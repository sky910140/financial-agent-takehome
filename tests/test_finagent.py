from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from finagent.agent import FinancialAgent, render_markdown
from finagent.cli import _configure_console_encoding, main
from finagent.ingest import build_filing_index, html_to_text, is_xbrl_noise
from finagent.market import download_major_indices, market_snapshot
from finagent.memory import PreferenceStore
from finagent.models import ModelGateway, ModelResponse
from finagent.retrieval import LocalRetriever, chunk_document, tokenize
from finagent.sec import download_sec_10k, validate_sec_user_agent
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
        with patch("finagent.models.urlopen", side_effect=HTTPError("https://example.com", 404, "Not Found", None, None)):
            result = ModelGateway(doubao_api_key="test-key", deepseek_api_key=None).complete("doubao", "system", "user")

        self.assertFalse(result.used_remote_model)
        self.assertEqual(result.error, "HTTP 404: remote request unavailable")

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
            result = ModelGateway(doubao_api_key="test-key", deepseek_api_key=None).complete("doubao", "system", "user")

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(result.used_remote_model)
        self.assertEqual(payload["max_tokens"], 600)

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

            def complete(self, provider: str, system: str, user: str) -> ModelResponse:
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
            def complete(self, provider: str, system: str, user: str) -> ModelResponse:
                model = "doubao-seed-evolving" if provider == "doubao" else "deepseek-v4-pro"
                return ModelResponse(provider, model, "READY", True)

        stdout = io.StringIO()
        with patch("finagent.cli.ModelGateway", return_value=VerifiedGateway()), redirect_stdout(stdout):
            exit_code = main(["verify-models"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Verified doubao / doubao-seed-evolving", stdout.getvalue())
        self.assertIn("Verified deepseek / deepseek-v4-pro", stdout.getvalue())

    def test_verify_models_fails_when_a_required_provider_is_offline(self) -> None:
        class PartialGateway:
            def complete(self, provider: str, system: str, user: str) -> ModelResponse:
                if provider == "doubao":
                    return ModelResponse("doubao", "doubao-seed-evolving", "READY", True)
                return ModelResponse("offline", "deepseek-v4-pro", "", False, "API key is not configured")

        stderr = io.StringIO()
        with patch("finagent.cli.ModelGateway", return_value=PartialGateway()), redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            exit_code = main(["verify-models"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Model verification failed for deepseek", stderr.getvalue())

    def test_web_search_unwraps_duckduckgo_redirects(self) -> None:
        self.assertEqual(
            _result_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.sec.gov%2Fexample&amp;rut=abc"),
            "https://www.sec.gov/example",
        )


if __name__ == "__main__":
    unittest.main()
