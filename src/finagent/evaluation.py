from __future__ import annotations

import json
import re
from pathlib import Path

from finagent.agent import FinancialAgent
from finagent.models import ModelResponse
from finagent.retrieval import LocalRetriever, read_chunks


CITATION_LABEL_RE = re.compile(r"\[(S\d+)\]")
ATTACHED_CITATIONS_RE = re.compile(r"(?:\s*\[S\d+\])+")


def evaluate_retrieval(index_path: Path, cases_path: Path, *, limit: int = 5) -> dict[str, object]:
    """Evaluate deterministic retrieval against a small reviewer-visible golden set."""
    if limit < 1:
        raise ValueError("limit must be positive")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Retrieval evaluation cases must be a non-empty JSON list")
    all_chunks = read_chunks(index_path)
    offline_plan = ModelResponse("offline", "deepseek-v4-pro", "", False, "evaluation uses deterministic retrieval")
    details: list[dict[str, object]] = []
    passed = 0
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each retrieval evaluation case must be a JSON object")
        company = str(case.get("company", "")).strip()
        question = str(case.get("question", "")).strip()
        expected = case.get("expected_chunk_ids", [])
        if not company or not question or not isinstance(expected, list) or not expected:
            raise ValueError("Each retrieval case requires company, question, and expected_chunk_ids")
        company_lower = company.lower()
        chunks = [
            chunk for chunk in all_chunks
            if company_lower in chunk.title.lower() or company_lower in chunk.document_id.lower()
        ]
        query = FinancialAgent._retrieval_query(question, [], offline_plan)
        retrieved = [result.evidence.chunk_id for result in LocalRetriever(chunks).search(query, limit=limit)]
        hit = bool(set(map(str, expected)) & set(retrieved))
        passed += int(hit)
        details.append({
            "company": company,
            "question": question,
            "hit": hit,
            "expected_chunk_ids": expected,
            "retrieved_chunk_ids": retrieved,
        })
    total = len(details)
    return {"passed": passed, "total": total, "hit_at_k": passed / total, "limit": limit, "details": details}


def evaluate_golden_answers(index_path: Path, cases_path: Path) -> dict[str, object]:
    """Verify every checked-in golden sentence against explicitly mapped evidence chunks."""
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or len(cases) < 1:
        raise ValueError("Golden answer cases must be a non-empty JSON list")
    chunks = {chunk.chunk_id: chunk for chunk in read_chunks(index_path)}
    details: list[dict[str, object]] = []
    case_passed = 0
    sentence_passed = 0
    sentence_total = 0
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each golden answer case must be a JSON object")
        answer = str(case.get("answer", "")).strip()
        citation_map = case.get("citations")
        support_rows = case.get("sentence_support")
        if not case.get("id") or not case.get("question") or not answer:
            raise ValueError("Each golden answer case requires id, question, and answer")
        if not isinstance(citation_map, dict) or not citation_map:
            raise ValueError("Each golden answer case requires a citations object")
        if not isinstance(support_rows, list) or not support_rows:
            raise ValueError("Each golden answer case requires sentence_support")

        sentence_details: list[dict[str, object]] = []
        covered_spans: list[tuple[int, int]] = []
        for support in support_rows:
            if not isinstance(support, dict):
                raise ValueError("Each sentence_support entry must be an object")
            sentence = str(support.get("sentence", "")).strip()
            labels = support.get("citation_labels")
            phrases = support.get("required_evidence_phrases")
            if not sentence or not isinstance(labels, list) or not labels or not isinstance(phrases, list) or not phrases:
                raise ValueError("Each sentence requires citation_labels and required_evidence_phrases")
            if any(not isinstance(label, str) or not re.fullmatch(r"S\d+", label) for label in labels):
                raise ValueError("Citation labels must use the S<number> format")
            if any(not isinstance(phrase, str) or not phrase.strip() for phrase in phrases):
                raise ValueError("Required evidence phrases must be non-empty strings")
            unknown_labels = [label for label in labels if label not in citation_map]
            mapped_chunks = [chunks.get(str(citation_map[label])) for label in labels if label in citation_map]
            sentence_span = _find_cited_sentence(answer, sentence)
            attached_labels = sentence_span[0] if sentence_span else []
            if sentence_span:
                covered_spans.append(sentence_span[1])
            cited_in_answer = (
                sentence_span is not None
                and len(attached_labels) == len(labels)
                and set(attached_labels) == set(labels)
            )
            evidence_text = "\n".join(chunk.text for chunk in mapped_chunks if chunk is not None)
            normalized_evidence = _normalize_for_support(evidence_text)
            missing_phrases = [phrase for phrase in phrases if _normalize_for_support(phrase) not in normalized_evidence]
            supported = not unknown_labels and all(chunk is not None for chunk in mapped_chunks) and cited_in_answer and not missing_phrases
            sentence_total += 1
            sentence_passed += int(supported)
            sentence_details.append({
                "sentence": sentence,
                "citation_labels": labels,
                "attached_citation_labels": attached_labels,
                "chunk_ids": [citation_map.get(label) for label in labels],
                "cited_in_answer": cited_in_answer,
                "missing_labels": unknown_labels,
                "missing_evidence_phrases": missing_phrases,
                "supported": supported,
            })
        covered = [False] * len(answer)
        for start, end in covered_spans:
            covered[start:end] = [True] * (end - start)
        uncovered_answer_text = "".join(
            character for index, character in enumerate(answer) if not covered[index]
        ).strip()
        answer_fully_covered = not uncovered_answer_text
        passed = answer_fully_covered and all(bool(item["supported"]) for item in sentence_details)
        case_passed += int(passed)
        details.append({
            "id": case["id"],
            "company": case.get("company"),
            "question": case["question"],
            "passed": passed,
            "answer_fully_covered": answer_fully_covered,
            "uncovered_answer_text": uncovered_answer_text,
            "sentences": sentence_details,
        })
    return {
        "passed": case_passed,
        "total": len(details),
        "sentence_passed": sentence_passed,
        "sentence_total": sentence_total,
        "details": details,
    }


def _find_cited_sentence(answer: str, sentence: str) -> tuple[list[str], tuple[int, int]] | None:
    """Locate one declared sentence and only the citation labels attached directly to it."""
    start = answer.find(sentence)
    if start < 0 or answer.find(sentence, start + 1) >= 0:
        return None
    sentence_end = start + len(sentence)
    citation_match = ATTACHED_CITATIONS_RE.match(answer, sentence_end)
    span_end = citation_match.end() if citation_match else sentence_end
    labels = CITATION_LABEL_RE.findall(answer[sentence_end:span_end])
    return labels, (start, span_end)


def _normalize_for_support(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()
