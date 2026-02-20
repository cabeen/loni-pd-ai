"""Tests for litscout.models."""

from litscout.models import (
    Author,
    DiscoveryMethod,
    FulltextSource,
    FulltextStatus,
    Paper,
    RetrievalLogEntry,
    SearchLog,
)


def test_paper_defaults():
    p = Paper(paper_id="s2:abc", title="Test Paper")
    assert p.paper_id == "s2:abc"
    assert p.title == "Test Paper"
    assert p.doi is None
    assert p.authors == []
    assert p.fulltext_status == FulltextStatus.NOT_ATTEMPTED
    assert p.discovery_method == DiscoveryMethod.KEYWORD_SEARCH
    assert p.tags == []
    assert p.needs_manual_retrieval is False


def test_paper_roundtrip():
    p = Paper(
        paper_id="s2:abc",
        title="Test Paper",
        doi="10.1234/test",
        authors=[Author(name="Jane Doe", author_id="s2:123")],
        year=2023,
        tags=["seed"],
    )
    json_str = p.model_dump_json()
    p2 = Paper.model_validate_json(json_str)
    assert p2.paper_id == p.paper_id
    assert p2.doi == p.doi
    assert p2.authors[0].name == "Jane Doe"
    assert p2.tags == ["seed"]


def test_enums():
    assert DiscoveryMethod.KEYWORD_SEARCH == "keyword_search"
    assert FulltextStatus.RETRIEVED == "retrieved"
    assert FulltextSource.UNPAYWALL == "unpaywall"


def test_search_log():
    log = SearchLog(
        timestamp="2025-01-01T00:00:00Z",
        query="test",
        sources=["semantic_scholar"],
        total_results=10,
        new_papers_added=5,
        duplicates_skipped=5,
    )
    assert log.total_results == 10


def test_retrieval_log_entry():
    entry = RetrievalLogEntry(
        paper_id="s2:abc",
        timestamp="2025-01-01T00:00:00Z",
        format_attempted="pdf",
        source_attempted="unpaywall",
        status="success",
    )
    assert entry.status == "success"
