"""Text extraction module — convert PDFs and XMLs into clean LLM-ready text."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tqdm import tqdm

from litscout.config import Config
from litscout.models import FulltextStatus, Paper
from litscout.utils.identifiers import sanitize_for_filename
from litscout.utils.io import load_papers, update_paper

logger = logging.getLogger(__name__)


def _extract_from_bioc_json(json_path: Path) -> dict[str, str]:
    """Extract sections from a BioC JSON file.

    Returns a dict mapping section names to text content.
    """
    sections: dict[str, str] = {}
    try:
        data = json.loads(json_path.read_text())
        documents = data if isinstance(data, list) else data.get("documents", [data])
        for doc in documents:
            for passage in doc.get("passages", []):
                infons = passage.get("infons", {})
                section_type = (
                    infons.get("section_type", "")
                    or infons.get("type", "")
                    or "body"
                ).lower()
                text = passage.get("text", "")
                if text:
                    if section_type in sections:
                        sections[section_type] += "\n" + text
                    else:
                        sections[section_type] = text
    except Exception:
        logger.exception("Failed to parse BioC JSON: %s", json_path)
    return sections


def _extract_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF using pymupdf4llm."""
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(str(pdf_path))
    except Exception:
        logger.exception("Failed to extract text from PDF: %s", pdf_path)
        return ""


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4


def _truncate_to_tokens(
    sections: dict[str, str],
    max_tokens: int,
    priority: list[str],
) -> tuple[dict[str, str], int, int]:
    """Truncate sections to fit within max_tokens, keeping priority sections.

    Returns (truncated_sections, total_tokens, shown_tokens).
    """
    total_tokens = sum(_estimate_tokens(v) for v in sections.values())
    if total_tokens <= max_tokens:
        return sections, total_tokens, total_tokens

    # Keep priority sections first
    result: dict[str, str] = {}
    used_tokens = 0

    # Add sections in priority order
    for sec_name in priority:
        for key, text in sections.items():
            if sec_name in key.lower() and key not in result:
                tokens = _estimate_tokens(text)
                if used_tokens + tokens <= max_tokens:
                    result[key] = text
                    used_tokens += tokens
                else:
                    # Truncate this section to fit
                    remaining = max_tokens - used_tokens
                    if remaining > 100:
                        char_limit = remaining * 4
                        result[key] = text[:char_limit] + "\n[TRUNCATED]"
                        used_tokens += remaining
                break

    # Add any remaining sections that fit
    for key, text in sections.items():
        if key not in result:
            tokens = _estimate_tokens(text)
            if used_tokens + tokens <= max_tokens:
                result[key] = text
                used_tokens += tokens

    return result, total_tokens, used_tokens


def _format_output(
    paper: Paper,
    sections: dict[str, str],
    total_tokens: int | None = None,
    shown_tokens: int | None = None,
) -> str:
    """Format extracted text into the LitScout output format."""
    lines: list[str] = []

    # Header
    lines.append(f"TITLE: {paper.title}")
    if paper.authors:
        names = ", ".join(a.name for a in paper.authors)
        lines.append(f"AUTHORS: {names}")
    if paper.year:
        lines.append(f"YEAR: {paper.year}")
    if paper.doi:
        lines.append(f"DOI: {paper.doi}")
    if paper.journal_name or paper.venue:
        lines.append(f"SOURCE: {paper.journal_name or paper.venue}")
    lines.append("")

    if total_tokens and shown_tokens and total_tokens > shown_tokens:
        lines.append(
            f"[TRUNCATED: full text is ~{total_tokens} tokens, "
            f"showing ~{shown_tokens} tokens from priority sections]"
        )
        lines.append("")

    # Section order preference
    section_order = [
        "abstract", "introduction", "background", "methods", "materials",
        "results", "discussion", "conclusion", "conclusions",
        "acknowledgments", "references",
    ]

    # Output sections in preferred order
    output_keys: list[str] = []
    for pref in section_order:
        for key in sections:
            if pref in key.lower() and key not in output_keys:
                output_keys.append(key)

    # Add any remaining sections
    for key in sections:
        if key not in output_keys:
            output_keys.append(key)

    for key in output_keys:
        label = key.upper().replace("_", " ")
        lines.append(f"--- {label} ---")
        lines.append(sections[key])
        lines.append("")

    return "\n".join(lines)


def _extract_one(
    paper: Paper,
    config: Config,
    txt_dir: Path,
    max_tokens: int,
) -> bool:
    """Extract text from one paper. Returns True on success."""
    project_dir = config.project_dir
    priority = config.extraction.priority_sections

    sections: dict[str, str] = {}

    # Prefer structured text (BioC JSON/XML) over PDF
    if paper.fulltext_xml_path:
        xml_path = project_dir / paper.fulltext_xml_path
        if xml_path.exists():
            sections = _extract_from_bioc_json(xml_path)

    if not sections and paper.fulltext_pdf_path:
        pdf_path = project_dir / paper.fulltext_pdf_path
        if pdf_path.exists():
            raw_text = _extract_from_pdf(pdf_path)
            if raw_text:
                sections = {"body": raw_text}

    if not sections:
        return False

    # Truncate if needed
    sections, total_tokens, shown_tokens = _truncate_to_tokens(sections, max_tokens, priority)

    # Format output
    output = _format_output(paper, sections, total_tokens, shown_tokens)

    # Write to file
    identifier = paper.doi or paper.paper_id.replace(":", "_")
    filename = sanitize_for_filename(identifier) + ".txt"
    dest = txt_dir / filename
    dest.write_text(output)

    return True


def run_extract(
    config: Config,
    *,
    doi: str | None = None,
    status: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, int]:
    """Run text extraction for papers with retrieved full text.

    Returns summary: extracted, skipped, errors.
    """
    papers_path = config.project_dir / "papers.jsonl"
    txt_dir = config.project_dir / "fulltext" / "txt"
    txt_dir.mkdir(parents=True, exist_ok=True)

    effective_max_tokens = max_tokens or config.extraction.max_tokens_per_doc

    all_papers = load_papers(papers_path)
    to_extract: list[Paper] = []

    for paper in all_papers:
        # Filter by DOI if specified
        if doi and paper.doi != doi:
            continue

        # Filter by status if specified
        if status and paper.fulltext_status != status:
            continue

        # Skip papers that already have extracted text (unless doi is explicit)
        if not doi and paper.fulltext_txt_path:
            continue

        # Must have some full text available
        if not paper.fulltext_pdf_path and not paper.fulltext_xml_path:
            continue

        to_extract.append(paper)

    extracted = 0
    skipped = 0
    errors = 0

    for paper in tqdm(to_extract, desc="Extracting text"):
        try:
            success = _extract_one(paper, config, txt_dir, effective_max_tokens)
            if success:
                identifier = paper.doi or paper.paper_id.replace(":", "_")
                filename = sanitize_for_filename(identifier) + ".txt"
                rel_path = f"fulltext/txt/{filename}"
                update_paper(papers_path, paper.paper_id, {"fulltext_txt_path": rel_path})
                extracted += 1
            else:
                skipped += 1
        except Exception:
            logger.exception("Extraction failed for %s", paper.paper_id)
            errors += 1

    logger.info("Extraction complete: %d extracted, %d skipped, %d errors",
                extracted, skipped, errors)
    return {"extracted": extracted, "skipped": skipped, "errors": errors}
