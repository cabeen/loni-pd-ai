"""OpenAlex API adapter — wraps the `pyalex` library."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from litscout.models import Author, DiscoveryMethod, Paper
from litscout.utils.identifiers import normalize_doi, reconstruct_abstract
from litscout.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def _openalex_to_paper(
    work: dict[str, Any],
    discovery_method: DiscoveryMethod = DiscoveryMethod.KEYWORD_SEARCH,
    discovery_query: str | None = None,
) -> Paper | None:
    """Convert an OpenAlex Work dict to a canonical Paper."""
    oalex_id = work.get("id", "")
    title = work.get("title")
    if not oalex_id or not title:
        return None

    # Extract short ID from URL
    short_id = oalex_id.split("/")[-1] if "/" in oalex_id else oalex_id

    # DOI
    doi_raw = work.get("doi")
    doi = normalize_doi(doi_raw) if doi_raw else None

    # IDs
    ids = work.get("ids", {})
    pmid = None
    pmcid = None
    if ids.get("pmid"):
        pmid_url = ids["pmid"]
        pmid = pmid_url.split("/")[-1] if "/" in pmid_url else pmid_url

    if ids.get("pmcid"):
        pmcid_url = ids["pmcid"]
        pmcid = pmcid_url.split("/")[-1] if "/" in pmcid_url else pmcid_url

    # Authors
    authors: list[Author] = []
    for authorship in work.get("authorships", []):
        author_info = authorship.get("author", {})
        name = author_info.get("display_name")
        if name:
            a_id = author_info.get("id", "")
            short_a_id = a_id.split("/")[-1] if a_id and "/" in a_id else a_id
            authors.append(Author(
                name=name,
                author_id=f"oalex:{short_a_id}" if short_a_id else None,
            ))

    # Abstract (inverted index)
    abstract = None
    abstract_idx = work.get("abstract_inverted_index")
    if abstract_idx:
        abstract = reconstruct_abstract(abstract_idx)

    # Open access
    oa = work.get("open_access", {})
    is_oa = oa.get("is_oa", False)
    oa_url = oa.get("oa_url")

    # Venue / journal
    primary_location = work.get("primary_location", {}) or {}
    source_info = primary_location.get("source", {}) or {}
    journal_name = source_info.get("display_name")
    venue = journal_name

    # Fields of study (concepts)
    concepts = work.get("concepts", [])
    fields_of_study = [c.get("display_name", "") for c in concepts[:5] if c.get("display_name")]

    return Paper(
        paper_id=f"oalex:{short_id}",
        doi=doi,
        pmid=pmid,
        pmcid=pmcid,
        title=title,
        authors=authors,
        year=work.get("publication_year"),
        venue=venue,
        journal_name=journal_name,
        citation_count=work.get("cited_by_count"),
        abstract=abstract,
        fields_of_study=fields_of_study,
        is_open_access=is_oa,
        open_access_pdf_url=oa_url,
        source="openalex",
        discovery_method=discovery_method,
        discovery_query=discovery_query,
        discovery_date=date.today().isoformat(),
    )


class OpenAlexClient:
    """Adapter around the `pyalex` library."""

    def __init__(self, email: str = "", api_key: str = "") -> None:
        import pyalex

        if email:
            pyalex.config.email = email
        if api_key:
            pyalex.config.api_key = api_key

        self._limiter = RateLimiter(10.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def search_works(
        self,
        query: str,
        *,
        year_range: tuple[int, int] | None = None,
        min_citation_count: int = 0,
        max_results: int = 100,
    ) -> list[Paper]:
        """Search OpenAlex Works by keyword query."""
        from pyalex import Works

        self._limiter.acquire()
        logger.info("OpenAlex search: query=%r max_results=%d", query, max_results)

        chain = Works().search(query)

        filters: dict[str, Any] = {"type": "article"}
        if year_range:
            filters["publication_year"] = f"{year_range[0]}-{year_range[1]}"
        if min_citation_count > 0:
            filters["cited_by_count"] = f">{min_citation_count}"

        chain = chain.filter(**filters)

        papers: list[Paper] = []
        for page in chain.paginate(per_page=min(max_results, 200)):
            for work in page:
                if len(papers) >= max_results:
                    break
                paper = _openalex_to_paper(work, DiscoveryMethod.KEYWORD_SEARCH, query)
                if paper:
                    papers.append(paper)
            if len(papers) >= max_results:
                break

        logger.info("OpenAlex search returned %d papers", len(papers))
        return papers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def get_work(self, work_id: str) -> Paper | None:
        """Fetch a single work by OpenAlex ID or DOI."""
        from pyalex import Works

        self._limiter.acquire()
        try:
            work = Works()[work_id]
            return _openalex_to_paper(work)
        except Exception:
            logger.exception("Failed to fetch OpenAlex work: %s", work_id)
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def get_cited_by(self, work_id: str, max_results: int = 500) -> list[Paper]:
        """Get works that cite the given work (forward citations).

        *work_id* can be an OpenAlex ID (W...), a DOI, or a prefixed paper_id.
        """
        from pyalex import Works

        oalex_id = self._resolve_to_openalex_id(work_id)
        if not oalex_id:
            return []

        self._limiter.acquire()
        logger.info("OpenAlex get_cited_by: %s (resolved=%s) max=%d", work_id, oalex_id, max_results)

        papers: list[Paper] = []
        for page in Works().filter(cites=oalex_id).paginate(per_page=min(max_results, 200)):
            for work in page:
                if len(papers) >= max_results:
                    break
                paper = _openalex_to_paper(work, DiscoveryMethod.CITATION_FORWARD, work_id)
                if paper:
                    papers.append(paper)
            if len(papers) >= max_results:
                break

        logger.info("OpenAlex get_cited_by returned %d papers", len(papers))
        return papers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def get_references(self, work_id: str, max_results: int = 500) -> list[Paper]:
        """Get works referenced by the given work (backward references).

        Uses the referenced_works field on the work object to batch-fetch details.
        """
        from pyalex import Works

        oalex_id = self._resolve_to_openalex_id(work_id)
        if not oalex_id:
            return []

        self._limiter.acquire()
        logger.info("OpenAlex get_references: %s (resolved=%s) max=%d", work_id, oalex_id, max_results)

        try:
            work = Works()[oalex_id]
        except Exception:
            logger.exception("Failed to fetch work for references: %s", work_id)
            return []

        ref_ids = work.get("referenced_works", [])
        if not ref_ids:
            logger.info("OpenAlex: no referenced_works for %s", work_id)
            return []

        # Trim to max_results before fetching details
        ref_ids = ref_ids[:max_results]

        # Batch fetch via filter (OpenAlex supports openalex_id filter with | OR)
        papers: list[Paper] = []
        # Process in chunks of 50 (API limit on OR filters)
        for i in range(0, len(ref_ids), 50):
            chunk = ref_ids[i:i + 50]
            self._limiter.acquire()
            id_filter = "|".join(chunk)
            try:
                for page in Works().filter(openalex_id=id_filter).paginate(per_page=200):
                    for w in page:
                        paper = _openalex_to_paper(w, DiscoveryMethod.CITATION_BACKWARD, work_id)
                        if paper:
                            papers.append(paper)
            except Exception:
                logger.exception("Failed to fetch reference batch for %s", work_id)

        logger.info("OpenAlex get_references returned %d papers", len(papers))
        return papers

    def _resolve_to_openalex_id(self, paper_id: str) -> str | None:
        """Resolve any identifier to a raw OpenAlex ID (W...).

        The `cites` filter requires a raw OpenAlex ID, not a DOI URL.
        """
        from pyalex import Works

        # Already a raw OpenAlex ID
        if paper_id.startswith("oalex:"):
            return paper_id.removeprefix("oalex:")
        if paper_id.startswith("W") and paper_id[1:].isdigit():
            return paper_id

        # DOI — look up via Works[] to get the OpenAlex ID
        if paper_id.startswith("10."):
            doi_url = f"doi:https://doi.org/{paper_id}"
        elif paper_id.startswith("s2:") or paper_id.startswith("pmid:"):
            logger.warning("Cannot resolve %s to OpenAlex ID without a DOI", paper_id)
            return None
        else:
            doi_url = paper_id

        self._limiter.acquire()
        try:
            work = Works()[doi_url]
            oalex_id = work.get("id", "")
            # Extract W... from full URL like https://openalex.org/W1234567
            return oalex_id.split("/")[-1] if "/" in oalex_id else oalex_id
        except Exception:
            logger.warning("Could not resolve %s to OpenAlex ID", paper_id)
            return None
