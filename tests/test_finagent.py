from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from finagent.agent import AgentResponse, FinancialAgent, render_html, render_markdown
from finagent.cli import _configure_console_encoding, main
from finagent.evaluation import evaluate_retrieval
from finagent.ingest import build_filing_index, html_to_text, is_xbrl_noise
from finagent.market import download_major_indices, market_snapshot
from finagent.memory import PreferenceStore
from finagent.models import ModelGateway, ModelResponse
from finagent.retrieval import LocalRetriever, chunk_document, tokenize
from finagent.sec import download_sec_10k, validate_sec_user_agent
from finagent.sources import Citation
from finagent.websearch import WebResult, _result_url


class FinancialAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        # CLI tests load .env; keep the unit suite offline even on a configured developer machine.
        self._model_keys = patch.dict(os.environ, {"DOUBAO_API_KEY": "", "DEEPSEEK_API_KEY": ""}, clear=False)
        self._model_keys.start()

    def tearDown(self) -> None:
        self._model_keys.stop()

    def test_chunks_keep_verifiable_source_metadata(self) -> None:
        chunks = chunk_document(
            document_id="acme-2025-10k",
            title="Acme 2025 Form 10-K",
            text="Liquidity risk increased because debt maturities concentrate in 2027. " * 8,
            source_url="https://www.sec.gov/Archives/example.htm",
            published_at="2025-02-20",
            source_type="sec_10k",
            chunk_size=120,
            overlap=20,
        )

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].source_url, "https://www.sec.gov/Archives/example.htm")
        self.assertEqual(chunks[0].source_type, "sec_10k")
        self.assertEqual(chunks[0].chunk_id, "acme-2025-10k:0001")

    def test_retrieval_ranks_relevant_evidence_and_returns_citation(self) -> None:
        chunks = chunk_document(
            "acme-2025-10k",
            "Acme 2025 Form 10-K",
            "The company faces liquidity risk from a revolving credit facility and debt maturities.",
            "https://www.sec.gov/Archives/example.htm",
            "2025-02-20",
            "sec_10k",
        ) + chunk_document(
            "acme-2025-10k",
            "Acme 2025 Form 10-K",
            "The company sells consumer devices through retail partners.",
            "https://www.sec.gov/Archives/example.htm",
            "2025-02-20",
            "sec_10k",
        )
        results = LocalRetriever(chunks).search("summarize liquidity and debt risk", limit=1)

        self.assertEqual(len(results), 1)
        self.assertIn("liquidity", results[0].evidence.text.lower())
        self.assertEqual(results[0].citation.label, "[S1]")

    def test_retrieval_evaluation_reports_hit_at_k(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Liquidity and capital resources remained sufficient.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index_path = root / "index.json"
            index_path.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            cases_path = root / "cases.json"
            cases_path.write_text(json.dumps([{
                "company": "Acme",
                "question": "Summarize liquidity risk.",
                "expected_chunk_ids": [chunks[0].chunk_id],
            }]), encoding="utf-8")

            report = evaluate_retrieval(index_path, cases_path, limit=5)

        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["hit_at_k"], 1.0)

    def test_market_snapshot_calculates_period_change_and_keeps_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "csi300.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "close", "volume"])
                writer.writeheader()
                writer.writerows([
                    {"date": "2024-01-02", "close": "3300", "volume": "1200000"},
                    {"date": "2024-01-03", "close": "3400", "volume": "1500000"},
                ])
            Path(f"{csv_path}.meta.json").write_text(json.dumps({"source_url": "https://query1.finance.yahoo.com/example"}), encoding="utf-8")

            snapshot = market_snapshot(csv_path, start="2024-01-02", end="2024-01-03")

        self.assertEqual(snapshot.start_close, 3300.0)
        self.assertEqual(snapshot.end_close, 3400.0)
        self.assertAlmostEqual(snapshot.change_percent, 3.03, places=2)
        self.assertEqual(snapshot.source_url, "https://query1.finance.yahoo.com/example")

    def test_preferences_are_persisted_and_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PreferenceStore(Path(directory) / "memory.json")
            store.record("alice", "I care most about liquidity risk and debt maturity.")
            store.record("alice", "Please focus on cash flow too.")

            preferences = store.get("alice")

        self.assertEqual(preferences, ["cash flow", "debt maturity", "liquidity risk"])

    def test_interested_in_is_an_explicit_preference_statement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PreferenceStore(Path(directory) / "memory.json")
            preferences = store.record("alice", "I'm interested in cash flow and valuation.")

        self.assertEqual(preferences, ["cash flow", "valuation"])

    def test_model_gateway_is_explicit_when_keys_are_missing(self) -> None:
        gateway = ModelGateway(doubao_api_key=None, deepseek_api_key=None)
        result = gateway.complete("doubao", "system", "user")

        self.assertEqual(result.provider, "offline")
        self.assertFalse(result.used_remote_model)
        self.assertNotIn("api_key", result.text.lower())

    def test_model_gateway_defaults_to_supported_deepseek_v4_model_name(self) -> None:
        gateway = ModelGateway(doubao_api_key=None, deepseek_api_key=None)

        self.assertEqual(gateway.providers["deepseek"]["model"], "deepseek-v4-pro")

    def test_model_gateway_reports_safe_http_status_without_response_body(self) -> None:
        error = HTTPError("https://example.com", 404, "Not Found", None, None)
        with patch("finagent.models.urlopen", side_effect=error):
            result = ModelGateway(doubao_api_key="test-key", deepseek_api_key=None).complete("doubao", "system", "user")
        error.close()

        self.assertFalse(result.used_remote_model)
        self.assertEqual(result.error, "HTTP 404: remote request unavailable")

    def test_model_gateway_treats_empty_content_as_remote_failure(self) -> None:
        class EmptyResponse:
            def __enter__(self) -> "EmptyResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            @staticmethod
            def read() -> bytes:
                return b'{"choices": [{"message": {"content": ""}}]}'

        with patch("finagent.models.urlopen", return_value=EmptyResponse()):
            result = ModelGateway(doubao_api_key=None, deepseek_api_key="test-key").complete(
                "deepseek", "system", "user",
            )

        self.assertFalse(result.used_remote_model)
        self.assertEqual(result.error, "Remote model returned empty content")

    def test_model_gateway_caps_completion_length_for_interactive_latency(self) -> None:
        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            @staticmethod
            def read() -> bytes:
                return b'{"choices": [{"message": {"content": "[S1] concise answer"}}]}'

        with patch("finagent.models.urlopen", return_value=FakeResponse()) as urlopen:
            result = ModelGateway(doubao_api_key="test-key", deepseek_api_key=None).complete(
                "doubao", "system", "user", max_tokens=96, timeout=7,
            )

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(result.used_remote_model)
        self.assertEqual(payload["max_tokens"], 96)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7)

    def test_verifier_failure_never_allows_remote_draft(self) -> None:
        class RejectingGateway:
            def __init__(self) -> None:
                self.deepseek_calls = 0

            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                if provider == "doubao":
                    return ModelResponse("doubao", "doubao-seed-evolving", "Unsupported draft. [S1]", True)
                self.deepseek_calls += 1
                if self.deepseek_calls == 1:
                    return ModelResponse("deepseek", "deepseek-v4-pro", "liquidity", True)
                return ModelResponse("offline", "deepseek-v4-pro", "", False, "verifier unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_path = root / "index.json"
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Liquidity remained adequate during the period.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index_path.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            response = FinancialAgent(
                index_path=index_path,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
                models=RejectingGateway(),  # type: ignore[arg-type]
            ).ask("Summarize liquidity.")

        self.assertNotIn("Unsupported draft", response.answer)
        self.assertIn("extractive mode", response.answer)

    def test_explicit_financial_query_does_not_use_stochastic_plan_terms(self) -> None:
        plan = ModelResponse("deepseek", "deepseek-v4-pro", "foreign exchange hedge derivatives", True)

        query = FinancialAgent._retrieval_query(
            "Summarize liquidity and debt-related risks for the company.", [], plan,
        )

        self.assertNotIn("foreign exchange", query)
        self.assertIn("capital resources", query)

    def test_explicit_revenue_query_gets_deterministic_financial_expansion(self) -> None:
        plan = ModelResponse("offline", "deepseek-v4-pro", "", False, "offline")

        query = FinancialAgent._retrieval_query(
            "How did revenue or profitability change compared with the prior year?", [], plan,
        )

        self.assertIn("operating income", query)
        self.assertIn("net income", query)

    def test_timeout_fallback_does_not_claim_credentials_are_missing(self) -> None:
        class TimeoutGateway:
            def __init__(self) -> None:
                self.deepseek_calls = 0

            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                if provider == "doubao":
                    return ModelResponse("offline", "doubao-seed-evolving", "", False, "TimeoutError: remote request unavailable")
                self.deepseek_calls += 1
                return ModelResponse("deepseek", "deepseek-v4-pro", "liquidity" if self.deepseek_calls == 1 else "Insufficient evidence.", True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_path = root / "index.json"
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Liquidity remained adequate during the period.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index_path.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            response = FinancialAgent(
                index_path=index_path,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
                models=TimeoutGateway(),  # type: ignore[arg-type]
            ).ask("Summarize liquidity.")

        self.assertIn("full two-model remote path was unavailable", response.answer)
        self.assertNotIn("credentials are unavailable", response.answer)

    def test_response_only_lists_sources_used_by_final_answer(self) -> None:
        class SelectiveGateway:
            def __init__(self) -> None:
                self.deepseek_calls = 0

            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                if provider == "doubao":
                    return ModelResponse("doubao", "doubao-seed-evolving", "Draft [S1] [S2]", True)
                self.deepseek_calls += 1
                if self.deepseek_calls == 1:
                    return ModelResponse("deepseek", "deepseek-v4-pro", "liquidity debt", True)
                return ModelResponse("deepseek", "deepseek-v4-pro", "Only the first finding is supported. [S1]", True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_path = root / "index.json"
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Liquidity remained adequate. Debt maturities increased refinancing risk.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k", chunk_size=40, overlap=10,
            )
            index_path.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            response = FinancialAgent(
                index_path=index_path,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
                models=SelectiveGateway(),  # type: ignore[arg-type]
            ).ask("Summarize liquidity and debt.")

        self.assertEqual([citation.label for citation in response.citations], ["[S1]"])
        self.assertEqual(response.evidence_count, 1)

    def test_numeric_guard_rejects_value_not_present_in_evidence(self) -> None:
        class DriftingGateway:
            def __init__(self) -> None:
                self.deepseek_calls = 0

            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                if provider == "doubao":
                    return ModelResponse("doubao", "doubao-seed-evolving", "Cash totaled $134.4 billion. [S1]", True)
                self.deepseek_calls += 1
                if self.deepseek_calls == 1:
                    return ModelResponse("deepseek", "deepseek-v4-pro", "cash liquidity", True)
                return ModelResponse("deepseek", "deepseek-v4-pro", "Cash totaled $134.4 billion. [S1]", True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_path = root / "index.json"
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Cash and marketable securities totaled $132.4 billion.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index_path.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            response = FinancialAgent(
                index_path=index_path,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
                models=DriftingGateway(),  # type: ignore[arg-type]
            ).ask("How much cash was reported?")

        self.assertNotIn("$134.4", response.answer)
        self.assertIn("$132.4", response.answer)

    def test_index_and_agent_produce_an_offline_cited_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "acme.html").write_text(
                "<html><body><h1>Risk Factors</h1><p>" + ("Acme faces liquidity risk because debt maturities are concentrated in 2027. " * 8) + "</p></body></html>",
                encoding="utf-8",
            )
            (docs / "manifest.jsonl").write_text(json.dumps({
                "document_id": "acme-2025-10k",
                "company": "Acme Inc.",
                "form": "10-K",
                "report_date": "2025-12-31",
                "filing_date": "2026-02-20",
                "accession_number": "000000-26-000001",
                "source_url": "https://www.sec.gov/Archives/acme.htm",
                "local_path": "acme.html",
            }) + "\n", encoding="utf-8")
            index = root / "index.json"
            documents, chunks = build_filing_index(docs, index, chunk_size=120)
            response = FinancialAgent(
                index_path=index,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
                models=ModelGateway(doubao_api_key=None, deepseek_api_key=None),
            ).ask("Please focus on liquidity risk and debt maturity.", user_id="alice")

        self.assertEqual(documents, 1)
        self.assertGreater(chunks, 0)
        self.assertIn("[S1]", response.answer)
        self.assertEqual(response.preferences, ["debt maturity", "liquidity risk"])
        self.assertEqual(response.citations[0].source_type, "sec_10k")

    def test_web_results_are_explicitly_labelled_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "finagent.agent.search_public_web",
            return_value=[WebResult("SEC filing page", "https://www.sec.gov/example", "Public result snippet")],
        ):
            root = Path(directory)
            response = FinancialAgent(
                index_path=root / "absent-index.json",
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
            ).ask("Find this company filing", include_web=True)

        self.assertEqual(response.evidence_count, 1)
        self.assertEqual(response.citations[0].source_type, "web_search")
        self.assertIn("Public result snippet", response.answer)

    def test_sec_downloader_writes_source_manifest(self) -> None:
        submissions = {"filings": {"recent": {
            "form": ["10-K"],
            "accessionNumber": ["000001-26-000001"],
            "primaryDocument": ["annual.htm"],
            "filingDate": ["2026-02-20"],
            "reportDate": ["2025-12-31"],
        }}}
        with tempfile.TemporaryDirectory() as directory, patch("finagent.sec._get_json", return_value=submissions), patch(
            "finagent.sec._get_bytes", return_value=b"<html><body>Annual report</body></html>"
        ):
            records = download_sec_10k(
                Path(directory),
                user_agent="FinancialAgent test@example.com",
                companies=(("ACME", "Acme Inc.", 1),),
            )
            manifest = Path(directory) / "manifest.jsonl"

            row = json.loads(manifest.read_text(encoding="utf-8"))

        self.assertEqual(len(records), 1)
        self.assertEqual(row["source_type"], "sec_10k")
        self.assertIn("www.sec.gov/Archives", row["source_url"])

    def test_sec_downloader_preserves_existing_manifest_records(self) -> None:
        submissions = {"filings": {"recent": {
            "form": ["10-K"],
            "accessionNumber": ["000001-26-000001"],
            "primaryDocument": ["annual.htm"],
            "filingDate": ["2026-02-20"],
            "reportDate": ["2025-12-31"],
        }}}
        with tempfile.TemporaryDirectory() as directory, patch("finagent.sec._get_json", return_value=submissions), patch(
            "finagent.sec._get_bytes", return_value=b"<html><body>Annual report</body></html>"
        ):
            root = Path(directory)
            (root / "manifest.jsonl").write_text(json.dumps({"document_id": "older-filing", "source_url": "https://www.sec.gov/older"}) + "\n", encoding="utf-8")
            download_sec_10k(root, user_agent="FinancialAgent test@example.com", companies=(("ACME", "Acme Inc.", 1),))
            rows = [json.loads(line) for line in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual({row["document_id"] for row in rows}, {"older-filing", "acme-2025-12-31-10k-00000126000001"})

    def test_sec_downloader_uses_historical_submission_files_to_fill_requested_years(self) -> None:
        submissions = {
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "accessionNumber": ["000001-26-000001"],
                    "primaryDocument": ["annual-2025.htm"],
                    "filingDate": ["2026-02-20"],
                    "reportDate": ["2025-12-31"],
                },
                "files": [{"name": "CIK0000000001-submissions-001.json"}],
            }
        }
        historical = {
            "form": ["10-K"],
            "accessionNumber": ["000001-25-000001"],
            "primaryDocument": ["annual-2024.htm"],
            "filingDate": ["2025-02-20"],
            "reportDate": ["2024-12-31"],
        }
        with tempfile.TemporaryDirectory() as directory, patch(
            "finagent.sec._get_json", side_effect=[submissions, historical]
        ) as get_json, patch("finagent.sec._get_bytes", return_value=b"<html><body>Annual report</body></html>"):
            records = download_sec_10k(
                Path(directory), years=2, user_agent="FinancialAgent test@example.com",
                companies=(("ACME", "Acme Inc.", 1),),
            )

        self.assertEqual(len(records), 2)
        self.assertEqual(get_json.call_count, 2)

    def test_cli_reports_incomplete_sec_download_as_failure(self) -> None:
        stderr = io.StringIO()
        with patch("finagent.cli.download_sec_10k", return_value=[]), redirect_stderr(stderr):
            exit_code = main([
                "download-sec", "--years", "1", "--user-agent", "FinancialAgent test@example.com",
            ])

        self.assertEqual(exit_code, 2)
        self.assertIn("incomplete", stderr.getvalue().lower())

    def test_sec_user_agent_requires_contact_information(self) -> None:
        with self.assertRaises(ValueError):
            validate_sec_user_agent("FinancialAgent")

    def test_html_text_normalizes_typographic_punctuation_for_cli_output(self) -> None:
        self.assertEqual(html_to_text("<p>Company&#8217;s debt - 2025</p>"), "Company's debt - 2025")

    def test_xbrl_boilerplate_is_identified_as_noise(self) -> None:
        self.assertTrue(is_xbrl_noise("http://fasb.org/us-gaap/2025 xbrli:context xmlns:dei us-gaap:Revenue"))
        self.assertFalse(is_xbrl_noise("Liquidity and capital resources depend on cash generated from operations."))

    def test_chinese_tokenizer_uses_overlapping_bigrams(self) -> None:
        self.assertEqual(tokenize("上海证券交易所"), ["上海", "海证", "证券", "券交", "交易", "易所"])

    def test_hyphenated_financial_terms_also_emit_component_tokens(self) -> None:
        self.assertEqual(tokenize("debt-related"), ["debt-related", "debt", "related"])

    def test_tokenizer_removes_query_stopwords_and_emits_financial_phrases(self) -> None:
        self.assertEqual(tokenize("What does the company say about competition?"), ["competition"])
        self.assertIn("cash_flow", tokenize("Summarize cash flow risks."))

    def test_major_index_bundle_uses_three_supported_symbols(self) -> None:
        calls: list[tuple[Path, str]] = []

        def fake_download(output_path: Path, *, symbol: str, start_year: int, end_year: int | None) -> int:
            calls.append((output_path, symbol))
            return 100

        with tempfile.TemporaryDirectory() as directory, patch("finagent.market.download_index_history", side_effect=fake_download):
            counts = download_major_indices(Path(directory), start_year=2005, end_year=2005)

        self.assertEqual(counts, {"csi300": 100, "sse_composite": 100, "szse_component": 100})
        self.assertEqual({symbol for _, symbol in calls}, {"sh000300", "sh000001", "sz399001"})

    def test_market_snapshot_rejects_malformed_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("date,close\n2024-01-01,3300\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required columns"):
                market_snapshot(path)

    def test_market_snapshot_rejects_duplicate_or_unsorted_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text(
                "date,close,volume\n2024-01-03,3300,100\n2024-01-02,3400,120\n2024-01-02,3500,130\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                market_snapshot(path)

    def test_market_snapshot_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.csv"
            path.write_text(
                "date,close,volume\n2024-01-02,3300,100\n2024-01-03,3400,120\n",
                encoding="utf-8",
            )
            Path(f"{path}.meta.json").write_text(json.dumps({
                "source_url": "https://example.com/market",
                "sha256": hashlib.sha256(b"different data").hexdigest(),
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "checksum"):
                market_snapshot(path)

    def test_agent_returns_data_warning_when_market_data_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            market_file = root / "bad.csv"
            market_file.write_text("date,close\n2024-01-01,3300\n", encoding="utf-8")
            with self.assertLogs("finagent.agent", level="WARNING") as logs:
                response = FinancialAgent(
                    index_path=root / "absent-index.json",
                    memory_path=root / "memory.json",
                    market_path=market_file,
                ).ask("How did the CSI 300 index perform?")

        self.assertEqual(len(response.warnings), 1)
        self.assertIn("Market data unavailable", logs.output[0])
        self.assertIn("Market data unavailable", response.warnings[0])
        self.assertIn("## Data warnings", render_markdown(response))

    def test_html_output_escapes_dynamic_content_and_allows_only_http_links(self) -> None:
        response = AgentResponse(
            answer="## Evidence-backed answer\n\n- <script>alert('xss')</script> [S1]",
            citations=[
                Citation("[S1]", "<img src=x onerror=alert(1)>", "https://www.sec.gov/example?a=1&b=2", "2026-02-20", "sec_10k", "acme", "chunk 1"),
                Citation("[S2]", "Unsafe source", "javascript:alert(1)", None, "web_search", "web:2", "snippet"),
            ],
            preferences=["liquidity risk"],
            model_trace=[{"stage": "analysis", "provider": "doubao", "model": "doubao-seed-evolving", "used_remote_model": True, "status": "ok"}],
            evidence_count=2,
            warnings=["<b>Market source delayed</b>"],
        )

        output = render_html(response, include_trace=True)

        self.assertIn("Content-Security-Policy", output)
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", output)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", output)
        self.assertIn('href="https://www.sec.gov/example?a=1&amp;b=2"', output)
        self.assertIn('rel="noopener noreferrer"', output)
        self.assertNotIn("javascript:", output)
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;b&gt;Market source delayed&lt;/b&gt;", output)
        self.assertIn("Execution mode", output)
        self.assertIn("offline_extractive", output)

    def test_cli_html_mode_renders_a_standalone_report(self) -> None:
        response = AgentResponse(
            answer="## Evidence-backed answer\n\nA cited finding. [S1]",
            citations=[Citation("[S1]", "Acme 10-K", "https://www.sec.gov/acme", "2026-02-20", "sec_10k", "acme", "chunk 1")],
            preferences=[],
            model_trace=[],
            evidence_count=1,
            warnings=[],
        )
        stdout = io.StringIO()
        with patch("finagent.cli.FinancialAgent.ask", return_value=response), redirect_stdout(stdout):
            exit_code = main(["ask", "test", "--html"])

        self.assertEqual(exit_code, 0)
        self.assertTrue(stdout.getvalue().lower().startswith("<!doctype html>"))
        self.assertIn("Evidence-backed answer", stdout.getvalue())

    def test_market_evidence_is_prioritized_for_market_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            market_file = root / "market.csv"
            market_file.write_text("date,close,volume\n2024-01-02,3300,100\n2024-01-03,3400,120\n", encoding="utf-8")
            Path(f"{market_file}.meta.json").write_text(json.dumps({"symbol": "sh000001", "source_url": "https://example.com/market"}), encoding="utf-8")
            chunks = chunk_document(
                "filing", "Acme 10-K", "The filing mentions an index in a compensation table.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index_path = root / "index.json"
            index_path.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            response = FinancialAgent(
                index_path=index_path,
                memory_path=root / "memory.json",
                market_path=market_file,
            ).ask("How did the CSI 300 index perform?")

        self.assertEqual(response.citations[0].source_type, "market_data")
        self.assertEqual(response.evidence_count, 1)
        self.assertIn("sh000001 moved from 3300.00", response.answer)

    def test_planning_terms_change_retrieval_and_verifier_rewrites_draft(self) -> None:
        class ScriptedGateway:
            def __init__(self) -> None:
                self.deepseek_calls = 0

            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                if provider == "deepseek":
                    self.deepseek_calls += 1
                    if self.deepseek_calls == 1:
                        return ModelResponse("deepseek", "deepseek-v4-pro", "liquidity debt maturity", True)
                    return ModelResponse("deepseek", "deepseek-v4-pro", "Verifier kept only cited evidence. [S1]", True)
                return ModelResponse("doubao", "doubao-seed-evolving", "Unsupported growth claim without a citation.", True)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks = chunk_document(
                "acme-10k", "Acme 10-K", "Liquidity risk is driven by debt maturities in 2027.",
                "https://www.sec.gov/acme", "2026-02-20", "sec_10k",
            )
            index_path = root / "index.json"
            index_path.write_text(json.dumps([chunk.to_dict() for chunk in chunks]), encoding="utf-8")
            response = FinancialAgent(
                index_path=index_path,
                memory_path=root / "memory.json",
                market_path=root / "missing.csv",
                models=ScriptedGateway(),  # type: ignore[arg-type]
            ).ask("What should I focus on?")

        self.assertEqual(response.evidence_count, 1)
        self.assertEqual(response.answer, "Verifier kept only cited evidence. [S1]")

    def test_cli_returns_friendly_error_instead_of_traceback(self) -> None:
        stderr = io.StringIO()
        with patch("finagent.cli.FinancialAgent.ask", side_effect=ValueError("Question cannot be empty")), redirect_stderr(stderr):
            exit_code = main(["ask", "test"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Error: Question cannot be empty", stderr.getvalue())

    def test_cli_configures_text_streams_for_utf8_when_supported(self) -> None:
        class Stream:
            def __init__(self) -> None:
                self.calls: list[dict[str, str]] = []

            def reconfigure(self, **kwargs: str) -> None:
                self.calls.append(kwargs)

        stdout = Stream()
        stderr = Stream()
        _configure_console_encoding(stdout, stderr)

        self.assertEqual(stdout.calls, [{"encoding": "utf-8", "errors": "replace"}])
        self.assertEqual(stderr.calls, [{"encoding": "utf-8", "errors": "replace"}])

    def test_verify_models_reports_both_required_remote_providers(self) -> None:
        class VerifiedGateway:
            def __init__(self) -> None:
                self.budgets: dict[str, int] = {}

            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                self.budgets[provider] = int(kwargs["max_tokens"])
                model = "doubao-seed-evolving" if provider == "doubao" else "deepseek-v4-pro"
                text = "READY" if provider == "doubao" else "READY."
                return ModelResponse(provider, model, text, True)

        gateway = VerifiedGateway()
        stdout = io.StringIO()
        with patch("finagent.cli.ModelGateway", return_value=gateway), redirect_stdout(stdout):
            exit_code = main(["verify-models"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(gateway.budgets, {"doubao": 16, "deepseek": 600})
        self.assertIn("Verified doubao / doubao-seed-evolving", stdout.getvalue())
        self.assertIn("Verified deepseek / deepseek-v4-pro", stdout.getvalue())

    def test_verify_models_fails_when_a_required_provider_is_offline(self) -> None:
        class PartialGateway:
            def complete(self, provider: str, system: str, user: str, **kwargs: object) -> ModelResponse:
                if provider == "doubao":
                    return ModelResponse("doubao", "doubao-seed-evolving", "READY", True)
                return ModelResponse("offline", "deepseek-v4-pro", "", False, "API key is not configured")

        stderr = io.StringIO()
        with patch("finagent.cli.ModelGateway", return_value=PartialGateway()), redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            exit_code = main(["verify-models"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Model verification failed for deepseek", stderr.getvalue())

    def test_smoke_demo_requires_all_three_remote_model_stages(self) -> None:
        response = AgentResponse(
            answer="A cited finding. [S1]",
            citations=[Citation("[S1]", "Acme 10-K", "https://www.sec.gov/acme", "2026-02-20", "sec_10k", "acme", "chunk 1")],
            preferences=[],
            model_trace=[
                {"stage": "planning", "provider": "deepseek", "model": "deepseek-v4-pro", "used_remote_model": True, "status": "ok"},
                {"stage": "analysis", "provider": "offline", "model": "doubao-seed-evolving", "used_remote_model": False, "status": "timeout"},
                {"stage": "verification", "provider": "deepseek", "model": "deepseek-v4-pro", "used_remote_model": True, "status": "ok"},
            ],
            evidence_count=1,
            warnings=[],
        )
        stderr = io.StringIO()
        with patch("finagent.cli.FinancialAgent.ask", return_value=response), redirect_stderr(stderr):
            exit_code = main(["smoke-demo"])

        self.assertEqual(exit_code, 2)
        self.assertIn("did not complete all required remote stages", stderr.getvalue())

    def test_web_search_unwraps_duckduckgo_redirects(self) -> None:
        self.assertEqual(
            _result_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.sec.gov%2Fexample&amp;rut=abc"),
            "https://www.sec.gov/example",
        )


if __name__ == "__main__":
    unittest.main()
