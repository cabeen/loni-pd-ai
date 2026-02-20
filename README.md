# LitScout

A Python toolkit for programmatic scientific literature search, citation graph exploration, and full-text retrieval. Designed for building reproducible, inspectable literature corpora — particularly useful when paired with LLMs for research synthesis.

## What it does

LitScout provides a CLI pipeline that takes you from a keyword query to an LLM-ready text corpus:

1. **Search** across Semantic Scholar, PubMed, and OpenAlex with cross-source deduplication
2. **Expand** your corpus by walking the citation graph (forward, backward, or algorithmic recommendations)
3. **Retrieve** full-text PDFs and structured XML through a fallback chain (S2 → Unpaywall → PMC → preprints)
4. **Ingest** manually downloaded PDFs by matching them to known papers
5. **Extract** clean, structured text from PDFs and XML, optimized for LLM consumption
6. **Report** on corpus statistics: coverage, retrieval gaps, citation distributions

Everything is stored in a single project directory with human-readable files (`papers.jsonl`, search logs, retrieval logs), making the entire workflow reproducible and version-controllable.

## Requirements

- Python 3.11+

## Installation

```bash
pip install -e ".[dev]"
```

## Quickstart

### 1. Initialize a project

```bash
mkdir my-review && cd my-review
litscout init
```

This creates the directory structure and a `litscout.toml` config file. Edit `litscout.toml` to add your API keys and email:

```toml
[apis]
semantic_scholar_api_key = ""   # optional, increases rate limits
unpaywall_email = "you@university.edu"  # required for Unpaywall
ncbi_email = "you@university.edu"       # required for PubMed
```

API keys can also be set via environment variables: `SEMANTIC_SCHOLAR_API_KEY`, `NCBI_API_KEY`, `OPENALEX_API_KEY`.

### 2. Search for papers

```bash
# Search Semantic Scholar (default)
litscout search "alpha-synuclein aggregation parkinson" --max-results 20 --tag seed

# Search multiple sources
litscout search "alpha-synuclein parkinson" \
    --sources semantic_scholar,pubmed,openalex \
    --year-range 2018 2025 \
    --min-citations 10 \
    --max-results 50
```

Results are deduplicated across sources and appended to `papers.jsonl`.

### 3. Expand via citations

```bash
# Expand from papers tagged "seed" — fetch their citations and references
litscout expand --seed-tag seed --strategy both --max-candidates 200

# Forward citations only, with a citation threshold
litscout expand --seed-tag seed --strategy forward --min-citations 5
```

### 4. Retrieve full text

```bash
# Attempt retrieval for all papers
litscout retrieve

# Dry run to see what would be attempted
litscout retrieve --dry-run

# Retry papers that previously failed
litscout retrieve --retry-failed
```

After retrieval, `manual_retrieval_list.md` lists papers that couldn't be obtained programmatically, sorted by priority.

### 5. Ingest manually downloaded PDFs

For paywalled papers, download PDFs through institutional access and drop them into `fulltext/inbox/`:

```bash
litscout ingest              # match and move PDFs
litscout ingest --extract    # also extract text immediately
litscout ingest --dry-run    # preview matches without moving files
```

The ingester matches files by DOI in the filename, PDF metadata, or first-page text.

### 6. Extract text for LLMs

```bash
litscout extract                     # extract all retrieved papers
litscout extract --max-tokens 12000  # custom token limit
```

Produces clean structured text files in `fulltext/txt/`, with section headers and metadata, truncated to fit LLM context windows.

### 7. View corpus summary

```bash
litscout report                   # plain text
litscout report --format markdown # markdown table
litscout report --format json     # machine-readable
```

## Project directory structure

After running the pipeline, your project directory looks like:

```
my-review/
├── litscout.toml                 # Configuration
├── papers.jsonl                  # Canonical paper registry (one JSON per line)
├── searches/                     # Search execution logs
├── expansions/                   # Citation expansion logs
├── retrieval_log.jsonl           # Record of every retrieval attempt
├── manual_retrieval_list.md      # Papers needing manual download
├── fulltext/
│   ├── pdf/                      # Retrieved PDFs
│   ├── xml/                      # PMC BioC structured text
│   ├── txt/                      # Extracted LLM-ready text
│   └── inbox/                    # Drop manually downloaded PDFs here
│       └── processed/            # Ingested originals moved here
└── reports/
```

## CLI reference

| Command | Description |
|---------|-------------|
| `litscout init` | Scaffold a new project directory with default config |
| `litscout search QUERY` | Keyword search across APIs |
| `litscout expand` | Citation graph expansion from seed papers |
| `litscout retrieve` | Full-text retrieval with fallback chain |
| `litscout ingest` | Match and ingest inbox PDFs |
| `litscout extract` | Extract clean text from PDFs/XML |
| `litscout report` | Corpus summary statistics |

Global options: `--version`, `-v`/`--verbose`, `-d`/`--project-dir PATH`.

Run `litscout <command> --help` for full option details.

## API sources

| Source | Library | What it provides |
|--------|---------|-----------------|
| Semantic Scholar | `semanticscholar` | Search, citations, references, recommendations, OA PDFs |
| PubMed / NCBI | `biopython` (Bio.Entrez) | PubMed search, MeSH terms, PMC full text via BioC |
| OpenAlex | `pyalex` | 260M+ works, citation filtering, OA status |
| Unpaywall | `httpx` (direct) | Best available OA PDF URL for any DOI |

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
