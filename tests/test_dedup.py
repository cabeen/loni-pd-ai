"""Tests for litscout.utils.dedup."""

from litscout.models import Paper
from litscout.utils.dedup import DedupIndex, merge_paper_records


def _make_paper(**kwargs) -> Paper:
    defaults = {"paper_id": "s2:test", "title": "Test Paper"}
    defaults.update(kwargs)
    return Paper(**defaults)


def test_dedup_by_doi():
    idx = DedupIndex()
    p1 = _make_paper(paper_id="s2:1", doi="10.1234/test")
    idx.add(p1)

    p2 = _make_paper(paper_id="s2:2", doi="10.1234/test")
    assert idx.is_duplicate(p2)


def test_dedup_by_doi_case_insensitive():
    idx = DedupIndex()
    p1 = _make_paper(paper_id="s2:1", doi="10.1234/TEST")
    idx.add(p1)

    p2 = _make_paper(paper_id="s2:2", doi="10.1234/test")
    assert idx.is_duplicate(p2)


def test_dedup_by_pmid():
    idx = DedupIndex()
    p1 = _make_paper(paper_id="s2:1", pmid="12345")
    idx.add(p1)

    p2 = _make_paper(paper_id="s2:2", pmid="12345")
    assert idx.is_duplicate(p2)


def test_dedup_by_paper_id():
    idx = DedupIndex()
    p1 = _make_paper(paper_id="s2:same_id")
    idx.add(p1)

    p2 = _make_paper(paper_id="s2:same_id", title="Different Title")
    assert idx.is_duplicate(p2)


def test_dedup_by_fuzzy_title():
    idx = DedupIndex()
    p1 = _make_paper(paper_id="s2:1", title="Alpha-synuclein aggregation in PD", year=2023)
    idx.add(p1)

    p2 = _make_paper(paper_id="s2:2", title="Alpha-synuclein aggregation in PD.", year=2023)
    assert idx.is_duplicate(p2)


def test_dedup_different_papers():
    idx = DedupIndex()
    p1 = _make_paper(paper_id="s2:1", title="Paper about cats", year=2023)
    idx.add(p1)

    p2 = _make_paper(paper_id="s2:2", title="Paper about dogs", year=2023)
    assert not idx.is_duplicate(p2)


def test_dedup_same_title_different_year():
    idx = DedupIndex()
    p1 = _make_paper(paper_id="s2:1", title="Annual Review of Something", year=2022)
    idx.add(p1)

    p2 = _make_paper(paper_id="s2:2", title="Annual Review of Something", year=2023)
    # Same title but different year — should NOT be duplicate (could be different editions)
    assert not idx.is_duplicate(p2)


def test_merge_paper_records():
    existing = _make_paper(paper_id="s2:1", doi="10.1234/test", pmid=None, year=2023)
    new = _make_paper(paper_id="s2:2", doi="10.1234/test", pmid="12345", year=2022)

    merged = merge_paper_records(existing, new)
    assert merged.paper_id == "s2:1"  # keep existing paper_id
    assert merged.doi == "10.1234/test"
    assert merged.pmid == "12345"  # filled from new
    assert merged.year == 2023  # keep existing non-null
