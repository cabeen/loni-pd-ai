"""Search module — orchestrates keyword searches across multiple APIs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from litscout.config import Config
from litscout.models import Paper, SearchLog
from litscout.utils.dedup import DedupIndex
from litscout.utils.io import append_papers, load_papers

logger = logging.getLogger(__name__)


def _run_semantic_scholar_search(
    query: str,
    config: Config,
    *,
    year_range: tuple[int, int] | None = None,
    fields_of_study: list[str] | None = None,
    min_citation_count: int = 0,
    max_results: int = 100,
) -> list[Paper]:
    from litscout.api_clients.semantic_scholar import SemanticScholarClient

    client = SemanticScholarClient(api_key=config.apis.semantic_scholar_api_key)
    year_str = f"{year_range[0]}-{year_range[1]}" if year_range else None
    return client.search_papers(
        query,
        year=year_str,
        fields_of_study=fields_of_study or None,
        min_citation_count=min_citation_count or None,
        max_results=max_results,
    )


def _run_pubmed_search(
    query: str,
    config: Config,
    *,
    year_range: tuple[int, int] | None = None,
    max_results: int = 100,
) -> list[Paper]:
    from litscout.api_clients.pubmed import PubMedClient

    client = PubMedClient(
        email=config.apis.ncbi_email,
        api_key=config.apis.ncbi_api_key,
    )
    return client.search(query, year_range=year_range, max_results=max_results)


def _run_openalex_search(
    query: str,
    config: Config,
    *,
    year_range: tuple[int, int] | None = None,
    min_citation_count: int = 0,
    max_results: int = 100,
) -> list[Paper]:
    from litscout.api_clients.openalex import OpenAlexClient

    client = OpenAlexClient(email=config.apis.unpaywall_email)
    return client.search_works(
        query,
        year_range=year_range,
        min_citation_count=min_citation_count,
        max_results=max_results,
    )


_SOURCE_DISPATCH = {
    "semantic_scholar": _run_semantic_scholar_search,
    "pubmed": _run_pubmed_search,
    "openalex": _run_openalex_search,
}


def run_search(
    query: str,
    config: Config,
    *,
    sources: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
    fields_of_study: list[str] | None = None,
    min_citation_count: int = 0,
    max_results: int = 100,
    tag: str | None = None,
) -> tuple[list[Paper], SearchLog]:
    """Execute a keyword search across the requested sources, dedup, and return results.

    Returns (new_papers, search_log).
    """
    sources = sources or ["semantic_scholar"]
    if year_range is None:
        yr = config.search.year_range
        year_range = (yr[0], yr[1])
    if fields_of_study is None:
        fields_of_study = config.search.fields_of_study

    all_papers: list[Paper] = []
    for source in sources:
        runner = _SOURCE_DISPATCH.get(source)
        if runner is None:
            logger.warning("Unknown search source: %s", source)
            continue

        kwargs: dict = dict(
            config=config,
            year_range=year_range,
            max_results=max_results,
        )
        if source == "semantic_scholar":
            kwargs["fields_of_study"] = fields_of_study
            kwargs["min_citation_count"] = min_citation_count
        elif source == "openalex":
            kwargs["min_citation_count"] = min_citation_count

        try:
            results = runner(query, **kwargs)
            logger.info("Source %s returned %d results", source, len(results))
            all_papers.extend(results)
        except Exception:
            logger.exception("Search failed for source %s", source)

    # Cross-source dedup
    dedup = DedupIndex()
    unique_papers: list[Paper] = []
    for paper in all_papers:
        if not dedup.is_duplicate(paper):
            if tag:
                paper.tags.append(tag)
            dedup.add(paper)
            unique_papers.append(paper)

    # Append to papers.jsonl (further dedup against existing)
    papers_path = config.project_dir / "papers.jsonl"
    new_count = append_papers(unique_papers, papers_path)

    search_log = SearchLog(
        timestamp=datetime.now(timezone.utc).isoformat(),
        query=query,
        sources=sources,
        year_range=list(year_range) if year_range else None,
        min_citation_count=min_citation_count,
        max_results=max_results,
        fields_of_study=fields_of_study,
        total_results=len(all_papers),
        new_papers_added=new_count,
        duplicates_skipped=len(all_papers) - new_count,
    )

    # Write search log
    searches_dir = config.project_dir / "searches"
    searches_dir.mkdir(exist_ok=True)
    safe_query = query[:50].replace(" ", "_").replace("/", "_")
    log_filename = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{safe_query}.jsonl"
    log_path = searches_dir / log_filename
    with open(log_path, "a") as f:
        f.write(search_log.model_dump_json() + "\n")

    return unique_papers, search_log
