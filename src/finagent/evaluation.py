from __future__ import annotations

import json
from pathlib import Path

from finagent.agent import FinancialAgent
from finagent.models import ModelResponse
from finagent.retrieval import LocalRetriever, read_chunks


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
