"""Identifier normalization and conversion utilities."""

from __future__ import annotations

import re


def normalize_doi(doi: str | None) -> str | None:
    """Normalize a DOI: strip URL prefixes, lowercase.

    Handles formats like:
      - 10.1038/s41586-023-06424-7
      - https://doi.org/10.1038/s41586-023-06424-7
      - http://dx.doi.org/10.1038/s41586-023-06424-7
    """
    if not doi:
        return None
    doi = doi.strip()
    # Strip common URL prefixes
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.lower().strip()


def sanitize_for_filename(identifier: str) -> str:
    """Convert an identifier (DOI, paper ID) into a safe filename component.

    Replaces / with _, strips characters that are unsafe for filenames.
    """
    s = identifier.replace("/", "_")
    s = re.sub(r'[<>:"|?*\\]', "", s)
    return s


def reconstruct_abstract(inverted_index: dict[str, list[int]]) -> str:
    """Reconstruct a plain-text abstract from OpenAlex's inverted-index format.

    The inverted index maps each word to a list of positions (0-indexed).
    """
    if not inverted_index:
        return ""
    # Find total length
    max_pos = -1
    for positions in inverted_index.values():
        for pos in positions:
            if pos > max_pos:
                max_pos = pos
    if max_pos < 0:
        return ""

    words: list[str] = [""] * (max_pos + 1)
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)


def extract_doi_from_string(s: str) -> str | None:
    """Try to extract a DOI from an arbitrary string (e.g. a filename)."""
    match = re.search(r"(10\.\d{4,9}[/_][^\s]+)", s)
    if match:
        doi = match.group(1)
        # Clean up trailing punctuation or file extensions
        doi = re.sub(r"\.(pdf|xml|txt|html)$", "", doi, flags=re.IGNORECASE)
        doi = doi.rstrip(".,;")
        # Convert _ back to / for DOIs that were sanitized
        if "/" not in doi and "_" in doi:
            # Replace only the first _ with / (the separator between prefix and suffix)
            doi = doi.replace("_", "/", 1)
        return normalize_doi(doi)
    return None
