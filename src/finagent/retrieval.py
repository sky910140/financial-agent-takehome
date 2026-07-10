from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from finagent.sources import Citation, EvidenceChunk, SearchResult

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)?|[\u4e00-\u9fff]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_RE.findall(text.lower()):
        if "\u4e00" <= match[0] <= "\u9fff":
            tokens.extend(match[index:index + 2] for index in range(len(match) - 1))
            if len(match) == 1:
                tokens.append(match)
        else:
            tokens.append(match)
    return tokens


def chunk_document(
    document_id: str,
    title: str,
    text: str,
    source_url: str,
    published_at: str | None,
    source_type: str,
    *,
    locator: str | None = None,
    chunk_size: int = 1_400,
    overlap: int = 180,
) -> list[EvidenceChunk]:
    """Split source text while retaining every field needed to verify a quote."""
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    chunks: list[EvidenceChunk] = []
    start = 0
    ordinal = 1
    while start < len(clean):
        end = min(start + chunk_size, len(clean))
        if end < len(clean):
            boundary = clean.rfind(". ", start, end)
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        piece = clean[start:end].strip()
        if piece:
            chunks.append(EvidenceChunk(
                chunk_id=f"{document_id}:{ordinal:04d}",
                document_id=document_id,
                title=title,
                text=piece,
                source_url=source_url,
                published_at=published_at,
                source_type=source_type,
                locator=locator,
            ))
            ordinal += 1
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks


class LocalRetriever:
    """Small deterministic BM25 retriever intended for an inspectable take-home."""

    def __init__(self, chunks: Iterable[EvidenceChunk]) -> None:
        self.chunks = list(chunks)
        self._tokens = [tokenize(chunk.text) for chunk in self.chunks]
        self._document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            self._document_frequency.update(set(tokens))
        self._average_length = sum(map(len, self._tokens)) / len(self._tokens) if self._tokens else 0.0

    def search(self, query: str, limit: int = 6) -> list[SearchResult]:
        if not query.strip() or limit < 1:
            return []
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        number_of_documents = len(self.chunks)
        scores: list[tuple[float, int]] = []
        for index, tokens in enumerate(self._tokens):
            counts = Counter(tokens)
            score = 0.0
            for term in set(terms):
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                inverse_document_frequency = math.log(1 + (number_of_documents - self._document_frequency[term] + 0.5) / (self._document_frequency[term] + 0.5))
                length_normalizer = 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(self._average_length, 1))
                score += inverse_document_frequency * frequency * (1.5 + 1) / (frequency + length_normalizer)
            scores.append((score, index))

        ranked = sorted((item for item in scores if item[0] > 0), key=lambda item: (-item[0], item[1]))[:limit]
        return [SearchResult(
            evidence=self.chunks[index].with_score(score),
            citation=Citation(
                label=f"[S{rank + 1}]",
                title=self.chunks[index].title,
                source_url=self.chunks[index].source_url,
                published_at=self.chunks[index].published_at,
                source_type=self.chunks[index].source_type,
                document_id=self.chunks[index].document_id,
                locator=self.chunks[index].locator or self.chunks[index].chunk_id,
            ),
        ) for rank, (score, index) in enumerate(ranked)]


def write_chunks(chunks: Iterable[EvidenceChunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([chunk.to_dict() for chunk in chunks], ensure_ascii=False, indent=2), encoding="utf-8")


def read_chunks(path: Path) -> list[EvidenceChunk]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [EvidenceChunk(**row) for row in rows]
