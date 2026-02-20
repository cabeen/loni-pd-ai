"""Report module — corpus summary statistics and analysis."""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from litscout.config import Config
from litscout.models import Paper
from litscout.utils.io import load_papers

logger = logging.getLogger(__name__)


def _year_histogram(papers: list[Paper], width: int = 40) -> str:
    """Generate a text-based year distribution histogram."""
    years = [p.year for p in papers if p.year]
    if not years:
        return "  No year data available"

    counter = Counter(years)
    min_year = min(counter)
    max_year = max(counter)
    max_count = max(counter.values())

    lines: list[str] = []
    for year in range(min_year, max_year + 1):
        count = counter.get(year, 0)
        bar_len = int(count / max_count * width) if max_count > 0 else 0
        bar = "#" * bar_len
        lines.append(f"  {year} | {bar} ({count})")
    return "\n".join(lines)


def _build_stats(papers: list[Paper]) -> dict[str, Any]:
    """Build comprehensive corpus statistics."""
    total = len(papers)

    # Discovery method breakdown
    method_counts = Counter(p.discovery_method for p in papers)

    # Fulltext status breakdown
    status_counts = Counter(p.fulltext_status for p in papers)

    # Papers with extracted text
    has_txt = sum(1 for p in papers if p.fulltext_txt_path)
    has_pdf = sum(1 for p in papers if p.fulltext_pdf_path)
    has_xml = sum(1 for p in papers if p.fulltext_xml_path)
    needs_manual = sum(1 for p in papers if p.needs_manual_retrieval)

    # Fulltext source breakdown
    source_counts = Counter(p.fulltext_source for p in papers if p.fulltext_source)

    # Top venues
    venue_counts = Counter(p.venue or p.journal_name for p in papers if p.venue or p.journal_name)
    top_venues = venue_counts.most_common(10)

    # Tag distribution
    tag_counts: Counter[str] = Counter()
    for p in papers:
        for tag in p.tags:
            tag_counts[tag] += 1

    # Top cited papers
    cited_papers = sorted(
        [p for p in papers if p.citation_count is not None],
        key=lambda p: p.citation_count or 0,
        reverse=True,
    )

    # Most recent papers
    recent_papers = sorted(
        [p for p in papers if p.year],
        key=lambda p: (p.year or 0, p.citation_count or 0),
        reverse=True,
    )

    # Citation stats
    citations = [p.citation_count for p in papers if p.citation_count is not None]
    avg_citations = sum(citations) / len(citations) if citations else 0

    return {
        "total": total,
        "method_counts": dict(method_counts),
        "status_counts": dict(status_counts),
        "has_txt": has_txt,
        "has_pdf": has_pdf,
        "has_xml": has_xml,
        "needs_manual": needs_manual,
        "source_counts": dict(source_counts),
        "top_venues": top_venues,
        "tag_counts": dict(tag_counts),
        "top_cited": cited_papers[:20],
        "most_recent": recent_papers[:20],
        "avg_citations": avg_citations,
    }


def _format_text(stats: dict[str, Any], papers: list[Paper]) -> str:
    """Format stats as plain text."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("  LitScout Corpus Report")
    lines.append("=" * 60)
    lines.append("")

    # Overview
    lines.append(f"Total papers: {stats['total']}")
    lines.append("")

    # Discovery methods
    lines.append("Discovery methods:")
    for method, count in sorted(stats["method_counts"].items()):
        lines.append(f"  {method}: {count}")
    lines.append("")

    # Retrieval status
    lines.append("Retrieval status:")
    for status, count in sorted(stats["status_counts"].items()):
        lines.append(f"  {status}: {count}")
    lines.append("")
    lines.append(f"  Papers with PDF: {stats['has_pdf']}")
    lines.append(f"  Papers with XML: {stats['has_xml']}")
    lines.append(f"  Papers with extracted text: {stats['has_txt']}")
    lines.append(f"  Awaiting manual retrieval: {stats['needs_manual']}")
    lines.append("")

    if stats["source_counts"]:
        lines.append("Fulltext sources:")
        for source, count in sorted(stats["source_counts"].items()):
            lines.append(f"  {source}: {count}")
        lines.append("")

    # Year distribution
    lines.append("Year distribution:")
    lines.append(_year_histogram(papers))
    lines.append("")

    # Top venues
    if stats["top_venues"]:
        lines.append("Top venues:")
        for venue, count in stats["top_venues"]:
            lines.append(f"  {venue}: {count}")
        lines.append("")

    # Citation stats
    lines.append(f"Average citations per paper: {stats['avg_citations']:.1f}")
    lines.append("")

    # Top cited
    if stats["top_cited"]:
        lines.append("Top cited papers:")
        for i, p in enumerate(stats["top_cited"][:10], 1):
            lines.append(f"  {i}. [{p.citation_count}] {p.title[:70]} ({p.year})")
        lines.append("")

    # Most recent
    if stats["most_recent"]:
        lines.append("Most recent papers:")
        for i, p in enumerate(stats["most_recent"][:10], 1):
            lines.append(f"  {i}. [{p.year}] {p.title[:70]}")
        lines.append("")

    # Tags
    if stats["tag_counts"]:
        lines.append("Tags:")
        for tag, count in sorted(stats["tag_counts"].items()):
            lines.append(f"  {tag}: {count}")
        lines.append("")

    return "\n".join(lines)


def _format_markdown(stats: dict[str, Any], papers: list[Paper]) -> str:
    """Format stats as markdown."""
    lines: list[str] = []

    lines.append("# LitScout Corpus Report")
    lines.append("")
    lines.append(f"**Total papers:** {stats['total']}")
    lines.append("")

    lines.append("## Discovery Methods")
    lines.append("")
    lines.append("| Method | Count |")
    lines.append("|--------|-------|")
    for method, count in sorted(stats["method_counts"].items()):
        lines.append(f"| {method} | {count} |")
    lines.append("")

    lines.append("## Retrieval Status")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    for status, count in sorted(stats["status_counts"].items()):
        lines.append(f"| {status} | {count} |")
    lines.append("")
    lines.append(f"- Papers with PDF: {stats['has_pdf']}")
    lines.append(f"- Papers with XML: {stats['has_xml']}")
    lines.append(f"- Papers with extracted text: {stats['has_txt']}")
    lines.append(f"- Awaiting manual retrieval: {stats['needs_manual']}")
    lines.append("")

    lines.append("## Year Distribution")
    lines.append("")
    lines.append("```")
    lines.append(_year_histogram(papers))
    lines.append("```")
    lines.append("")

    if stats["top_venues"]:
        lines.append("## Top Venues")
        lines.append("")
        lines.append("| Venue | Count |")
        lines.append("|-------|-------|")
        for venue, count in stats["top_venues"]:
            lines.append(f"| {venue} | {count} |")
        lines.append("")

    lines.append(f"**Average citations per paper:** {stats['avg_citations']:.1f}")
    lines.append("")

    if stats["top_cited"]:
        lines.append("## Top Cited Papers")
        lines.append("")
        for i, p in enumerate(stats["top_cited"][:20], 1):
            doi_link = f" ([DOI](https://doi.org/{p.doi}))" if p.doi else ""
            lines.append(f"{i}. **[{p.citation_count} citations]** {p.title} ({p.year}){doi_link}")
        lines.append("")

    return "\n".join(lines)


def run_report(config: Config, *, fmt: str = "text") -> str:
    """Generate a corpus summary report.

    Returns the report as a string.
    """
    papers_path = config.project_dir / "papers.jsonl"
    papers = load_papers(papers_path)

    if not papers:
        return "No papers in corpus. Run `litscout search` to add papers."

    stats = _build_stats(papers)

    if fmt == "json":
        # Serialize non-Paper fields
        json_stats = {k: v for k, v in stats.items() if k not in ("top_cited", "most_recent")}
        json_stats["top_cited"] = [
            {"title": p.title, "year": p.year, "doi": p.doi, "citations": p.citation_count}
            for p in stats["top_cited"][:20]
        ]
        json_stats["most_recent"] = [
            {"title": p.title, "year": p.year, "doi": p.doi}
            for p in stats["most_recent"][:20]
        ]
        return json.dumps(json_stats, indent=2)
    elif fmt == "markdown":
        return _format_markdown(stats, papers)
    else:
        return _format_text(stats, papers)
