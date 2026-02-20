"""I/O utilities for reading/writing JSONL paper registries and related files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from litscout.models import Paper
from litscout.utils.dedup import DedupIndex


def load_papers(filepath: Path, **filters: Any) -> list[Paper]:
    """Load papers from a JSONL file with optional filtering.

    Supported filters:
      - tags: list[str] — paper must have at least one of these tags
      - status: str — match fulltext_status
      - discovery_method: str — match discovery_method
      - needs_manual_retrieval: bool
    """
    if not filepath.exists():
        return []

    papers: list[Paper] = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            paper = Paper.model_validate_json(line)

            # Apply filters
            if "tags" in filters and filters["tags"]:
                if not set(filters["tags"]) & set(paper.tags):
                    continue
            if "status" in filters and paper.fulltext_status != filters["status"]:
                continue
            if "discovery_method" in filters and paper.discovery_method != filters["discovery_method"]:
                continue
            if "needs_manual_retrieval" in filters:
                if paper.needs_manual_retrieval != filters["needs_manual_retrieval"]:
                    continue

            papers.append(paper)

    return papers


def append_papers(papers: list[Paper], filepath: Path) -> int:
    """Append papers to a JSONL file, skipping duplicates against existing content.

    Returns the number of new papers actually written.
    """
    # Build dedup index from existing papers
    index = DedupIndex()
    existing = load_papers(filepath)
    for p in existing:
        index.add(p)

    new_count = 0
    with open(filepath, "a") as f:
        for paper in papers:
            if index.is_duplicate(paper):
                continue
            f.write(paper.model_dump_json() + "\n")
            index.add(paper)
            new_count += 1

    return new_count


def update_paper(filepath: Path, paper_id: str, updates: dict[str, Any]) -> bool:
    """Update specific fields of a paper in-place within a JSONL file.

    Returns True if the paper was found and updated.
    """
    if not filepath.exists():
        return False

    lines: list[str] = []
    found = False
    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if data.get("paper_id") == paper_id:
                data.update(updates)
                found = True
            lines.append(json.dumps(data))

    if found:
        with open(filepath, "w") as f:
            for line in lines:
                f.write(line + "\n")

    return found


def generate_manual_list(papers_filepath: Path, output_filepath: Path) -> int:
    """Generate a markdown file listing papers that need manual retrieval.

    Returns the number of papers in the list.
    """
    from datetime import datetime, timezone

    papers = load_papers(papers_filepath, needs_manual_retrieval=True)
    if not papers:
        # Write an empty list
        output_filepath.write_text(
            "# Papers Needing Manual Retrieval\n\nNo papers currently need manual retrieval.\n"
        )
        return 0

    # Sort: seed papers first, then by citation count descending
    def sort_key(p: Paper) -> tuple[int, int]:
        is_seed = 1 if "seed" in p.tags else 0
        return (-is_seed, -(p.citation_count or 0))

    papers.sort(key=sort_key)

    lines = [
        "# Papers Needing Manual Retrieval",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"Total: {len(papers)} papers",
        "",
        "## How to add papers",
        "",
        "1. Download the PDF from the link below (use institutional access, interlibrary loan, etc.)",
        "2. Name the file using the filename shown below (or any name — the ingest tool will match by content)",
        "3. Drop it into: `fulltext/inbox/`",
        "4. Run: `python -m litscout ingest`",
        "",
        "---",
        "",
    ]

    from litscout.utils.identifiers import sanitize_for_filename

    for i, paper in enumerate(papers, 1):
        authors_str = ", ".join(a.name for a in paper.authors[:3])
        if len(paper.authors) > 3:
            authors_str += ", et al."

        lines.append(f"### {i}. {paper.title} ({paper.year or 'n.d.'})")
        if authors_str:
            lines.append(f"- **Authors:** {authors_str}")
        if paper.venue:
            lines.append(f"- **Venue:** {paper.venue}")
        if paper.doi:
            lines.append(f"- **DOI:** {paper.doi}")
            lines.append(f"- **Publisher link:** https://doi.org/{paper.doi}")
        if paper.citation_count is not None:
            lines.append(f"- **Citations:** {paper.citation_count}")
        if paper.discovery_method and paper.discovery_query:
            lines.append(f"- **Why it matters:** Discovered via {paper.discovery_method}")
        if paper.doi:
            fn = sanitize_for_filename(paper.doi) + ".pdf"
            lines.append(f"- **Suggested filename:** `{fn}`")
        lines.append("")

    output_filepath.write_text("\n".join(lines))
    return len(papers)
