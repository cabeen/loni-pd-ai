"""CLI entry point for LitScout."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from litscout import __version__

logger = logging.getLogger("litscout")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.version_option(version=__version__, prog_name="litscout")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option(
    "-d", "--project-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Project directory (default: current directory).",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, project_dir: Path) -> None:
    """LitScout: Scientific literature search & retrieval toolkit."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["project_dir"] = project_dir.resolve()


# ---------- search ----------


@cli.command()
@click.argument("query")
@click.option(
    "--sources", default="semantic_scholar",
    help="Comma-separated list of sources: semantic_scholar, pubmed, openalex.",
)
@click.option("--year-range", nargs=2, type=int, default=None, help="Start and end year.")
@click.option("--min-citations", type=int, default=0, help="Minimum citation count.")
@click.option("--max-results", type=int, default=100, help="Max results per source.")
@click.option("--tag", default=None, help="Tag to apply to discovered papers.")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    sources: str,
    year_range: tuple[int, int] | None,
    min_citations: int,
    max_results: int,
    tag: str | None,
) -> None:
    """Search for papers by keyword query."""
    from litscout.config import load_config
    from litscout.search import run_search

    config = load_config(ctx.obj["project_dir"])
    source_list = [s.strip() for s in sources.split(",")]

    click.echo(f"Searching for: {query}")
    click.echo(f"Sources: {', '.join(source_list)}")

    papers, log = run_search(
        query,
        config,
        sources=source_list,
        year_range=year_range,
        min_citation_count=min_citations,
        max_results=max_results,
        tag=tag,
    )

    click.echo(f"\nResults: {log.total_results} total, {log.new_papers_added} new, "
               f"{log.duplicates_skipped} duplicates skipped")


# ---------- expand ----------


@cli.command()
@click.option("--seed-tag", default="seed", help="Tag identifying seed papers.")
@click.option("--seed-dois", default=None, help="Comma-separated DOIs of seed papers.")
@click.option(
    "--strategy", type=click.Choice(["forward", "backward", "both", "recommend", "all"]),
    default="both", help="Expansion strategy.",
)
@click.option("--depth", type=int, default=1, help="Expansion depth.")
@click.option("--min-citations", type=int, default=0, help="Minimum citations for candidates.")
@click.option("--max-candidates", type=int, default=500, help="Max candidates to add.")
@click.pass_context
def expand(
    ctx: click.Context,
    seed_tag: str,
    seed_dois: str | None,
    strategy: str,
    depth: int,
    min_citations: int,
    max_candidates: int,
) -> None:
    """Expand corpus via citation graph from seed papers."""
    from litscout.config import load_config
    from litscout.expand import run_expand

    config = load_config(ctx.obj["project_dir"])
    doi_list = [d.strip() for d in seed_dois.split(",")] if seed_dois else None

    click.echo(f"Expanding from seeds (tag={seed_tag}, dois={doi_list})")
    click.echo(f"Strategy: {strategy}, depth: {depth}")

    new_papers, summary = run_expand(
        config,
        seed_tag=seed_tag,
        seed_dois=doi_list,
        strategy=strategy,
        depth=depth,
        min_citation_count=min_citations,
        max_candidates=max_candidates,
    )

    click.echo(f"\nExpansion complete: {summary['candidates_found']} candidates found, "
               f"{summary['new_papers_added']} new papers added")


# ---------- retrieve ----------


@cli.command()
@click.option("--tag", default=None, help="Only retrieve papers with this tag.")
@click.option("--retry-failed", is_flag=True, help="Retry previously failed papers.")
@click.option("--retry-manual-pending", is_flag=True, help="Retry papers flagged for manual retrieval.")
@click.option("--dry-run", is_flag=True, help="Show what would be attempted.")
@click.option("--update-manual-list", is_flag=True, help="Only regenerate the manual retrieval list.")
@click.pass_context
def retrieve(
    ctx: click.Context,
    tag: str | None,
    retry_failed: bool,
    retry_manual_pending: bool,
    dry_run: bool,
    update_manual_list: bool,
) -> None:
    """Retrieve full-text PDFs and structured text for papers."""
    from litscout.config import load_config
    from litscout.retrieve import run_retrieve

    config = load_config(ctx.obj["project_dir"])

    result = run_retrieve(
        config,
        tag=tag,
        retry_failed=retry_failed,
        retry_manual_pending=retry_manual_pending,
        dry_run=dry_run,
        update_manual_list_only=update_manual_list,
    )

    click.echo(f"\nRetrieval complete: {result['retrieved']} retrieved, "
               f"{result['failed']} failed, {result['manual_pending']} need manual retrieval")


# ---------- ingest ----------


@cli.command()
@click.option("--extract", "do_extract", is_flag=True, help="Also extract text after ingesting.")
@click.option("--dry-run", is_flag=True, help="Preview matching without moving files.")
@click.pass_context
def ingest(ctx: click.Context, do_extract: bool, dry_run: bool) -> None:
    """Match and ingest manually downloaded PDFs from the inbox."""
    from litscout.config import load_config
    from litscout.ingest import run_ingest

    config = load_config(ctx.obj["project_dir"])
    result = run_ingest(config, extract=do_extract, dry_run=dry_run)

    click.echo(f"\nIngest complete: {result['ingested']} ingested, "
               f"{result['unmatched']} unmatched, {result['still_pending']} still need manual retrieval")


# ---------- extract ----------


@cli.command()
@click.option("--doi", default=None, help="Extract a specific paper by DOI.")
@click.option("--status", default=None, help="Extract papers with this fulltext_status.")
@click.option("--max-tokens", type=int, default=None, help="Override max tokens per doc.")
@click.pass_context
def extract(ctx: click.Context, doi: str | None, status: str | None, max_tokens: int | None) -> None:
    """Extract clean text from retrieved PDFs and XMLs."""
    from litscout.config import load_config
    from litscout.extract import run_extract

    config = load_config(ctx.obj["project_dir"])
    result = run_extract(config, doi=doi, status=status, max_tokens=max_tokens)

    click.echo(f"\nExtraction complete: {result['extracted']} papers processed, "
               f"{result['skipped']} skipped, {result['errors']} errors")


# ---------- report ----------


@cli.command()
@click.option(
    "--format", "fmt", type=click.Choice(["text", "markdown", "json"]),
    default="text", help="Output format.",
)
@click.pass_context
def report(ctx: click.Context, fmt: str) -> None:
    """Generate a corpus summary report."""
    from litscout.config import load_config
    from litscout.report import run_report

    config = load_config(ctx.obj["project_dir"])
    output = run_report(config, fmt=fmt)
    click.echo(output)


# ---------- init ----------


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize a new LitScout project directory."""
    from litscout.config import generate_default_toml

    project_dir = ctx.obj["project_dir"]

    # Create directory structure
    dirs = [
        "searches",
        "expansions",
        "fulltext/pdf",
        "fulltext/xml",
        "fulltext/txt",
        "fulltext/inbox/processed",
        "reports",
    ]
    for d in dirs:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # Write default config
    toml_path = project_dir / "litscout.toml"
    if toml_path.exists():
        click.echo("litscout.toml already exists — skipping.")
    else:
        toml_path.write_text(generate_default_toml())
        click.echo(f"Created {toml_path}")

    click.echo("Project initialized. Edit litscout.toml to configure API keys and search defaults.")
