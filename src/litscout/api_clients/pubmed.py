"""PubMed/NCBI API adapter — wraps Bio.Entrez and BioC REST API."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from xml.etree import ElementTree

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from litscout.models import Author, DiscoveryMethod, Paper
from litscout.utils.identifiers import normalize_doi
from litscout.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# NCBI ID converter URL
_IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"


def _xml_text(elem: ElementTree.Element | None, path: str, default: str = "") -> str:
    if elem is None:
        return default
    node = elem.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return default


def _parse_pubmed_article(article: ElementTree.Element, discovery_query: str | None = None) -> Paper | None:
    """Parse a single PubmedArticle XML element into a Paper."""
    medline = article.find("MedlineCitation")
    if medline is None:
        return None
    pmid_elem = medline.find("PMID")
    if pmid_elem is None or not pmid_elem.text:
        return None
    pmid = pmid_elem.text.strip()

    art = medline.find("Article")
    if art is None:
        return None

    title = _xml_text(art, "ArticleTitle")
    if not title:
        return None

    # Abstract
    abstract_parts: list[str] = []
    abstract_elem = art.find("Abstract")
    if abstract_elem is not None:
        for text_elem in abstract_elem.findall("AbstractText"):
            label = text_elem.get("Label", "")
            text = "".join(text_elem.itertext()).strip()
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
    abstract = " ".join(abstract_parts) if abstract_parts else None

    # Authors
    authors: list[Author] = []
    author_list = art.find("AuthorList")
    if author_list is not None:
        for author_elem in author_list.findall("Author"):
            last = _xml_text(author_elem, "LastName")
            fore = _xml_text(author_elem, "ForeName")
            if last:
                name = f"{fore} {last}".strip() if fore else last
                authors.append(Author(name=name))

    # Year
    year = None
    pub_date = art.find("Journal/JournalIssue/PubDate")
    if pub_date is not None:
        year_text = _xml_text(pub_date, "Year")
        medline_date = _xml_text(pub_date, "MedlineDate")
        if year_text:
            try:
                year = int(year_text)
            except ValueError:
                pass
        elif medline_date:
            # Format like "2023 Jan-Feb"
            try:
                year = int(medline_date[:4])
            except ValueError:
                pass

    # Journal/venue
    journal_name = _xml_text(art, "Journal/Title")
    venue = _xml_text(art, "Journal/ISOAbbreviation") or journal_name

    # DOI
    doi = None
    article_id_list = article.find("PubmedData/ArticleIdList")
    if article_id_list is not None:
        for aid in article_id_list.findall("ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = normalize_doi(aid.text.strip())
            elif aid.get("IdType") == "pmc" and aid.text:
                pmcid = aid.text.strip()

    # PMCID from article ID list
    pmcid = None
    if article_id_list is not None:
        for aid in article_id_list.findall("ArticleId"):
            if aid.get("IdType") == "pmc" and aid.text:
                pmcid = aid.text.strip()
                if not pmcid.startswith("PMC"):
                    pmcid = f"PMC{pmcid}"

    return Paper(
        paper_id=f"pmid:{pmid}",
        doi=doi,
        pmid=pmid,
        pmcid=pmcid,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        journal_name=journal_name,
        abstract=abstract,
        source="pubmed",
        discovery_method=DiscoveryMethod.KEYWORD_SEARCH,
        discovery_query=discovery_query,
        discovery_date=date.today().isoformat(),
    )


class PubMedClient:
    """Adapter around Bio.Entrez for PubMed search and retrieval."""

    def __init__(self, email: str = "", api_key: str = "") -> None:
        from Bio import Entrez

        self._entrez = Entrez
        if email:
            Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
        effective_rate = 8.0 if api_key else 2.0
        self._limiter = RateLimiter(effective_rate)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def search(
        self,
        query: str,
        *,
        year_range: tuple[int, int] | None = None,
        max_results: int = 100,
    ) -> list[Paper]:
        """Search PubMed by keyword query, returning canonical Paper objects."""
        self._limiter.acquire()

        # Build date filter
        if year_range:
            query = f"({query}) AND ({year_range[0]}:{year_range[1]}[pdat])"

        logger.info("PubMed search: query=%r max_results=%d", query, max_results)

        # Step 1: esearch to get PMIDs
        handle = self._entrez.esearch(
            db="pubmed", term=query, retmax=max_results, sort="relevance"
        )
        search_results = self._entrez.read(handle)
        handle.close()

        pmids = search_results.get("IdList", [])
        if not pmids:
            logger.info("PubMed search returned 0 results")
            return []

        logger.info("PubMed esearch returned %d PMIDs", len(pmids))

        # Step 2: efetch to get full metadata
        return self._fetch_by_pmids(pmids, discovery_query=query)

    def _fetch_by_pmids(self, pmids: list[str], discovery_query: str | None = None) -> list[Paper]:
        """Fetch full metadata for a list of PMIDs."""
        self._limiter.acquire()

        handle = self._entrez.efetch(
            db="pubmed", id=",".join(pmids), rettype="xml", retmode="xml"
        )
        xml_data = handle.read()
        handle.close()

        # Parse XML
        if isinstance(xml_data, bytes):
            xml_data = xml_data.decode("utf-8")

        root = ElementTree.fromstring(xml_data)
        papers: list[Paper] = []
        for article in root.findall("PubmedArticle"):
            paper = _parse_pubmed_article(article, discovery_query)
            if paper:
                papers.append(paper)

        logger.info("PubMed efetch parsed %d papers", len(papers))
        return papers

    def get_bioc_fulltext(self, pmcid: str) -> str | None:
        """Fetch full-text BioC JSON from the PMC BioC API.

        Returns the raw JSON string, or None if not available.
        """
        pmcid_clean = pmcid.replace("PMC", "")
        url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{pmcid_clean}/unicode"

        self._limiter.acquire()
        try:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/json"):
                return resp.text
        except httpx.HTTPError:
            logger.exception("BioC fetch failed for %s", pmcid)
        return None

    def pmid_to_pmcid(self, pmid: str) -> str | None:
        """Convert a PMID to a PMCID using the NCBI ID converter."""
        try:
            resp = httpx.get(
                _IDCONV_URL,
                params={"ids": pmid, "format": "json"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("records", [])
                if records and "pmcid" in records[0]:
                    return records[0]["pmcid"]
        except Exception:
            logger.exception("PMID→PMCID conversion failed for %s", pmid)
        return None
