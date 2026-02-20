"""Rank module — score and rank papers in the corpus."""

from __future__ import annotations

import logging
import math
from typing import Any

from tqdm import tqdm

from litscout.config import Config
from litscout.models import Paper
from litscout.utils.io import load_papers, update_paper

logger = logging.getLogger(__name__)


def _bibliometric_score(paper: Paper, max_log_citations: float, min_year: int, max_year: int) -> float:
    """Compute a bibliometric score from citation count and recency.

    score = citation_normalized * 0.6 + recency * 0.3 + influential_ratio * 0.1
    """
    cc = paper.citation_count or 0
    log_cc = math.log(cc + 1)
    citation_norm = log_cc / max_log_citations if max_log_citations > 0 else 0

    year = paper.year or min_year
    year_range = max_year - min_year
    recency = (year - min_year) / year_range if year_range > 0 else 0.5

    icc = paper.influential_citation_count or 0
    influential_ratio = icc / (cc + 1)

    return citation_norm * 0.6 + recency * 0.3 + influential_ratio * 0.1


def _llm_relevance_score(paper: Paper, prompt: str, api_key: str) -> float:
    """Score a paper's relevance to a research prompt using an LLM.

    Returns a score from 0.0 to 1.0.
    """
    import httpx

    paper_text = f"Title: {paper.title}"
    if paper.abstract:
        paper_text += f"\nAbstract: {paper.abstract}"
    if paper.year:
        paper_text += f"\nYear: {paper.year}"
    if paper.venue or paper.journal_name:
        paper_text += f"\nVenue: {paper.venue or paper.journal_name}"

    system_msg = (
        "You are a research relevance scorer. Given a research focus and a paper, "
        "rate the paper's relevance on a scale of 0 to 10, where 0 means completely "
        "irrelevant and 10 means directly addresses the research focus. "
        "Respond with ONLY a single integer from 0 to 10, nothing else."
    )

    user_msg = f"Research focus: {prompt}\n\n---\n\n{paper_text}"

    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 8,
                "system": system_msg,
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"].strip()
        score = int(text)
        return max(0.0, min(1.0, score / 10.0))
    except (ValueError, KeyError, httpx.HTTPError) as e:
        logger.warning("LLM scoring failed for %s: %s", paper.paper_id, e)
        return 0.5  # neutral fallback


def run_rank(
    config: Config,
    *,
    top: int = 20,
    tag: str | None = None,
    filter_tag: str | None = None,
    filter_method: str | None = None,
    relevance_prompt: str | None = None,
    relevance_weight: float = 0.5,
) -> list[tuple[float, Paper]]:
    """Score and rank papers in the corpus.

    Parameters
    ----------
    top : int
        Number of top papers to return.
    tag : str, optional
        If set, apply this tag to the top N papers.
    filter_tag : str, optional
        Only rank papers with this existing tag.
    filter_method : str, optional
        Only rank papers with this discovery_method.
    relevance_prompt : str, optional
        If set, use LLM scoring with this research focus description.
    relevance_weight : float
        Weight of LLM relevance score vs bibliometric score (0.0-1.0).
        Only used when relevance_prompt is set.

    Returns
    -------
    list of (score, Paper) tuples, sorted descending.
    """
    import os

    papers_path = config.project_dir / "papers.jsonl"
    all_papers = load_papers(papers_path)

    # Apply filters
    papers = all_papers
    if filter_tag:
        papers = [p for p in papers if filter_tag in p.tags]
    if filter_method:
        papers = [p for p in papers if p.discovery_method == filter_method]

    if not papers:
        logger.warning("No papers match the filters")
        return []

    # Compute bibliometric scores
    all_citations = [math.log((p.citation_count or 0) + 1) for p in papers]
    max_log_cc = max(all_citations) if all_citations else 1.0
    all_years = [p.year for p in papers if p.year]
    min_year = min(all_years) if all_years else 2000
    max_year = max(all_years) if all_years else 2025

    bib_scores: dict[str, float] = {}
    for paper in papers:
        bib_scores[paper.paper_id] = _bibliometric_score(paper, max_log_cc, min_year, max_year)

    # LLM relevance scoring (optional)
    llm_scores: dict[str, float] = {}
    if relevance_prompt:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY not set — skipping LLM scoring")
        else:
            logger.info("Scoring %d papers with LLM relevance prompt", len(papers))
            for paper in tqdm(papers, desc="LLM scoring"):
                llm_scores[paper.paper_id] = _llm_relevance_score(paper, relevance_prompt, api_key)

    # Combine scores
    scored: list[tuple[float, Paper]] = []
    for paper in papers:
        bib = bib_scores[paper.paper_id]
        if llm_scores:
            llm = llm_scores.get(paper.paper_id, 0.5)
            combined = (1.0 - relevance_weight) * bib + relevance_weight * llm
        else:
            combined = bib
        scored.append((combined, paper))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_scored = scored[:top]

    # Apply tag to top papers
    if tag:
        for _, paper in top_scored:
            if tag not in paper.tags:
                new_tags = paper.tags + [tag]
                update_paper(papers_path, paper.paper_id, {"tags": new_tags})
        logger.info("Tagged top %d papers with %r", len(top_scored), tag)

    return top_scored
