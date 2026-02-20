"""Citation expansion module — discover papers via citation graph exploration."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from litscout.config import Config
from litscout.models import Paper
from litscout.utils.dedup import DedupIndex
from litscout.utils.io import append_papers, load_papers

logger = logging.getLogger(__name__)


def _composite_score(
    paper: Paper,
    seed_connections: int,
    total_seeds: int,
    max_log_citations: float,
    min_year: int,
    max_year: int,
) -> float:
    """Compute the composite ranking score for a candidate paper.

    score = citation_normalized * 0.3 + seed_connection_ratio * 0.4
            + recency * 0.2 + influential_ratio * 0.1
    """
    # Citation count normalized (log scale)
    cc = paper.citation_count or 0
    log_cc = math.log(cc + 1)
    citation_norm = log_cc / max_log_citations if max_log_citations > 0 else 0

    # Seed connections ratio
    seed_ratio = seed_connections / total_seeds if total_seeds > 0 else 0

    # Recency score
    year = paper.year or min_year
    year_range = max_year - min_year
    recency = (year - min_year) / year_range if year_range > 0 else 0.5

    # Influential citation ratio
    icc = paper.influential_citation_count or 0
    influential_ratio = icc / (cc + 1)

    return citation_norm * 0.3 + seed_ratio * 0.4 + recency * 0.2 + influential_ratio * 0.1


def run_expand(
    config: Config,
    *,
    seed_tag: str = "seed",
    seed_dois: list[str] | None = None,
    strategy: str = "both",
    depth: int = 1,
    min_citation_count: int = 0,
    max_candidates: int = 500,
) -> tuple[list[Paper], dict[str, Any]]:
    """Run citation expansion from seed papers.

    Returns (new_papers_added, summary_dict).
    """
    from litscout.api_clients.semantic_scholar import SemanticScholarClient

    papers_path = config.project_dir / "papers.jsonl"
    client = SemanticScholarClient(api_key=config.apis.semantic_scholar_api_key)

    # Load seeds
    all_papers = load_papers(papers_path)
    seeds: list[Paper] = []

    if seed_dois:
        doi_set = {d.lower() for d in seed_dois}
        seeds = [p for p in all_papers if p.doi and p.doi.lower() in doi_set]
    else:
        seeds = [p for p in all_papers if seed_tag in p.tags]

    if not seeds:
        logger.warning("No seed papers found (tag=%s, dois=%s)", seed_tag, seed_dois)
        return [], {"candidates_found": 0, "new_papers_added": 0}

    logger.info("Expanding from %d seed papers, strategy=%s, depth=%d", len(seeds), strategy, depth)

    current_seeds = seeds
    all_new_papers: list[Paper] = []

    for d in range(depth):
        logger.info("Expansion depth %d/%d", d + 1, depth)

        # Track how many seeds each candidate is connected to
        candidate_connections: dict[str, int] = {}  # paper_id -> count
        candidate_map: dict[str, Paper] = {}

        for seed in current_seeds:
            raw_id = seed.paper_id

            discovered: list[Paper] = []

            if strategy in ("forward", "both", "all"):
                try:
                    fwd = client.get_paper_citations(raw_id, max_results=max_candidates)
                    discovered.extend(fwd)
                except Exception:
                    logger.exception("Forward citations failed for %s", raw_id)

            if strategy in ("backward", "both", "all"):
                try:
                    bwd = client.get_paper_references(raw_id, max_results=max_candidates)
                    discovered.extend(bwd)
                except Exception:
                    logger.exception("Backward references failed for %s", raw_id)

            if strategy in ("recommend", "all"):
                try:
                    recs = client.get_recommendations([raw_id], max_results=max_candidates)
                    discovered.extend(recs)
                except Exception:
                    logger.exception("Recommendations failed for %s", raw_id)

            for paper in discovered:
                paper.seed_paper_id = raw_id
                pid = paper.paper_id
                candidate_connections[pid] = candidate_connections.get(pid, 0) + 1
                if pid not in candidate_map:
                    candidate_map[pid] = paper

        # Filter by min citations
        if min_citation_count > 0:
            candidate_map = {
                pid: p for pid, p in candidate_map.items()
                if (p.citation_count or 0) >= min_citation_count
            }
            candidate_connections = {
                pid: c for pid, c in candidate_connections.items()
                if pid in candidate_map
            }

        # Score and rank candidates
        candidates = list(candidate_map.values())
        if not candidates:
            break

        all_citations = [math.log((p.citation_count or 0) + 1) for p in candidates]
        max_log_cc = max(all_citations) if all_citations else 1.0
        all_years = [p.year for p in candidates if p.year]
        min_year = min(all_years) if all_years else 2000
        max_year = max(all_years) if all_years else 2025

        scored: list[tuple[float, Paper]] = []
        for paper in candidates:
            sc = _composite_score(
                paper,
                seed_connections=candidate_connections.get(paper.paper_id, 1),
                total_seeds=len(current_seeds),
                max_log_citations=max_log_cc,
                min_year=min_year,
                max_year=max_year,
            )
            scored.append((sc, paper))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [p for _, p in scored[:max_candidates]]

        # Append to papers.jsonl
        new_count = append_papers(top_candidates, papers_path)
        all_new_papers.extend(top_candidates[:new_count])

        logger.info("Depth %d: %d candidates found, %d new papers added",
                     d + 1, len(candidates), new_count)

        # For next depth, use the top newly discovered papers as seeds
        if d < depth - 1:
            current_seeds = top_candidates[:min(10, len(top_candidates))]

    # Write expansion log
    expansions_dir = config.project_dir / "expansions"
    expansions_dir.mkdir(exist_ok=True)
    log_filename = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_expansion.jsonl"
    log_path = expansions_dir / log_filename

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "seed_count": len(seeds),
        "seed_tag": seed_tag,
        "seed_dois": seed_dois,
        "strategy": strategy,
        "depth": depth,
        "candidates_found": len(all_new_papers),
        "new_papers_added": len(all_new_papers),
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    summary = {
        "candidates_found": len(all_new_papers),
        "new_papers_added": len(all_new_papers),
    }
    return all_new_papers, summary
