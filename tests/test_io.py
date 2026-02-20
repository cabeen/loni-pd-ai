"""Tests for litscout.utils.io."""

from pathlib import Path

from litscout.models import Author, Paper
from litscout.utils.io import append_papers, generate_manual_list, load_papers, update_paper


def _make_paper(**kwargs) -> Paper:
    defaults = {"paper_id": "s2:test", "title": "Test Paper"}
    defaults.update(kwargs)
    return Paper(**defaults)


def test_load_papers_empty(tmp_path: Path):
    papers = load_papers(tmp_path / "nonexistent.jsonl")
    assert papers == []


def test_append_and_load(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [
        _make_paper(paper_id="s2:1", title="Paper 1", doi="10.1234/a"),
        _make_paper(paper_id="s2:2", title="Paper 2", doi="10.1234/b"),
    ]
    count = append_papers(papers, filepath)
    assert count == 2

    loaded = load_papers(filepath)
    assert len(loaded) == 2
    assert loaded[0].paper_id == "s2:1"
    assert loaded[1].paper_id == "s2:2"


def test_append_dedup(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"

    papers1 = [_make_paper(paper_id="s2:1", title="Paper 1", doi="10.1234/a")]
    append_papers(papers1, filepath)

    papers2 = [
        _make_paper(paper_id="s2:1", title="Paper 1", doi="10.1234/a"),  # duplicate
        _make_paper(paper_id="s2:2", title="Paper 2", doi="10.1234/b"),  # new
    ]
    count = append_papers(papers2, filepath)
    assert count == 1

    loaded = load_papers(filepath)
    assert len(loaded) == 2


def test_update_paper(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [_make_paper(paper_id="s2:1", title="Paper 1")]
    append_papers(papers, filepath)

    updated = update_paper(filepath, "s2:1", {"fulltext_status": "retrieved"})
    assert updated is True

    loaded = load_papers(filepath)
    assert loaded[0].fulltext_status == "retrieved"


def test_update_paper_not_found(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [_make_paper(paper_id="s2:1", title="Paper 1")]
    append_papers(papers, filepath)

    updated = update_paper(filepath, "s2:nonexistent", {"title": "x"})
    assert updated is False


def test_load_papers_filter_by_tag(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [
        _make_paper(paper_id="s2:1", title="Paper 1", tags=["seed"]),
        _make_paper(paper_id="s2:2", title="Paper 2", tags=["expand"]),
    ]
    append_papers(papers, filepath)

    seed_papers = load_papers(filepath, tags=["seed"])
    assert len(seed_papers) == 1
    assert seed_papers[0].paper_id == "s2:1"


def test_generate_manual_list(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [
        _make_paper(
            paper_id="s2:1",
            title="Paywalled Paper",
            doi="10.1234/pw",
            needs_manual_retrieval=True,
            authors=[Author(name="Jane Doe")],
            year=2023,
            citation_count=50,
        ),
        _make_paper(paper_id="s2:2", title="Open Paper", needs_manual_retrieval=False),
    ]
    append_papers(papers, filepath)

    output_path = tmp_path / "manual_list.md"
    count = generate_manual_list(filepath, output_path)
    assert count == 1

    content = output_path.read_text()
    assert "Paywalled Paper" in content
    assert "10.1234/pw" in content
    assert "Jane Doe" in content
