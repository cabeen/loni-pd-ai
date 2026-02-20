"""Full-text retrieval module — fallback chain for PDFs and structured text."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from tqdm import tqdm

from litscout.config import Config
from litscout.models import FulltextSource, FulltextStatus, Paper, RetrievalLogEntry
from litscout.utils.identifiers import sanitize_for_filename
from litscout.utils.io import generate_manual_list, load_papers, update_paper

logger = logging.getLogger(__name__)

_USER_AGENT = "LitScout/0.1 (scientific literature retrieval tool)"


def _download_pdf(url: str, dest: Path) -> tuple[bool, str]:
    """Download a PDF from *url* to *dest*. Returns (success, error_or_content_type)."""
    try:
        with httpx.stream(
            "GET", url,
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": _USER_AGENT},
        ) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            # Check for HTML paywall
            if "text/html" in content_type:
                return False, "failed_paywall"

            # Stream to file
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    f.write(chunk)

        # Verify PDF magic bytes
        with open(dest, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            dest.unlink(missing_ok=True)
            return False, "not_pdf"

        return True, content_type
    except Exception as e:
        dest.unlink(missing_ok=True)
        return False, str(e)


def _log_retrieval(
    log_path: Path,
    paper: Paper,
    format_attempted: str,
    source_attempted: str,
    url_attempted: str | None,
    status: str,
    file_path: str | None = None,
    file_size: int | None = None,
    content_type: str | None = None,
    error: str | None = None,
) -> None:
    entry = RetrievalLogEntry(
        doi=paper.doi,
        paper_id=paper.paper_id,
        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
        format_attempted=format_attempted,
        source_attempted=source_attempted,
        url_attempted=url_attempted,
        status=status,
        file_path=file_path,
        file_size_bytes=file_size,
        content_type=content_type,
        error=error,
    )
    with open(log_path, "a") as f:
        f.write(entry.model_dump_json() + "\n")


def _try_pdf_retrieval(
    paper: Paper,
    config: Config,
    pdf_dir: Path,
    log_path: Path,
) -> str | None:
    """Try to retrieve a PDF through the fallback chain. Returns the path on success."""
    identifier = paper.doi or paper.paper_id.replace(":", "_")
    filename = sanitize_for_filename(identifier) + ".pdf"
    dest = pdf_dir / filename

    # 1. Semantic Scholar OA PDF
    if paper.open_access_pdf_url:
        ok, info = _download_pdf(paper.open_access_pdf_url, dest)
        _log_retrieval(log_path, paper, "pdf", "semantic_scholar",
                       paper.open_access_pdf_url,
                       "success" if ok else "failed",
                       file_path=str(dest.relative_to(config.project_dir)) if ok else None,
                       file_size=dest.stat().st_size if ok and dest.exists() else None,
                       content_type=info if ok else None,
                       error=None if ok else info)
        if ok:
            return str(dest.relative_to(config.project_dir))

    # 2. Unpaywall
    if paper.doi and config.apis.unpaywall_email:
        from litscout.api_clients.unpaywall import UnpaywallClient

        uw = UnpaywallClient(email=config.apis.unpaywall_email)
        result = uw.get_oa_status(paper.doi)
        if result and result.pdf_url:
            ok, info = _download_pdf(result.pdf_url, dest)
            _log_retrieval(log_path, paper, "pdf", "unpaywall",
                           result.pdf_url,
                           "success" if ok else "failed",
                           file_path=str(dest.relative_to(config.project_dir)) if ok else None,
                           file_size=dest.stat().st_size if ok and dest.exists() else None,
                           content_type=info if ok else None,
                           error=None if ok else info)
            if ok:
                return str(dest.relative_to(config.project_dir))

    # 3. bioRxiv/medRxiv (DOI starts with 10.1101/)
    if paper.doi and paper.doi.startswith("10.1101/"):
        biorxiv_url = f"https://www.biorxiv.org/content/{paper.doi}v1.full.pdf"
        ok, info = _download_pdf(biorxiv_url, dest)
        _log_retrieval(log_path, paper, "pdf", "biorxiv",
                       biorxiv_url,
                       "success" if ok else "failed",
                       file_path=str(dest.relative_to(config.project_dir)) if ok else None,
                       file_size=dest.stat().st_size if ok and dest.exists() else None,
                       error=None if ok else info)
        if ok:
            return str(dest.relative_to(config.project_dir))

    # 4. arXiv
    if paper.arxiv_id:
        arxiv_url = f"https://arxiv.org/pdf/{paper.arxiv_id}"
        ok, info = _download_pdf(arxiv_url, dest)
        _log_retrieval(log_path, paper, "pdf", "arxiv",
                       arxiv_url,
                       "success" if ok else "failed",
                       file_path=str(dest.relative_to(config.project_dir)) if ok else None,
                       file_size=dest.stat().st_size if ok and dest.exists() else None,
                       error=None if ok else info)
        if ok:
            return str(dest.relative_to(config.project_dir))

    return None


def _try_structured_text_retrieval(
    paper: Paper,
    config: Config,
    xml_dir: Path,
    log_path: Path,
) -> str | None:
    """Try to retrieve structured XML/JSON text. Returns the path on success."""
    pmcid = paper.pmcid

    # Try to map PMID → PMCID if we don't have it
    if not pmcid and paper.pmid:
        from litscout.api_clients.pubmed import PubMedClient
        client = PubMedClient(
            email=config.apis.ncbi_email,
            api_key=config.apis.ncbi_api_key,
        )
        pmcid = client.pmid_to_pmcid(paper.pmid)

    if not pmcid:
        return None

    identifier = pmcid
    filename = sanitize_for_filename(identifier) + ".json"
    dest = xml_dir / filename

    # PMC BioC API
    from litscout.api_clients.pubmed import PubMedClient
    client = PubMedClient(
        email=config.apis.ncbi_email,
        api_key=config.apis.ncbi_api_key,
    )
    bioc_json = client.get_bioc_fulltext(pmcid)
    if bioc_json:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(bioc_json)
        _log_retrieval(log_path, paper, "xml", "pmc_bioc",
                       None, "success",
                       file_path=str(dest.relative_to(config.project_dir)),
                       file_size=len(bioc_json))
        return str(dest.relative_to(config.project_dir))

    _log_retrieval(log_path, paper, "xml", "pmc_bioc", None, "failed",
                   error="BioC not available")
    return None


def _determine_source(pdf_path: str | None, xml_path: str | None) -> FulltextSource | None:
    """Determine the fulltext_source based on what was retrieved."""
    if pdf_path and "unpaywall" in pdf_path:
        return FulltextSource.UNPAYWALL
    if xml_path:
        return FulltextSource.PMC_BIOC
    if pdf_path:
        return FulltextSource.SEMANTIC_SCHOLAR
    return None


def run_retrieve(
    config: Config,
    *,
    tag: str | None = None,
    retry_failed: bool = False,
    retry_manual_pending: bool = False,
    dry_run: bool = False,
    update_manual_list_only: bool = False,
) -> dict[str, int]:
    """Run full-text retrieval for papers in the registry.

    Returns a summary dict with counts of retrieved, failed, manual_pending.
    """
    papers_path = config.project_dir / "papers.jsonl"
    pdf_dir = config.project_dir / "fulltext" / "pdf"
    xml_dir = config.project_dir / "fulltext" / "xml"
    log_path = config.project_dir / "retrieval_log.jsonl"

    pdf_dir.mkdir(parents=True, exist_ok=True)
    xml_dir.mkdir(parents=True, exist_ok=True)

    if update_manual_list_only:
        manual_path = config.project_dir / "manual_retrieval_list.md"
        count = generate_manual_list(papers_path, manual_path)
        logger.info("Manual retrieval list updated: %d papers", count)
        return {"retrieved": 0, "failed": 0, "manual_pending": count}

    # Select papers to process
    all_papers = load_papers(papers_path)
    to_process: list[Paper] = []

    for paper in all_papers:
        if tag and tag not in paper.tags:
            continue
        if paper.fulltext_status == FulltextStatus.NOT_ATTEMPTED:
            to_process.append(paper)
        elif retry_failed and paper.fulltext_status == FulltextStatus.FAILED:
            to_process.append(paper)
        elif retry_manual_pending and paper.fulltext_status == FulltextStatus.MANUAL_PENDING:
            to_process.append(paper)

    if dry_run:
        logger.info("Dry run: would process %d papers", len(to_process))
        for p in to_process:
            logger.info("  %s — %s", p.paper_id, p.title[:60])
        return {"retrieved": 0, "failed": 0, "manual_pending": 0}

    retrieved = 0
    failed = 0

    for paper in tqdm(to_process, desc="Retrieving full text"):
        pdf_path = _try_pdf_retrieval(paper, config, pdf_dir, log_path)
        xml_path = _try_structured_text_retrieval(paper, config, xml_dir, log_path)

        updates: dict[str, Any] = {}
        if pdf_path or xml_path:
            updates["fulltext_status"] = FulltextStatus.RETRIEVED
            updates["needs_manual_retrieval"] = False
            if pdf_path:
                updates["fulltext_pdf_path"] = pdf_path
            if xml_path:
                updates["fulltext_xml_path"] = xml_path
            source = _determine_source(pdf_path, xml_path)
            if source:
                updates["fulltext_source"] = source
            retrieved += 1
        else:
            updates["fulltext_status"] = FulltextStatus.FAILED
            updates["needs_manual_retrieval"] = True
            failed += 1

        update_paper(papers_path, paper.paper_id, updates)

    # Generate manual retrieval list
    manual_path = config.project_dir / "manual_retrieval_list.md"
    manual_count = generate_manual_list(papers_path, manual_path)

    logger.info("Retrieval complete: %d retrieved, %d failed, %d manual pending",
                retrieved, failed, manual_count)

    return {"retrieved": retrieved, "failed": failed, "manual_pending": manual_count}
