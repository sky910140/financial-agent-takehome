from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from finagent.agent import FinancialAgent
from finagent.cli import main
from finagent.evaluation import evaluate_golden_answers
from finagent.integrity import validate_repository_data
from finagent.market import market_snapshot
from finagent.memory import PreferenceStore
from finagent.models import ModelResponse
from finagent.retrieval import chunk_document


class ReviewReadinessTests(unittest.TestCase):
    def test_citations_include_chunk_hash_excerpt_and_retrieval_score(self) -> None:
        chunk = chunk_document(
            "acme-10k",
            "Acme 10-K",
            "Liquidity was $10 million at year end.",
            "https://www.sec.gov/acme",
            "2026-02-20",
            "sec_10k",
            locator="accession 0000000000-26-000001",
        )[0].with_score(3.25)

        citation = FinancialAgent._cite([chunk])[0].citation

        self.assertEqual(citation.chunk_id, "acme-10k:0001")
        self.assertEqual(citation.evidence_sha256, hashlib.sha256(chunk.text.encode("utf-8")).hexdigest())
        self.assertEqual(citation.excerpt, chunk.text)
        self.assertEqual(citation.retrieval_score, 3.25)

    def test_memory_write_read_influence_modify_and_clear_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PreferenceStore(Path(directory) / "preferences.json")

            written = store.record("reviewer", "I care about liquidity risk and debt maturity.")
            self.assertEqual(written, ["debt maturity", "liquidity risk"])
            self.assertEqual(store.get("reviewer"), written)
            self.assertIn("liquidity risk", FinancialAgent._retrieval_query("What should I focus on?", written, _offline_plan()))

            modified = store.set("reviewer", ["cash flow", "profitability"])
            self.assertEqual(modified, ["cash flow", "profitability"])
            self.assertEqual(store.remove("reviewer", ["profitability"]), ["cash flow"])
            self.assertTrue(store.clear("reviewer"))
            self.assertEqual(store.get("reviewer"), [])

    def test_memory_rejects_unbounded_user_ids_and_non_whitelisted_topics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PreferenceStore(Path(directory) / "preferences.json")
            with self.assertRaises(ValueError):
                store.set("../other-user", ["cash flow"])
            with self.assertRaises(ValueError):
                store.set("reviewer", ["social security number"])

    def test_golden_answers_require_sentence_level_citations_and_support_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunk = chunk_document(
                "acme-10k", "Acme 10-K", "Revenue increased $2 billion or 10% in 2025.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )[0]
            index_path = root / "index.json"
            index_path.write_text(json.dumps([chunk.to_dict()]), encoding="utf-8")
            cases_path = root / "golden.json"
            cases_path.write_text(json.dumps([{
                "id": "acme-revenue",
                "company": "Acme",
                "question": "How did revenue change?",
                "answer": "Revenue increased $2 billion or 10% in 2025. [S1]",
                "citations": {"S1": chunk.chunk_id},
                "sentence_support": [{
                    "sentence": "Revenue increased $2 billion or 10% in 2025.",
                    "citation_labels": ["S1"],
                    "required_evidence_phrases": ["Revenue increased $2 billion or 10%"],
                }],
            }]), encoding="utf-8")

            report = evaluate_golden_answers(index_path, cases_path)

        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["sentence_passed"], 1)
        self.assertTrue(report["details"][0]["sentences"][0]["supported"])

    def test_golden_answers_do_not_borrow_citations_from_later_sentences(self) -> None:
        report = _evaluate_golden_case(
            "Revenue increased $2 billion. Operating income increased $1 billion. [S1]",
            [
                {
                    "sentence": "Revenue increased $2 billion.",
                    "citation_labels": ["S1"],
                    "required_evidence_phrases": ["Revenue increased $2 billion"],
                },
                {
                    "sentence": "Operating income increased $1 billion.",
                    "citation_labels": ["S1"],
                    "required_evidence_phrases": ["Operating income increased $1 billion"],
                },
            ],
        )

        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["sentence_passed"], 1)
        self.assertFalse(report["details"][0]["sentences"][0]["cited_in_answer"])
        self.assertTrue(report["details"][0]["sentences"][1]["cited_in_answer"])

    def test_golden_answers_reject_unregistered_answer_text(self) -> None:
        report = _evaluate_golden_case(
            "Revenue increased $2 billion. [S1]\nManagement expects further growth. [S1]",
            [{
                "sentence": "Revenue increased $2 billion.",
                "citation_labels": ["S1"],
                "required_evidence_phrases": ["Revenue increased $2 billion"],
            }],
        )

        self.assertEqual(report["sentence_passed"], 1)
        self.assertEqual(report["passed"], 0)
        self.assertFalse(report["details"][0]["answer_fully_covered"])

    def test_repository_data_integrity_matches_checked_in_snapshot(self) -> None:
        root = Path(__file__).resolve().parents[1]

        report = validate_repository_data(
            root / "data/index/filing_chunks.json",
            root / "data/market",
            root / "data/DATA_SNAPSHOT.json",
        )

        self.assertTrue(report["valid"])
        self.assertEqual(report["filings"]["document_count"], 10)
        self.assertEqual(report["filings"]["chunk_count"], 3978)
        self.assertEqual(report["markets"]["dataset_count"], 3)

    def test_market_response_labels_disclosed_and_deterministically_calculated_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            market = root / "market.csv"
            market.write_text("date,close,volume\n2024-01-02,100,10\n2024-01-03,110,30\n", encoding="utf-8")
            Path(f"{market}.meta.json").write_text(json.dumps({
                "symbol": "sh000300", "source_url": "https://example.com/market",
            }), encoding="utf-8")

            response = FinancialAgent(
                index_path=root / "missing.json",
                memory_path=root / "memory.json",
                market_path=market,
            ).ask("How did the CSI 300 index perform?")

        kinds = {item["kind"] for item in response.value_provenance}
        self.assertEqual(kinds, {"disclosed", "calculated"})
        self.assertIn("deterministic", response.value_provenance[-1]["method"])
        self.assertEqual(response.execution_mode, "offline_extractive")
        self.assertIsNotNone(response.fallback_reason)

    def test_market_snapshot_rejects_non_finite_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for field, value in (("close", "nan"), ("close", "inf"), ("volume", "nan"), ("volume", "inf")):
                with self.subTest(field=field, value=value):
                    first = {"date": "2024-01-02", "close": "100", "volume": "10"}
                    first[field] = value
                    path = root / f"{field}-{value}.csv"
                    path.write_text(
                        "date,close,volume\n"
                        f"{first['date']},{first['close']},{first['volume']}\n"
                        "2024-01-03,110,20\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, rf"Market {field} must be finite"):
                        market_snapshot(path)

    def test_filing_response_marks_source_numbers_as_disclosed_not_calculated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Cash totaled $10 million at year end.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index = root / "index.json"
            index.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")

            response = FinancialAgent(
                index_path=index,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
            ).ask("How much cash was disclosed?")

        self.assertEqual([item["kind"] for item in response.value_provenance], ["disclosed"])
        self.assertIn("SEC filing", response.value_provenance[0]["method"])

    def test_planning_failure_forces_explicit_offline_fallback(self) -> None:
        class PlanningFailureGateway:
            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                if provider == "deepseek" and "planner" in system:
                    return ModelResponse("offline", "deepseek-v4-pro", "", False, "TimeoutError: remote request unavailable")
                if provider == "doubao":
                    return ModelResponse("doubao", "doubao-seed-evolving", "Draft. [S1]", True)
                return ModelResponse("deepseek", "deepseek-v4-pro", "Verified. [S1]", True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Liquidity risk remained material.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index = root / "index.json"
            index.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            response = FinancialAgent(
                index_path=index,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
                models=PlanningFailureGateway(),  # type: ignore[arg-type]
            ).ask("Summarize liquidity risk.")

        self.assertEqual(response.execution_mode, "offline_extractive")
        self.assertIn("planning: TimeoutError", response.fallback_reason or "")
        self.assertIn("Offline extractive mode is active", response.answer)

    def test_invalid_market_data_is_not_replaced_with_filing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            market = root / "bad.csv"
            market.write_text("date,close\n2024-01-02,100\n", encoding="utf-8")
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "An index was used in compensation benchmarking.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index = root / "index.json"
            index.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")

            response = FinancialAgent(
                index_path=index,
                memory_path=root / "memory.json",
                market_path=market,
            ).ask("How did the CSI 300 index perform?")

        self.assertEqual(response.citations, [])
        self.assertIn("No local evidence matched", response.answer)

    def test_empty_optional_web_results_emit_an_explicit_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Liquidity remained adequate.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index = root / "index.json"
            index.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            with patch.object(FinancialAgent, "_web_evidence", return_value=[]):
                response = FinancialAgent(
                    index_path=index,
                    memory_path=root / "memory.json",
                    market_path=root / "missing.csv",
                ).ask("Summarize liquidity.", include_web=True)

        self.assertIn("Web search returned no usable results", response.warnings)

    def test_offline_demo_command_runs_without_model_or_network_dependencies(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["offline-demo"])

        self.assertEqual(exit_code, 0)
        self.assertIn("OFFLINE DEMO: PASS", stdout.getvalue())
        self.assertIn("Golden sentence citations:", stdout.getvalue())
        self.assertIn("Memory lifecycle: PASS", stdout.getvalue())

    def test_offline_demo_does_not_load_dotenv(self) -> None:
        with patch("finagent.cli._load_dotenv") as load_dotenv, patch("finagent.cli._run_offline_demo", return_value=0):
            exit_code = main(["offline-demo"])

        self.assertEqual(exit_code, 0)
        load_dotenv.assert_not_called()


def _offline_plan():
    from finagent.models import ModelResponse

    return ModelResponse("offline", "deepseek-v4-pro", "", False, "offline test")


def _evaluate_golden_case(answer: str, sentence_support: list[dict[str, object]]) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        chunk = chunk_document(
            "acme-10k",
            "Acme 10-K",
            "Revenue increased $2 billion. Operating income increased $1 billion.",
            "https://www.sec.gov/acme",
            "2026-02-20",
            "sec_10k",
        )[0]
        index_path = root / "index.json"
        index_path.write_text(json.dumps([chunk.to_dict()]), encoding="utf-8")
        cases_path = root / "golden.json"
        cases_path.write_text(json.dumps([{
            "id": "acme-results",
            "company": "Acme",
            "question": "How did results change?",
            "answer": answer,
            "citations": {"S1": chunk.chunk_id},
            "sentence_support": sentence_support,
        }]), encoding="utf-8")
        return evaluate_golden_answers(index_path, cases_path)


if __name__ == "__main__":
    unittest.main()
