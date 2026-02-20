"""Tests for litscout.report."""

from pathlib import Path

from litscout.models import Paper
from litscout.report import run_report
from litscout.config import Config
from litscout.utils.io import append_papers


def _make_paper(**kwargs) -> Paper:
    defaults = {"paper_id": "s2:test", "title": "Test Paper"}
    defaults.update(kwargs)
    return Paper(**defaults)


def test_report_empty_corpus(tmp_path: Path):
    config = Config(project_dir=tmp_path)
    result = run_report(config)
    assert "No papers" in result


def test_report_text(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [
        _make_paper(paper_id="s2:1", title="Paper One", year=2023, citation_count=10, venue="Nature"),
        _make_paper(paper_id="s2:2", title="Paper Two", year=2024, citation_count=5, venue="Science"),
    ]
    append_papers(papers, filepath)

    config = Config(project_dir=tmp_path)
    result = run_report(config, fmt="text")
    assert "Total papers: 2" in result
    assert "Nature" in result


def test_report_markdown(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [
        _make_paper(paper_id="s2:1", title="Paper One", year=2023, citation_count=10),
    ]
    append_papers(papers, filepath)

    config = Config(project_dir=tmp_path)
    result = run_report(config, fmt="markdown")
    assert "# LitScout Corpus Report" in result
    assert "**Total papers:** 1" in result


def test_report_json(tmp_path: Path):
    filepath = tmp_path / "papers.jsonl"
    papers = [
        _make_paper(paper_id="s2:1", title="Paper One", year=2023, citation_count=10),
    ]
    append_papers(papers, filepath)

    config = Config(project_dir=tmp_path)
    result = run_report(config, fmt="json")
    import json
    data = json.loads(result)
    assert data["total"] == 1
