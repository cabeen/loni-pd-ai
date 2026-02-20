"""Data models for LitScout — the canonical paper schema and related types."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DiscoveryMethod(StrEnum):
    KEYWORD_SEARCH = "keyword_search"
    CITATION_FORWARD = "citation_forward"
    CITATION_BACKWARD = "citation_backward"
    RECOMMENDATION = "recommendation"
    MANUAL = "manual"


class FulltextStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    RETRIEVED = "retrieved"
    PARTIAL = "partial"
    FAILED = "failed"
    MANUAL_PENDING = "manual_pending"
    MANUAL_RETRIEVED = "manual_retrieved"


class FulltextSource(StrEnum):
    SEMANTIC_SCHOLAR = "semantic_scholar"
    UNPAYWALL = "unpaywall"
    PMC_BIOC = "pmc_bioc"
    BIORXIV = "biorxiv"
    PUBLISHER_OA = "publisher_oa"
    MANUAL = "manual"


class Author(BaseModel):
    name: str
    author_id: str | None = None


class Paper(BaseModel):
    paper_id: str
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = None

    title: str
    authors: list[Author] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    journal_name: str | None = None
    citation_count: int | None = None
    influential_citation_count: int | None = None
    abstract: str | None = None
    tldr: str | None = None
    fields_of_study: list[str] = Field(default_factory=list)

    is_open_access: bool | None = None
    open_access_pdf_url: str | None = None

    source: str | None = None
    discovery_method: DiscoveryMethod = DiscoveryMethod.KEYWORD_SEARCH
    discovery_query: str | None = None
    discovery_date: str | None = None
    seed_paper_id: str | None = None

    fulltext_status: FulltextStatus = FulltextStatus.NOT_ATTEMPTED
    fulltext_pdf_path: str | None = None
    fulltext_xml_path: str | None = None
    fulltext_txt_path: str | None = None
    fulltext_source: FulltextSource | None = None
    needs_manual_retrieval: bool = False

    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class SearchLog(BaseModel):
    timestamp: str
    query: str
    sources: list[str]
    year_range: list[int] | None = None
    min_citation_count: int = 0
    max_results: int = 100
    fields_of_study: list[str] | None = None
    total_results: int = 0
    new_papers_added: int = 0
    duplicates_skipped: int = 0


class RetrievalLogEntry(BaseModel):
    doi: str | None = None
    paper_id: str
    timestamp: str
    format_attempted: str
    source_attempted: str
    url_attempted: str | None = None
    status: str  # "success", "failed", "failed_paywall"
    file_path: str | None = None
    file_size_bytes: int | None = None
    content_type: str | None = None
    error: str | None = None
