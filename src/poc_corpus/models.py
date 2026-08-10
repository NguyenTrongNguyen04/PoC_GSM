from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


MATERIALIZER_VERSION = "0.2.0"
PARSER_CONTRACT_VERSION = "0.2.0"


class ExtractionStrategy(StrEnum):
    DOM_SEMANTIC = "dom_semantic"
    LINE_FALLBACK = "line_fallback"


class RetrievalRole(StrEnum):
    STANDALONE = "standalone"
    PARENT_CONTEXT = "parent_context"
    RETRIEVABLE_CHILD = "retrievable_child"


class EvidenceKind(StrEnum):
    CORPUS = "CORPUS"
    TICKET_FIXTURE = "TICKET_FIXTURE"
    MEMORY_FIXTURE = "MEMORY_FIXTURE"
    POLICY_RULE = "POLICY_RULE"
    NEGATIVE_CONSTRAINT = "NEGATIVE_CONSTRAINT"


class EvidenceStatus(StrEnum):
    CANDIDATE = "candidate"
    CANDIDATE_LIVE = "candidate_live"
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_LIVE_REVIEW = "pending_live_review"


class ReviewStatus(StrEnum):
    PENDING_RESEARCH_REVIEW = "pending_research_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class EvidenceSpan(BaseModel):
    quote: str
    start_codepoint: int
    end_codepoint: int


class StructuredEvidenceRef(BaseModel):
    """Non-corpus evidence pointer for POLICY / TICKET / MEMORY / NEGATIVE facts."""

    ref_type: str
    ref_id: str
    path: str | None = None
    notes: str = ""


class SnapshotDocument(BaseModel):
    schema_version: str = "0.2.0"
    source_id: str
    title: str
    canonical_url: str
    requested_url: str
    final_url: str
    content_selector: str
    language: str = "vi"
    publisher: str = "Green SM"
    fetched_at: str
    http_status: int
    content_type: str
    raw_sha256: str
    content_sha256: str
    extraction_strategy: ExtractionStrategy
    source_last_modified: str | None = None
    parser_version: str
    normalizer_version: str
    materializer_version: str
    materialization_mode: str
    materialization_payload_sha256: str
    content_kind: str = "text"
    ocr_status: str | None = None
    text_retrieval_eligible: bool = True
    asset_urls: list[str] = Field(default_factory=list)
    normalized_text: str
    char_count: int
    topic_tags: list[str] = Field(default_factory=list)
    priority: str = "medium"
    retrieval_role: RetrievalRole = RetrievalRole.STANDALONE
    parent_source_id: str | None = None
    faq_range: list[str] | None = None


class CatalogReview(BaseModel):
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING_RESEARCH_REVIEW
    reviewed_snapshot_sha256: str | None = None


class FactEntry(BaseModel):
    fact_id: str
    evidence_kind: EvidenceKind
    evidence_status: EvidenceStatus = EvidenceStatus.PENDING_LIVE_REVIEW
    source_id: str | None
    claim_type: str = ""
    description: str = ""
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    structured_evidence_refs: list[StructuredEvidenceRef] = Field(default_factory=list)
    source_content_sha256: str | None = None
    notes: str = ""


class ManifestRow(BaseModel):
    source_id: str
    title: str
    canonical_url: str
    content_selector: str
    topic_tags: str = ""
    priority: str = "medium"
    language: str = "vi"
    publisher: str = "Green SM"
    selection_status: str = "selected"
    snapshot_status: str = "pending"
    fetched_at: str = ""
    sha256: str = ""
    notes: str = ""

    @classmethod
    def from_csv_row(cls, row: dict[str, Any]) -> ManifestRow:
        return cls(**{k: (row.get(k) or "") for k in cls.model_fields})
