"""Semantic Scholar API adapter — wraps the `semanticscholar` library."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from litscout.models import Author, DiscoveryMethod, Paper
from litscout.utils.identifiers import normalize_doi
from litscout.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Fields to request from the S2 API
S2_FIELDS = [
    "paperId",
    "externalIds",
    "title",
    "abstract",
    "year",
    "venue",
    "journal",
    "citationCount",
    "influentialCitationCount",
    "isOpenAccess",
    "openAccessPdf",
    "fieldsOfStudy",
    "tldr",
    "authors",
    "publicationTypes",
]

# Citations/references endpoints don't support tldr
S2_CITATION_FIELDS = [f for f in S2_FIELDS if f != "tldr"]


def _s2_to_paper(
    raw: Any,
    discovery_method: DiscoveryMethod = DiscoveryMethod.KEYWORD_SEARCH,
    discovery_query: str | None = None,
) -> Paper | None:
    """Convert a Semantic Scholar result object to a canonical Paper."""
    if raw is None:
        return None

    # Handle both dict-like and object-like access
    def get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    paper_id_raw = get(raw, "paperId")
    title = get(raw, "title")
    if not paper_id_raw or not title:
        return None

    ext_ids = get(raw, "externalIds") or {}
    if not isinstance(ext_ids, dict):
        ext_ids = {k: getattr(ext_ids, k, None) for k in ["DOI", "PubMed", "PubMedCentral", "ArXiv"]}

    journal_obj = get(raw, "journal") or {}
    oa_pdf = get(raw, "openAccessPdf") or {}
    tldr_obj = get(raw, "tldr") or {}
    authors_raw = get(raw, "authors") or []

    authors = []
    for a in authors_raw:
        a_name = get(a, "name")
        a_id = get(a, "authorId")
        if a_name:
            authors.append(Author(
                name=a_name,
                author_id=f"s2:{a_id}" if a_id else None,
            ))

    return Paper(
        paper_id=f"s2:{paper_id_raw}",
        doi=normalize_doi(get(ext_ids, "DOI")),
        pmid=get(ext_ids, "PubMed"),
        pmcid=get(ext_ids, "PubMedCentral"),
        arxiv_id=get(ext_ids, "ArXiv"),
        title=title,
        authors=authors,
        year=get(raw, "year"),
        venue=get(raw, "venue") or None,
        journal_name=get(journal_obj, "name") if isinstance(journal_obj, dict) else getattr(journal_obj, "name", None),
        citation_count=get(raw, "citationCount"),
        influential_citation_count=get(raw, "influentialCitationCount"),
        abstract=get(raw, "abstract"),
        tldr=get(tldr_obj, "text") if isinstance(tldr_obj, dict) else getattr(tldr_obj, "text", None),
        fields_of_study=get(raw, "fieldsOfStudy") or [],
        is_open_access=get(raw, "isOpenAccess"),
        open_access_pdf_url=(
            get(oa_pdf, "url") if isinstance(oa_pdf, dict) else getattr(oa_pdf, "url", None)
        ),
        source="semantic_scholar",
        discovery_method=discovery_method,
        discovery_query=discovery_query,
        discovery_date=date.today().isoformat(),
    )


class SemanticScholarClient:
    """Adapter around the `semanticscholar` library."""

    def __init__(self, api_key: str = "", rate_limit: float | None = None) -> None:
        from semanticscholar import SemanticScholar
        self._sch = SemanticScholar(api_key=api_key) if api_key else SemanticScholar()
        effective_rate = rate_limit or (10.0 if api_key else 0.8)
        self._limiter = RateLimiter(effective_rate)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def search_papers(
        self,
        query: str,
        *,
        year: str | None = None,
        fields_of_study: list[str] | None = None,
        min_citation_count: int | None = None,
        max_results: int = 100,
    ) -> list[Paper]:
        """Search for papers by keyword query."""
        self._limiter.acquire()
        logger.info("S2 search: query=%r max_results=%d", query, max_results)

        results = self._sch.search_paper(
            query,
            fields=S2_FIELDS,
            year=year,
            fields_of_study=fields_of_study,
            min_citation_count=str(min_citation_count) if min_citation_count else None,
            limit=min(max_results, 100),
        )

        papers: list[Paper] = []
        for item in results:
            if len(papers) >= max_results:
                break
            paper = _s2_to_paper(item, DiscoveryMethod.KEYWORD_SEARCH, query)
            if paper:
                papers.append(paper)

        logger.info("S2 search returned %d papers", len(papers))
        return papers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def get_paper(self, paper_id: str) -> Paper | None:
        """Fetch a single paper by its Semantic Scholar ID, DOI, PMID, etc."""
        self._limiter.acquire()
        result = self._sch.get_paper(paper_id, fields=S2_FIELDS)
        return _s2_to_paper(result)

    def get_paper_citations(self, paper_id: str, max_results: int = 500) -> list[Paper]:
        """Fetch papers that cite the given paper (forward citations)."""
        self._limiter.acquire()
        raw_id = paper_id.removeprefix("s2:")
        try:
            results = self._sch.get_paper_citations(
                raw_id, fields=S2_CITATION_FIELDS, limit=min(max_results, 1000)
            )
        except TypeError:
            # The S2 library crashes on null pagination data for some papers
            logger.warning("S2 returned no citation data for %s", paper_id)
            return []

        papers: list[Paper] = []
        for item in results:
            if len(papers) >= max_results:
                break
            citing = getattr(item, "citingPaper", item)
            paper = _s2_to_paper(citing, DiscoveryMethod.CITATION_FORWARD, paper_id)
            if paper:
                papers.append(paper)
        return papers

    def get_paper_references(self, paper_id: str, max_results: int = 500) -> list[Paper]:
        """Fetch papers referenced by the given paper (backward references)."""
        self._limiter.acquire()
        raw_id = paper_id.removeprefix("s2:")
        try:
            results = self._sch.get_paper_references(
                raw_id, fields=S2_CITATION_FIELDS, limit=min(max_results, 1000)
            )
        except TypeError:
            logger.warning("S2 returned no reference data for %s", paper_id)
            return []

        papers: list[Paper] = []
        for item in results:
            if len(papers) >= max_results:
                break
            cited = getattr(item, "citedPaper", item)
            paper = _s2_to_paper(cited, DiscoveryMethod.CITATION_BACKWARD, paper_id)
            if paper:
                papers.append(paper)
        return papers

    def get_recommendations(self, paper_ids: list[str], max_results: int = 100) -> list[Paper]:
        """Get algorithmic recommendations based on a set of positive-example papers."""
        self._limiter.acquire()
        raw_ids = [pid.removeprefix("s2:") for pid in paper_ids]
        try:
            results = self._sch.get_recommended_papers(raw_ids[0], limit=min(max_results, 500))
        except TypeError:
            logger.warning("S2 returned no recommendation data for %s", paper_ids)
            return []

        papers: list[Paper] = []
        for item in results:
            if len(papers) >= max_results:
                break
            paper = _s2_to_paper(item, DiscoveryMethod.RECOMMENDATION, ",".join(paper_ids))
            if paper:
                papers.append(paper)
        return papers
