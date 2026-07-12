from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Citation:
    label: str
    title: str
    source_url: str
    published_at: str | None
    source_type: str
    document_id: str
    locator: str | None = None
    chunk_id: str | None = None
    evidence_sha256: str | None = None
    excerpt: str | None = None
    retrieval_score: float | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    document_id: str
    title: str
    text: str
    source_url: str
    published_at: str | None
    source_type: str
    locator: str | None = None
    score: float = 0.0

    def with_score(self, score: float) -> "EvidenceChunk":
        return EvidenceChunk(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            title=self.title,
            text=self.text,
            source_url=self.source_url,
            published_at=self.published_at,
            source_type=self.source_type,
            locator=self.locator,
            score=score,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    evidence: EvidenceChunk
    citation: Citation
