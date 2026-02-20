"""Ingest module — match manually downloaded PDFs to papers in the registry."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from litscout.config import Config
from litscout.models import FulltextSource, FulltextStatus, Paper, RetrievalLogEntry
from litscout.utils.identifiers import extract_doi_from_string, normalize_doi, sanitize_for_filename
from litscout.utils.io import generate_manual_list, load_papers, update_paper

logger = logging.getLogger(__name__)


def _extract_pdf_title(pdf_path: Path) -> str | None:
    """Extract title from PDF metadata."""
    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
        metadata = doc.metadata
        doc.close()
        title = metadata.get("title", "").strip() if metadata else ""
        return title if title and len(title) > 5 else None
    except Exception:
        return None


def _extract_first_page_text(pdf_path: Path) -> str | None:
    """Extract text from the first page of a PDF."""
    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
        if doc.page_count > 0:
            text = doc[0].get_text().strip()
            doc.close()
            return text if text else None
        doc.close()
    except Exception:
        pass
    return None


def _match_by_filename(filename: str, papers: list[Paper]) -> Paper | None:
    """Try to match a PDF filename to a paper by DOI in the filename."""
    doi = extract_doi_from_string(filename)
    if not doi:
        return None
    for paper in papers:
        if paper.doi and normalize_doi(paper.doi) == doi:
            return paper
    return None


def _match_by_pdf_title(pdf_path: Path, papers: list[Paper]) -> tuple[Paper | None, float]:
    """Try to match via PDF metadata title. Returns (paper, score)."""
    pdf_title = _extract_pdf_title(pdf_path)
    if not pdf_title:
        return None, 0.0

    best_match: Paper | None = None
    best_score = 0.0
    for paper in papers:
        score = fuzz.ratio(pdf_title.lower(), paper.title.lower())
        if score > best_score:
            best_score = score
            best_match = paper

    if best_score > 85:
        return best_match, best_score
    return None, best_score


def _match_by_first_page(pdf_path: Path, papers: list[Paper]) -> tuple[Paper | None, float]:
    """Try to match via first-page text content. Returns (paper, score)."""
    text = _extract_first_page_text(pdf_path)
    if not text:
        return None, 0.0

    text_lower = text.lower()
    best_match: Paper | None = None
    best_score = 0.0

    for paper in papers:
        if paper.title.lower() in text_lower:
            return paper, 100.0
        score = fuzz.partial_ratio(paper.title.lower(), text_lower)
        if score > best_score:
            best_score = score
            best_match = paper

    if best_score > 90:
        return best_match, best_score
    return None, best_score


def run_ingest(
    config: Config,
    *,
    extract: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Scan the inbox for PDFs, match them to papers, and ingest.

    Returns summary with counts: ingested, unmatched, still_pending.
    """
    papers_path = config.project_dir / "papers.jsonl"
    inbox_dir = config.project_dir / Path(config.retrieval.inbox_dir)
    processed_dir = config.project_dir / Path(config.retrieval.processed_dir)
    pdf_dir = config.project_dir / "fulltext" / "pdf"
    log_path = config.project_dir / "retrieval_log.jsonl"

    inbox_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # Find PDFs in inbox
    pdfs = sorted(inbox_dir.glob("*.pdf"))
    if not pdfs:
        logger.info("No PDFs found in inbox")
        return {"ingested": 0, "unmatched": 0, "still_pending": 0}

    logger.info("Scanning inbox: %d PDFs found", len(pdfs))

    # Load papers that need manual retrieval (prioritize these for matching)
    all_papers = load_papers(papers_path)
    manual_papers = [p for p in all_papers if p.needs_manual_retrieval]

    ingested = 0
    unmatched = 0

    for pdf_path in pdfs:
        filename = pdf_path.name
        match: Paper | None = None
        method = ""

        # Strategy 1: filename match
        match = _match_by_filename(filename, all_papers)
        if match:
            method = "filename"

        # Strategy 2: PDF metadata title
        if not match:
            match, score = _match_by_pdf_title(pdf_path, manual_papers or all_papers)
            if match:
                method = f"pdf_metadata (score={score:.0f})"

        # Strategy 3: first-page text
        if not match:
            match, score = _match_by_first_page(pdf_path, manual_papers or all_papers)
            if match:
                method = f"first_page_text (score={score:.0f})"

        if match:
            logger.info("  %s -> matched by %s", filename, method)
            logger.info("    %s (%s)", match.title[:60], match.year)

            if dry_run:
                ingested += 1
                continue

            # Copy to fulltext/pdf/
            identifier = match.doi or match.paper_id.replace(":", "_")
            dest_filename = sanitize_for_filename(identifier) + ".pdf"
            dest_path = pdf_dir / dest_filename
            shutil.copy2(pdf_path, dest_path)

            # Update paper record
            rel_path = str(dest_path.relative_to(config.project_dir))
            update_paper(papers_path, match.paper_id, {
                "fulltext_pdf_path": rel_path,
                "fulltext_status": FulltextStatus.MANUAL_RETRIEVED,
                "fulltext_source": FulltextSource.MANUAL,
                "needs_manual_retrieval": False,
            })

            # Log
            entry = RetrievalLogEntry(
                doi=match.doi,
                paper_id=match.paper_id,
                timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                format_attempted="pdf",
                source_attempted="manual",
                url_attempted=None,
                status="success",
                file_path=rel_path,
                file_size_bytes=dest_path.stat().st_size,
                content_type="application/pdf",
            )
            with open(log_path, "a") as f:
                f.write(entry.model_dump_json() + "\n")

            # Move original to processed
            shutil.move(str(pdf_path), str(processed_dir / filename))
            ingested += 1
        else:
            # Find closest candidate for reporting
            closest_name = ""
            closest_score = 0.0
            for p in manual_papers or all_papers:
                score = fuzz.ratio(filename.lower(), (p.title or "").lower())
                if score > closest_score:
                    closest_score = score
                    closest_name = p.title or ""

            logger.warning("  %s -> no confident match found", filename)
            if closest_name:
                logger.warning("    Closest candidate (score %.0f): %s — skipped",
                               closest_score, closest_name[:60])
            unmatched += 1

    # Regenerate manual retrieval list
    if not dry_run:
        manual_path = config.project_dir / "manual_retrieval_list.md"
        still_pending = generate_manual_list(papers_path, manual_path)
    else:
        still_pending = len(manual_papers) - ingested

    # Run extraction if requested
    if extract and not dry_run and ingested > 0:
        from litscout.extract import run_extract
        run_extract(config, status="manual_retrieved")

    logger.info("Ingest complete: %d ingested, %d unmatched, %d still need manual retrieval",
                ingested, unmatched, still_pending)

    return {"ingested": ingested, "unmatched": unmatched, "still_pending": still_pending}
