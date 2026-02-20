"""Unpaywall API adapter — direct httpx calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from litscout.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.unpaywall.org/v2/"


@dataclass
class UnpaywallResult:
    is_oa: bool
    pdf_url: str | None
    landing_page_url: str | None
    host_type: str | None  # "publisher", "repository"
    license: str | None
    version: str | None  # "submittedVersion", "acceptedVersion", "publishedVersion"


class UnpaywallClient:
    """Client for the Unpaywall API."""

    def __init__(self, email: str) -> None:
        self._email = email
        self._limiter = RateLimiter(10.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def get_oa_status(self, doi: str) -> UnpaywallResult | None:
        """Look up OA status and best PDF URL for a DOI."""
        if not doi or not self._email:
            return None

        self._limiter.acquire()
        url = f"{_BASE_URL}{doi}"
        logger.debug("Unpaywall lookup: %s", doi)

        try:
            resp = httpx.get(url, params={"email": self._email}, timeout=15.0, follow_redirects=True)
            if resp.status_code == 404:
                return UnpaywallResult(is_oa=False, pdf_url=None, landing_page_url=None,
                                        host_type=None, license=None, version=None)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning("Unpaywall HTTP error for %s: %s", doi, e)
            return None

        data = resp.json()
        best = data.get("best_oa_location") or {}

        return UnpaywallResult(
            is_oa=data.get("is_oa", False),
            pdf_url=best.get("url_for_pdf"),
            landing_page_url=best.get("url_for_landing_page"),
            host_type=best.get("host_type"),
            license=best.get("license"),
            version=best.get("version"),
        )
