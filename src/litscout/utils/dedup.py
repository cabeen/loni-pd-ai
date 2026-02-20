"""Deduplication utilities for papers across multiple sources."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from litscout.utils.identifiers import normalize_doi

if TYPE_CHECKING:
    from litscout.models import Paper


def _normalize_title(title: str) -> str:
    """Normalize a title for comparison: lowercase, strip punctuation, collapse whitespace."""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


class DedupIndex:
    """Index for fast deduplication of papers by DOI, PMID, and fuzzy title."""

    def __init__(self) -> None:
        self._doi_set: set[str] = set()
        self._pmid_set: set[str] = set()
        self._paper_id_set: set[str] = set()
        # Store (normalized_title, year) tuples for fuzzy matching
        self._title_year_pairs: list[tuple[str, int | None]] = []

    def add(self, paper: Paper) -> None:
        """Add a paper to the dedup index."""
        if paper.doi:
            ndoi = normalize_doi(paper.doi)
            if ndoi:
                self._doi_set.add(ndoi)
        if paper.pmid:
            self._pmid_set.add(paper.pmid)
        self._paper_id_set.add(paper.paper_id)
        if paper.title:
            self._title_year_pairs.append((_normalize_title(paper.title), paper.year))

    def is_duplicate(self, paper: Paper) -> bool:
        """Check if a paper is a duplicate of any paper already in the index."""
        # 1. Exact DOI match
        if paper.doi:
            ndoi = normalize_doi(paper.doi)
            if ndoi and ndoi in self._doi_set:
                return True

        # 2. Exact PMID match
        if paper.pmid and paper.pmid in self._pmid_set:
            return True

        # 3. Exact paper_id match
        if paper.paper_id in self._paper_id_set:
            return True

        # 4. Fuzzy title match (same year + high similarity)
        if paper.title:
            norm_title = _normalize_title(paper.title)
            for existing_title, existing_year in self._title_year_pairs:
                if paper.year is not None and existing_year is not None and paper.year != existing_year:
                    continue
                ratio = fuzz.ratio(norm_title, existing_title)
                if ratio > 92:
                    return True

        return False


def merge_paper_records(existing: Paper, new: Paper) -> Paper:
    """Merge two paper records, preferring the one with more metadata.

    Fills in missing fields from *new* into *existing* without overwriting
    non-null values.
    """
    data = existing.model_dump()
    new_data = new.model_dump()

    for key, value in new_data.items():
        existing_val = data.get(key)
        # Fill missing scalar fields
        if existing_val is None and value is not None:
            data[key] = value
        # Merge lists (extend without duplicates)
        elif isinstance(existing_val, list) and isinstance(value, list) and value:
            if not existing_val:
                data[key] = value

    from litscout.models import Paper
    return Paper(**data)
