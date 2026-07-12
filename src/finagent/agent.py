from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from finagent.market import market_snapshot
from finagent.memory import PreferenceStore
from finagent.models import ModelGateway, ModelResponse
from finagent.retrieval import LocalRetriever, read_chunks, tokenize
from finagent.sources import Citation, EvidenceChunk, SearchResult
from finagent.websearch import search_public_web


MARKET_TERMS = re.compile(r"\b(csi\s*300|沪深300|sh000300|index|指数|market performance|market data)\b", re.IGNORECASE)
CITATION_RE = re.compile(r"\[S(\d+)\]")
NUMBER_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")
TOKEN_COUNT_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)?|[\u4e00-\u9fff]+", re.IGNORECASE)
RETRIEVAL_EXPANSIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"liquidity|debt|流动性|债务", re.IGNORECASE), "capital resources borrowings maturity maturities"),
    (re.compile(r"revenue|profitability|income|margin|收入|利润|盈利", re.IGNORECASE), "operating income net income fiscal year"),
    (re.compile(r"competition|competitive|竞争", re.IGNORECASE), "compete competitor competitors competitive"),
    (re.compile(r"risk factors?|风险因素", re.IGNORECASE), "material adverse uncertainty"),
)
LOGGER = logging.getLogger(__name__)
PLAN_MAX_TOKENS = 600
PLAN_TIMEOUT_SECONDS = 25
ANALYSIS_MAX_TOKENS = 500
ANALYSIS_TIMEOUT_SECONDS = 45
VERIFICATION_MAX_TOKENS = 3_000
VERIFICATION_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    citations: list[Citation]
    preferences: list[str]
    model_trace: list[dict[str, str | bool | None]]
    evidence_count: int
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "answer": self.answer,
            "citations": [citation.to_dict() for citation in self.citations],
            "preferences": self.preferences,
            "model_trace": self.model_trace,
            "evidence_count": self.evidence_count,
            "warnings": self.warnings,
        }


class FinancialAgent:
    def __init__(
        self,
        *,
        index_path: Path,
        memory_path: Path,
        market_path: Path,
        models: ModelGateway | None = None,
    ) -> None:
        self.index_path = index_path
        self.memory = PreferenceStore(memory_path)
        self.market_path = market_path
        self.models = models or ModelGateway()

    def ask(
        self,
        question: str,
        *,
        user_id: str = "default",
        company: str | None = None,
        include_web: bool = False,
        limit: int = 5,
    ) -> AgentResponse:
        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty")
        preferences = self.memory.record(user_id, question)
        plan = self.models.complete(
            "deepseek",
            (
                "You are a financial research planner. Return up to eight retrieval terms or short phrases only. "
                "Identify factual dimensions needed; do not make claims, cite sources, or use outside facts."
            ),
            f"Question: {question}\nPersisted user preferences: {', '.join(preferences) or 'none'}",
            max_tokens=PLAN_MAX_TOKENS,
            timeout=PLAN_TIMEOUT_SECONDS,
        )
        query = self._retrieval_query(question, preferences, plan)
        is_market_query = bool(MARKET_TERMS.search(question))

        chunks = read_chunks(self.index_path)
        if company:
            company_lower = company.lower()
            chunks = [chunk for chunk in chunks if company_lower in chunk.title.lower() or company_lower in chunk.document_id.lower()]
        evidence = [item.evidence for item in LocalRetriever(chunks).search(query, limit=limit)]
        market_evidence: list[EvidenceChunk] = []
        warnings: list[str] = []
        if include_web:
            evidence.extend(self._web_evidence(question))
        if is_market_query and self.market_path.exists():
            try:
                snapshot = market_snapshot(self.market_path)
                market_evidence.append(EvidenceChunk(
                    chunk_id=f"market:{snapshot.symbol}:{snapshot.start_date}:{snapshot.end_date}",
                    document_id=f"market-{snapshot.symbol}",
                    title=f"{snapshot.symbol} daily close and volume ({snapshot.start_date} to {snapshot.end_date})",
                    text=(
                        f"{snapshot.symbol} moved from {snapshot.start_close:.2f} on {snapshot.start_date} "
                        f"to {snapshot.end_close:.2f} on {snapshot.end_date}, a {snapshot.change_percent:.2f}% change. "
                        f"Average daily volume in this period was {snapshot.average_volume:.0f}."
                    ),
                    source_url=snapshot.source_url,
                    published_at=snapshot.end_date,
                    source_type="market_data",
                    locator=f"{self.market_path.name}; rows {snapshot.start_date}..{snapshot.end_date}",
                ))
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                warning = f"Market data unavailable: {exc}"
                LOGGER.warning(warning)
                warnings.append(warning)
        elif is_market_query:
            warning = f"Market data unavailable: file not found: {self.market_path}"
            LOGGER.warning(warning)
            warnings.append(warning)

        # A pure market question should not be diluted by incidental filing mentions of "index".
        if market_evidence and not company:
            evidence = market_evidence + [chunk for chunk in evidence if chunk.source_type == "web_search"]
        else:
            evidence = market_evidence + evidence

        sources = self._cite(evidence)
        if sources:
            draft = self.models.complete(
                "doubao",
                (
                    "You are the filing analyst in an evidence-first financial agent. Answer only from the supplied evidence. "
                    "Every factual claim needs one of the supplied [S#] citations. If evidence is insufficient, say so plainly. "
                    "Do not provide investment advice or invent figures. Return at most four concise bullets and stay under 250 words."
                ),
                self._analysis_prompt(question, preferences, sources),
                max_tokens=ANALYSIS_MAX_TOKENS,
                timeout=ANALYSIS_TIMEOUT_SECONDS,
            )
            verification = self.models.complete(
                "deepseek",
                (
                    "You are the final citation verifier. Rewrite the draft only where needed to remove unsupported claims. "
                    "Use only the exact [S#] labels in the evidence. Retain an uncertainty statement when evidence is weak. "
                    "Return only the final answer, at most four concise bullets and under 250 words."
                ),
                self._verification_prompt(question, sources, draft.text),
                max_tokens=VERIFICATION_MAX_TOKENS,
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
        else:
            draft = ModelResponse("offline", "doubao-seed-evolving", "", False, "No evidence available")
            verification = ModelResponse("offline", "deepseek-v4-pro", "", False, "No evidence available")

        fallback_reason = self._fallback_reason(plan, draft, verification)
        fallback = self._offline_answer(question, preferences, sources, fallback_reason)
        final = fallback
        if (
            draft.used_remote_model
            and verification.used_remote_model
            and self._has_valid_citations(verification.text, sources)
            and self._has_supported_numbers(verification.text, sources)
        ):
            final = self._sanitize_citations(verification.text, sources)

        cited_sources = self._referenced_sources(final, sources)

        return AgentResponse(
            answer=final,
            citations=[source.citation for source in cited_sources],
            preferences=preferences,
            model_trace=[self._trace("planning", plan), self._trace("analysis", draft), self._trace("verification", verification)],
            evidence_count=len(cited_sources),
            warnings=warnings,
        )

    @staticmethod
    def _retrieval_query(question: str, preferences: list[str], plan: ModelResponse) -> str:
        """Bound model output to retrieval-term expansion, never to factual evidence or final prose."""
        base_terms = [question, *preferences]
        base_terms.extend(expansion for pattern, expansion in RETRIEVAL_EXPANSIONS if pattern.search(question))
        raw_question_terms = TOKEN_COUNT_RE.findall(question)
        if plan.used_remote_model and plan.text and len(raw_question_terms) <= 6:
            base_terms.append(" ".join(tokenize(plan.text)[:24]))
        return " ".join(term for term in base_terms if term)

    @staticmethod
    def _trace(stage: str, response: ModelResponse) -> dict[str, str | bool | None]:
        return {
            "stage": stage,
            "provider": response.provider,
            "model": response.model,
            "used_remote_model": response.used_remote_model,
            "status": "ok" if response.used_remote_model else response.error,
        }

    @staticmethod
    def _cite(evidence: list[EvidenceChunk]) -> list[SearchResult]:
        return [SearchResult(
            evidence=chunk,
            citation=Citation(
                label=f"[S{index}]",
                title=chunk.title,
                source_url=chunk.source_url,
                published_at=chunk.published_at,
                source_type=chunk.source_type,
                document_id=chunk.document_id,
                locator=f"{chunk.locator}; chunk {chunk.chunk_id}" if chunk.locator else f"chunk {chunk.chunk_id}",
            ),
        ) for index, chunk in enumerate(evidence, start=1)]

    @staticmethod
    def _web_evidence(question: str) -> list[EvidenceChunk]:
        evidence: list[EvidenceChunk] = []
        for index, result in enumerate(search_public_web(question), start=1):
            evidence.append(EvidenceChunk(
                chunk_id=f"web:{index}",
                document_id=f"web:{index}",
                title=result.title,
                text=result.snippet or result.title,
                source_url=result.url,
                published_at=None,
                source_type="web_search",
                locator="search result snippet",
            ))
        return evidence

    @staticmethod
    def _analysis_prompt(question: str, preferences: list[str], sources: list[SearchResult]) -> str:
        return (
            f"Question: {question}\n"
            f"User preferences: {', '.join(preferences) or 'none'}\n\n"
            "Evidence:\n" + "\n\n".join(
                f"{source.citation.label} {source.evidence.title}\n{source.evidence.text}" for source in sources
            )
        )

    @staticmethod
    def _verification_prompt(question: str, sources: list[SearchResult], draft: str) -> str:
        labels = ", ".join(source.citation.label for source in sources) or "none"
        evidence = "\n".join(f"{source.citation.label} {source.evidence.text}" for source in sources)
        return f"Question: {question}\nAllowed citation labels: {labels}\n\nDraft:\n{draft}\n\nEvidence:\n{evidence}"

    @staticmethod
    def _has_valid_citations(answer: str, sources: list[SearchResult]) -> bool:
        valid = {source.citation.label for source in sources}
        labels = {f"[S{number}]" for number in CITATION_RE.findall(answer)}
        return bool(labels & valid) and labels.issubset(valid)

    @staticmethod
    def _sanitize_citations(answer: str, sources: list[SearchResult]) -> str:
        valid = {source.citation.label for source in sources}
        return CITATION_RE.sub(lambda match: match.group(0) if match.group(0) in valid else "[citation unavailable]", answer).strip()

    @staticmethod
    def _has_supported_numbers(answer: str, sources: list[SearchResult]) -> bool:
        """Reject numeric drift by requiring generated values to occur in supplied evidence."""
        clean_answer = CITATION_RE.sub("", answer)
        clean_answer = re.sub(r"(?m)^\s*\d+[.)]\s+", "", clean_answer)
        answer_numbers = FinancialAgent._normalized_numbers(clean_answer)
        evidence_text = "\n".join(f"{source.evidence.title}\n{source.evidence.text}" for source in sources)
        return answer_numbers.issubset(FinancialAgent._normalized_numbers(evidence_text))

    @staticmethod
    def _normalized_numbers(text: str) -> set[str]:
        values: set[str] = set()
        for match in NUMBER_RE.findall(text):
            try:
                values.add(format(Decimal(match.replace(",", "")).normalize(), "f"))
            except InvalidOperation:
                continue
        return values

    @staticmethod
    def _referenced_sources(answer: str, sources: list[SearchResult]) -> list[SearchResult]:
        labels = {f"[S{number}]" for number in CITATION_RE.findall(answer)}
        return [source for source in sources if source.citation.label in labels]

    @staticmethod
    def _fallback_reason(plan: ModelResponse, draft: ModelResponse, verification: ModelResponse) -> str:
        failures = [
            f"{stage}: {response.error or 'remote model unavailable'}"
            for stage, response in (("planning", plan), ("analysis", draft), ("verification", verification))
            if not response.used_remote_model
        ]
        return "; ".join(failures) or "remote output did not pass the citation guard"

    @staticmethod
    def _offline_answer(
        question: str,
        preferences: list[str],
        sources: list[SearchResult],
        fallback_reason: str,
    ) -> str:
        if not sources:
            return (
                "## Evidence-backed answer\n\n"
                "No local evidence matched this question. Run the SEC download and index commands, or repeat with `--web` for explicitly labelled public-web snippets. "
                "The agent will not infer an answer without evidence."
            )
        terms = set(tokenize(question)) | {term for preference in preferences for term in tokenize(preference)}
        bullets = []
        seen_excerpts: set[str] = set()
        for source in sources:
            quote = source.evidence.text if source.evidence.source_type == "market_data" else FinancialAgent._best_excerpt(source.evidence.text, terms)
            normalized_quote = re.sub(r"\W+", " ", quote.lower()).strip()
            if normalized_quote in seen_excerpts:
                continue
            seen_excerpts.add(normalized_quote)
            bullets.append(f"- {quote} {source.citation.label}")
            if len(bullets) == 5:
                break
        preference_line = f"\n\nApplied remembered preferences: {', '.join(preferences)}." if preferences else ""
        return (
            "## Evidence-backed answer\n\n"
            f"Offline extractive mode is active because the full two-model remote path was unavailable ({fallback_reason}). "
            "The following are retrieved source excerpts, not a synthesized investment recommendation.\n\n"
            + "\n".join(bullets)
            + preference_line
        )

    @staticmethod
    def _best_excerpt(text: str, terms: set[str]) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        ranked = sorted(
            sentences,
            key=lambda sentence: (-sum(term in tokenize(sentence) for term in terms), len(sentence)),
        )
        excerpt = (ranked[0] if ranked else text).strip()
        return excerpt[:520] + ("..." if len(excerpt) > 520 else "")


def render_markdown(response: AgentResponse, *, include_trace: bool = False) -> str:
    sources = "\n".join(
        f"- {citation.label} [{citation.title}]({citation.source_url})"
        f" | {citation.source_type} | {citation.published_at or 'date unavailable'} | {citation.locator or 'locator unavailable'}"
        for citation in response.citations
    ) or "- No sources retrieved."
    output = f"{response.answer}\n\n## Sources\n\n{sources}"
    if response.warnings:
        output += "\n\n## Data warnings\n\n" + "\n".join(f"- {warning}" for warning in response.warnings)
    if include_trace:
        trace = "\n".join(
            f"- {item['stage']}: {item['provider']} / {item['model']} / remote={item['used_remote_model']} / {item['status']}"
            for item in response.model_trace
        )
        output += f"\n\n## Agent trace\n\n{trace}"
    return output


def _safe_external_url(value: str) -> str | None:
    """Only expose absolute HTTP(S) links from external evidence in HTML output."""
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return None


def _render_html_blocks(markdown: str) -> str:
    """Render the small, controlled Markdown subset emitted by the agent without trusting HTML."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{'<br>\n'.join(escape(line) for line in paragraph)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{escape(item)}</li>" for item in list_items) + "</ul>")
            list_items.clear()

    for line in markdown.splitlines():
        if line.startswith("## "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:])
        elif not line.strip():
            flush_paragraph()
            flush_list()
        else:
            flush_list()
            paragraph.append(line)
    flush_paragraph()
    flush_list()
    return "\n".join(blocks) or "<p>No answer was generated.</p>"


def render_html(response: AgentResponse, *, include_trace: bool = False) -> str:
    """Render a self-contained, safe HTML research report from a structured response."""
    source_items = []
    for citation in response.citations:
        source_url = _safe_external_url(citation.source_url)
        title = escape(citation.title)
        if source_url:
            title = (
                f'<a href="{escape(source_url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer" referrerpolicy="no-referrer">{title}</a>'
            )
        details = " | ".join(escape(value) for value in (
            citation.label,
            citation.source_type,
            citation.published_at or "date unavailable",
            citation.locator or "locator unavailable",
        ))
        source_items.append(f"<li>{title}<span class=\"source-meta\">{details}</span></li>")
    sources = "\n".join(source_items) or "<li>No sources retrieved.</li>"

    preferences = ""
    if response.preferences:
        preferences = "<section><h2>Remembered preferences</h2><p>" + escape(", ".join(response.preferences)) + "</p></section>"
    warnings = ""
    if response.warnings:
        warnings = "<section><h2>Data warnings</h2><ul>" + "".join(
            f"<li>{escape(warning)}</li>" for warning in response.warnings
        ) + "</ul></section>"
    trace = ""
    if include_trace:
        trace_items = "".join(
            "<li>" + escape(
                f"{item['stage']}: {item['provider']} / {item['model']} / "
                f"remote={item['used_remote_model']} / {item['status']}"
            ) + "</li>"
            for item in response.model_trace
        ) or "<li>No model trace recorded.</li>"
        trace = f"<section><h2>Agent trace</h2><ul>{trace_items}</ul></section>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Financial Agent Research Report</title>
<style>
body {{ margin: 0; background: #f7f8fa; color: #18212b; font: 16px/1.55 Arial, sans-serif; }}
main {{ max-width: 900px; margin: 32px auto; padding: 0 24px 40px; }}
header, section {{ border-bottom: 1px solid #d9dde3; padding: 20px 0; }}
h1, h2 {{ margin: 0 0 12px; color: #102a43; }}
h1 {{ font-size: 28px; }} h2 {{ font-size: 20px; }}
p, ul {{ margin: 0 0 12px; }} li {{ margin: 7px 0; }}
a {{ color: #0b5cad; }} .source-meta {{ display: block; color: #52606d; font-size: 13px; }}
</style>
</head>
<body>
<main>
<header><h1>Financial Agent Research Report</h1><p>Evidence-backed research output. Not investment advice.</p></header>
<section>{_render_html_blocks(response.answer)}</section>
<section><h2>Sources</h2><ul>{sources}</ul></section>
{preferences}
{warnings}
{trace}
</main>
</body>
</html>"""
