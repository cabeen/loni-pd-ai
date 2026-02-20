# LitScout: Scientific Literature Search & Retrieval Toolkit

## Design Document

**Purpose:** A Python library of composable scripts for programmatic scientific literature search, citation graph exploration, and full-text retrieval. Designed to be invoked by Claude Code or run standalone from the command line, producing reproducible, inspectable, and version-controllable search workflows.

**Primary domain:** Biomedical and life sciences research (Parkinson's disease, omics, etc.), though the architecture is domain-agnostic.

---

## 1. Design Principles

1. **Reproducibility.** Every search, expansion, and retrieval step writes its parameters and results to disk. A complete literature search can be re-executed from a single configuration file.
2. **Composability.** Each module does one thing. They communicate through a shared data format on disk. You can run them independently, swap implementations, or skip stages.
3. **Inspectability.** Raw API responses are logged. Filtering and ranking logic is explicit in code, not hidden in LLM reasoning. Intermediate outputs are human-readable.
4. **Graceful degradation.** Not every paper will have a free PDF. The system tracks what it found and what it couldn't find, so you know the gaps in your corpus.
5. **LLM-friendly outputs.** Final text extraction produces clean, structured text optimized for feeding into Claude or other LLMs for synthesis.
6. **Reuse over reinvention.** Wrap battle-tested existing libraries for API access and PDF extraction. Focus custom code on the orchestration layer—the parts no existing tool provides.

---

## 2. Build vs. Reuse Strategy

The scientific Python ecosystem has strong single-purpose libraries but no tool that combines multi-source search, citation expansion, fallback retrieval, manual ingestion, and corpus management into a unified workflow. LitScout's value is in the **orchestration layer**, not in reimplementing API clients.

**Reuse (thin adapters around existing libraries):**

| Capability | Library | Notes |
|---|---|---|
| Semantic Scholar API | [`semanticscholar`](https://github.com/danielnsilva/semanticscholar) (~393 stars) | Typed responses, pagination, async, recommendations |
| OpenAlex API | [`pyalex`](https://github.com/J535D165/pyalex) (~350 stars) | Works, Authors, cursor pagination |
| PubMed/NCBI API | [`Bio.Entrez`](https://github.com/biopython/biopython) (Biopython, ~4.5k stars) | esearch, efetch, elink; mature, 20+ year project |
| Unpaywall API | Direct `httpx` calls | API is trivial (single endpoint, email auth only) |
| PDF → LLM text | [`pymupdf4llm`](https://github.com/pymupdf/pymupdf4llm) (~1.2k stars) | PDF to clean markdown, preserves structure |
| PMC XML parsing | [`pubmed_parser`](https://github.com/titipata/pubmed_parser) (~690 stars) | Extracts sections, refs, figures from PMC XML |
| Fuzzy matching | [`rapidfuzz`](https://github.com/rapidfuzz/RapidFuzz) | Fast Levenshtein for deduplication |

**Build (novel orchestration—no existing tool does this):**

| Capability | Why it must be custom |
|---|---|
| Multi-source search with cross-API deduplication | No tool unifies S2 + PubMed + OpenAlex into a single deduplicated registry |
| Citation expansion with composite scoring | The "expand from seeds" workflow with ranking doesn't exist |
| Fallback retrieval chain with paywall detection | No tool tries S2 → Unpaywall → PMC → preprints in sequence |
| Manual retrieval workflow (list → inbox → ingest) | Entirely absent from every surveyed tool |
| Canonical paper registry with provenance tracking | No tool tracks discovery method, source, and retrieval status together |

**Closest existing tool:** [paper-qa](https://github.com/Future-House/paper-qa) (~7.8k stars) searches S2 + OpenAlex and extracts text for LLM Q&A, but is fundamentally a Q&A agent, not a corpus-building toolkit. LitScout and paper-qa are complementary—LitScout builds the corpus, paper-qa could answer questions from it.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI / Claude Code                       │
│             (invokes modules, inspects results)              │
└──────┬──────┬──────────┬──────────┬──────────┬──────────────┘
       │      │          │          │          │
  ┌────▼──┐ ┌─▼────┐ ┌───▼───┐ ┌───▼───┐ ┌────▼───┐
  │search │ │expand│ │retriev│ │ingest │ │extract │  ← CUSTOM
  └───┬───┘ └──┬───┘ └───┬───┘ └───┬───┘ └────┬───┘
      │        │         │         │           │
      │        │         │    ┌────┘           │
      ▼        ▼         ▼    ▼                ▼
  ┌───────────────────────────────────────────────────┐
  │               project data store                   │
  │  papers.jsonl + fulltext/{pdf,xml,txt,inbox} +     │
  │  manual_retrieval_list.md + retrieval_log.jsonl     │
  └──────────────┬────────────────────────────────────┘
                 │
       ┌─────────▼─────────────────┐
       │   api_clients (adapters)   │  ← THIN WRAPPERS
       │                            │
       │  semanticscholar (pypi)    │
       │  pyalex (pypi)             │
       │  Bio.Entrez (biopython)    │
       │  httpx → Unpaywall         │
       └────────────┬──────────────┘
                    │
       ┌────────────▼──────────────┐
       │   extraction libraries     │  ← REUSED
       │                            │
       │  pymupdf4llm (PDF→text)    │
       │  pubmed_parser (PMC XML)   │
       └───────────────────────────┘
```

---

## 4. Project Data Store

All modules read from and write to a single project directory. This is the source of truth for a literature search.

### 4.1 Directory Structure

```
my_project/
├── litscout.toml              # Project config: search parameters, API keys, etc.
├── searches/                  # One file per search execution
│   ├── 2025-02-19_parkinsons_alpha_synuclein.jsonl
│   └── 2025-02-20_parkinsons_gut_brain_axis.jsonl
├── papers.jsonl               # Canonical paper registry (deduplicated)
├── expansions/                # Citation graph exploration results
│   └── 2025-02-19_seed_expansion.jsonl
├── retrieval_log.jsonl        # Record of retrieval attempts and outcomes
├── fulltext/                  # Retrieved full-text files
│   ├── pdf/                   # PDFs (programmatic + manually ingested)
│   │   └── 10.1038_s41586-023-06424-7.pdf
│   ├── xml/                   # PMC BioC XML
│   │   └── PMC9876543.xml
│   ├── txt/                   # Extracted clean text (LLM-ready)
│   │   └── 10.1038_s41586-023-06424-7.txt
│   └── inbox/                 # Drop manually downloaded PDFs here
│       └── processed/         # Ingested PDFs are moved here
├── manual_retrieval_list.md   # Human-readable list of papers needing manual download
└── reports/                   # Generated summaries and syntheses
    └── synthesis_v1.md
```

### 4.2 Canonical Paper Schema (papers.jsonl)

Each line is a JSON object representing one paper. This is the single source of truth—all modules write to and read from this file. Papers are deduplicated by DOI (preferred) or Semantic Scholar paper ID.

```json
{
  "paper_id": "s2:abc123def456",
  "doi": "10.1038/s41586-023-06424-7",
  "pmid": "37654321",
  "pmcid": "PMC9876543",
  "arxiv_id": null,
  "title": "Alpha-synuclein aggregation pathways in Parkinson's disease",
  "authors": [
    {"name": "Jane Smith", "author_id": "s2:1234567"}
  ],
  "year": 2023,
  "venue": "Nature",
  "journal_name": "Nature",
  "citation_count": 142,
  "influential_citation_count": 38,
  "abstract": "Alpha-synuclein aggregation is a hallmark...",
  "tldr": "This study demonstrates that...",
  "fields_of_study": ["Medicine", "Biology"],
  "is_open_access": true,
  "open_access_pdf_url": "https://www.nature.com/articles/...",
  "source": "semantic_scholar",
  "discovery_method": "keyword_search",
  "discovery_query": "alpha-synuclein aggregation parkinson",
  "discovery_date": "2025-02-19",
  "seed_paper_id": null,
  "fulltext_status": "retrieved",
  "fulltext_pdf_path": "fulltext/pdf/10.1038_s41586-023-06424-7.pdf",
  "fulltext_xml_path": null,
  "fulltext_txt_path": "fulltext/txt/10.1038_s41586-023-06424-7.txt",
  "fulltext_source": "unpaywall",
  "needs_manual_retrieval": false,
  "tags": ["seed", "highly_cited"],
  "notes": ""
}
```

Key fields explained:

- **`paper_id`**: Prefixed identifier. `s2:` for Semantic Scholar, `pmid:` for PubMed, `oalex:` for OpenAlex.
- **`discovery_method`**: How this paper entered the corpus. One of: `keyword_search`, `citation_forward` (cited by), `citation_backward` (references), `recommendation`, `manual`.
- **`discovery_query`**: The search query or seed paper ID that led to this paper.
- **`fulltext_status`**: One of: `not_attempted`, `retrieved` (at least one format obtained), `partial` (only abstract-level text, e.g. structured text but no PDF), `failed` (all sources tried, none succeeded), `manual_pending` (flagged for manual retrieval), `manual_retrieved` (manually provided PDF ingested).
- **`fulltext_pdf_path`**: Path to PDF file, if available. May be from programmatic download or manual ingestion.
- **`fulltext_xml_path`**: Path to structured XML (BioC/PMC), if available. Typically only for PMC Open Access papers.
- **`fulltext_txt_path`**: Path to extracted clean text file (LLM-ready). Generated by `extract.py` from whichever source format is available.
- **`fulltext_source`**: Which source provided the full text: `semantic_scholar`, `unpaywall`, `pmc_bioc`, `biorxiv`, `publisher_oa`, `manual`.
- **`needs_manual_retrieval`**: Boolean. Set to `true` by `retrieve.py` when all automated sources fail. Set back to `false` after manual ingestion via `ingest.py`.
- **`tags`**: User-defined labels. Useful for marking seed papers, marking papers for inclusion/exclusion, etc.

### 4.3 Configuration File (litscout.toml)

```toml
[project]
name = "parkinsons_alpha_synuclein_review"
description = "Literature review on alpha-synuclein aggregation pathways in PD"
created = "2025-02-19"

[apis]
semantic_scholar_api_key = ""  # Optional but recommended; set via env var SEMANTIC_SCHOLAR_API_KEY
unpaywall_email = "researcher@university.edu"  # Required for Unpaywall
ncbi_api_key = ""  # Optional; set via env var NCBI_API_KEY
ncbi_email = "researcher@university.edu"  # Required for NCBI/PubMed
openalex_api_key = ""  # Optional; set via env var OPENALEX_API_KEY

[search.defaults]
year_range = [2015, 2025]
min_citation_count = 0
max_results_per_query = 100
fields_of_study = ["Medicine", "Biology"]

[retrieval]
# Ordered list of sources to try for full text
fallback_chain = ["semantic_scholar", "unpaywall", "pmc_bioc", "biorxiv"]
# Retrieve both PDFs and structured text when both are available.
# Structured text (BioC XML) is used for LLM synthesis; PDFs are archived
# for reference, figures, tables, and supplementary materials.
retrieve_both_formats = true
# Max concurrent downloads
concurrency = 5

[retrieval.manual_ingest]
# Directory where you drop manually downloaded PDFs for ingestion
inbox_dir = "fulltext/inbox/"
# After ingestion, move originals here (set to "" to delete after ingestion)
processed_dir = "fulltext/inbox/processed/"

[extraction]
# Max tokens per extracted document (for LLM context management)
max_tokens_per_doc = 8000
# Sections to prioritize when truncating
priority_sections = ["abstract", "introduction", "results", "discussion", "conclusion"]
```

---

## 5. Module Specifications

### 5.1 `api_clients/` — API Adapters

Thin adapters that wrap existing Python libraries, providing a uniform interface for LitScout's orchestration modules. Each adapter normalizes the upstream library's response into Python dicts matching our canonical schema. Rate limiting, pagination, and retry logic are delegated to the underlying libraries where possible.

#### 5.1.1 `api_clients/semantic_scholar.py`

**Wraps:** [`semanticscholar`](https://github.com/danielnsilva/semanticscholar) (pypi: `semanticscholar`)

The `semanticscholar` library already provides typed responses, paginated navigation, async support, and API key handling. Our adapter:
- Calls the library's methods and normalizes results into the canonical paper schema
- Adds any rate-limiting beyond what the library provides
- Translates library exceptions into LitScout's error types

**Key library methods we use:**

| Our function | Library method | Purpose |
|---|---|---|
| `search_papers(...)` | `sch.search_paper(query, ...)` | Relevance-ranked keyword search |
| `get_paper(...)` | `sch.get_paper(paper_id, ...)` | Single paper details (accepts DOI, PMID, ArXiv, PMCID) |
| `get_paper_citations(...)` | `sch.get_paper_citations(paper_id, ...)` | Forward citations |
| `get_paper_references(...)` | `sch.get_paper_references(paper_id, ...)` | Backward references |
| `get_recommendations(...)` | `sch.get_recommended_papers(paper_id, ...)` | Algorithmic recommendations |
| `batch_paper_details(...)` | `sch.get_papers(paper_ids, ...)` | Batch details (up to 500) |

**Key fields to request** (pass via the library's `fields` parameter):
```
paperId, externalIds, title, abstract, year, venue, journal,
citationCount, influentialCitationCount, isOpenAccess,
openAccessPdf, fieldsOfStudy, tldr, authors, references,
citations, publicationTypes
```

**Rate limiting:** The `semanticscholar` library handles basic rate limiting. Our adapter adds a configurable `RateLimiter` as an additional guard (default: 10 req/s with key, 0.8 req/s without).

**Pagination:** The library provides paginated iterators. Our adapter consumes these up to the configured `max_results`.

**Error handling:** The library raises typed exceptions. Our adapter catches these, logs them, and translates to LitScout's error types. Additional retry logic via `tenacity` for transient failures.

#### 5.1.2 `api_clients/pubmed.py`

**Wraps:** [`Bio.Entrez`](https://github.com/biopython/biopython) (pypi: `biopython`)

Biopython's `Bio.Entrez` module provides access to all NCBI E-utilities. Our adapter:
- Sets `Entrez.email` and `Entrez.api_key` from config/environment
- Calls `esearch`, `efetch`, and `elink` and normalizes results into the canonical schema
- Handles the BioC API for PMC full text via direct `httpx` calls (not covered by Biopython)

**Key library methods we use:**

| Our function | Library call | Purpose |
|---|---|---|
| `search(query, ...)` | `Entrez.esearch(db="pubmed", ...)` | PubMed keyword search; returns PMIDs |
| `fetch_abstracts(pmids)` | `Entrez.efetch(db="pubmed", ...)` | Fetch article metadata + abstracts |
| `fetch_pmc_fulltext(pmcid)` | `Entrez.efetch(db="pmc", ...)` | Fetch full-text XML from PMC OA subset |
| `get_bioc_json(pmcid)` | Direct `httpx` GET to BioC REST API | Full-text in structured BioC JSON |

**Notes:**
- PubMed search supports MeSH terms: e.g. `"Parkinson Disease"[MeSH] AND "alpha-Synuclein"[MeSH]`
- The BioC API only works for PMC Open Access subset articles
- PMID → PMCID mapping: use `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json`
- Rate limit: 3 req/s without key, 10 req/s with key. Biopython enforces this automatically when `Entrez.api_key` is set.

#### 5.1.3 `api_clients/unpaywall.py`

**Base URL:** `https://api.unpaywall.org/v2/`

**Authentication:** Email address appended as `?email=` parameter. No API key needed.

**Key endpoint:**

| Function | Endpoint | Purpose |
|----------|----------|---------|
| `get_oa_status(doi)` | `GET /{doi}?email={email}` | Returns OA status and best available PDF URL |

**Response fields of interest:**
```json
{
  "is_oa": true,
  "best_oa_location": {
    "url_for_pdf": "https://...",
    "url_for_landing_page": "https://...",
    "host_type": "repository",
    "license": "cc-by",
    "version": "publishedVersion"
  },
  "oa_locations": [...]
}
```

**Notes:**
- Only works for papers with DOIs
- Rate limit: 100,000 requests per day (more than sufficient)
- The `best_oa_location.url_for_pdf` is what you want for downloading
- If `url_for_pdf` is null but `url_for_landing_page` exists, the paper may be OA but without a direct PDF link
- Some URLs may be to preprint versions; check `version` field (`submittedVersion`, `acceptedVersion`, `publishedVersion`)

#### 5.1.4 `api_clients/openalex.py` (optional, for bibliometric analysis)

**Wraps:** [`pyalex`](https://github.com/J535D165/pyalex) (pypi: `pyalex`)

The `pyalex` library provides a Pythonic interface to OpenAlex's REST API with offset and cursor pagination. Our adapter:
- Calls the library's `Works` entity and normalizes results into the canonical schema
- Reconstructs abstracts from OpenAlex's inverted index format (utility in `utils/identifiers.py`)
- Handles the upcoming API key requirement (required as of Feb 2026)

**Key library methods we use:**

| Our function | Library call | Purpose |
|---|---|---|
| `search_works(query, ...)` | `Works().search(query).filter(...)` | Full-text search across 260M+ works |
| `get_work(id_or_doi)` | `Works()[id]` | Single work details |
| `get_cited_by(work_id)` | `Works().filter(cites=id)` | Works that cite a given work |
| `get_related_works(work_id)` | Via `related_works` field on work object | Algorithmically related works |

**Useful filters** (passed via `pyalex`'s `.filter()` method):
```
publication_year:2020-2025
is_oa:true
has_fulltext:true
type:article
cited_by_count:>50
```

**Notes:**
- OpenAlex includes Unpaywall OA data natively in the `open_access` field
- Abstracts are "inverted index" format; our `reconstruct_abstract()` utility handles conversion
- Rate limit: 100,000 credits/day with free key. `pyalex` handles pagination automatically.

---

### 5.2 `search.py` — Discovery Module

**Purpose:** Execute keyword searches against one or more APIs, deduplicate results, and append new papers to `papers.jsonl`.

**CLI interface:**
```bash
# Basic keyword search
python -m litscout.search "alpha-synuclein aggregation parkinson" \
    --sources semantic_scholar,pubmed \
    --year-range 2015 2025 \
    --min-citations 10 \
    --max-results 200 \
    --tag seed_search

# Search with MeSH terms (PubMed only)
python -m litscout.search \
    --pubmed-query '"Parkinson Disease"[MeSH] AND "alpha-Synuclein"[MeSH] AND "Disease Models, Animal"[MeSH]' \
    --year-range 2020 2025 \
    --tag mesh_search
```

**Logic:**

1. Parse arguments and load config from `litscout.toml`
2. For each source:
   - Call the appropriate API client
   - Paginate through all results up to `max_results`
   - Normalize results into the canonical paper schema
3. Merge results across sources:
   - Deduplicate by DOI (primary), then by title similarity (fuzzy match, Levenshtein ratio > 0.9) for papers without DOIs
   - When merging duplicates, prefer the record with more metadata (e.g., keep the one with a PMCID if one has it and the other doesn't)
4. Append new papers to `papers.jsonl` (skip papers already present by DOI/paper_id)
5. Write a search log file to `searches/` with: timestamp, query parameters, source, number of results, number of new papers added

**Normalization mapping** (Semantic Scholar → canonical schema):

| S2 field | Canonical field |
|----------|----------------|
| `paperId` | `paper_id` (prefixed as `s2:{id}`) |
| `externalIds.DOI` | `doi` |
| `externalIds.PubMed` | `pmid` |
| `externalIds.PubMedCentral` | `pmcid` |
| `externalIds.ArXiv` | `arxiv_id` |
| `title` | `title` |
| `abstract` | `abstract` |
| `year` | `year` |
| `venue` | `venue` |
| `journal.name` | `journal_name` |
| `citationCount` | `citation_count` |
| `influentialCitationCount` | `influential_citation_count` |
| `isOpenAccess` | `is_open_access` |
| `openAccessPdf.url` | `open_access_pdf_url` |
| `fieldsOfStudy` | `fields_of_study` |
| `tldr.text` | `tldr` |
| `authors` | `authors` (map `authorId` → `author_id`, `name` → `name`) |

A similar mapping table should be built for PubMed XML → canonical schema and OpenAlex JSON → canonical schema.

---

### 5.3 `expand.py` — Citation Graph Exploration

**Purpose:** Take a set of seed papers and explore their citation neighborhoods to discover related work. This automates the "cited by" and "related papers" browsing pattern.

**CLI interface:**
```bash
# Expand from all papers tagged "seed"
python -m litscout.expand --seed-tag seed --depth 1 --strategy both \
    --min-citations 5 --max-candidates 500

# Expand from specific papers
python -m litscout.expand --seed-dois "10.1038/xxx,10.1016/yyy" \
    --strategy forward --max-candidates 200

# Use Semantic Scholar recommendations
python -m litscout.expand --seed-tag seed --strategy recommend \
    --max-candidates 100
```

**Strategies:**

| Strategy | Method | Description |
|----------|--------|-------------|
| `forward` | `get_paper_citations()` | Papers that cite the seeds (newer work building on the seeds) |
| `backward` | `get_paper_references()` | Papers the seeds cite (foundational work) |
| `both` | Both of the above | Full neighborhood |
| `recommend` | `get_recommendations_multi()` | S2 algorithmic recommendations using seeds as positive examples |
| `all` | All three | Maximum discovery |

**Logic:**

1. Load seed papers from `papers.jsonl` (filtered by tag or explicit IDs)
2. For each seed, fetch citations and/or references via the chosen strategy
3. Aggregate all discovered papers, counting how many seeds each candidate is connected to
4. Rank candidates by a composite score:
   ```
   score = (citation_count_normalized * 0.3) +
           (seed_connections * 0.4) +
           (recency_score * 0.2) +
           (influential_citation_ratio * 0.1)
   ```
   Where:
   - `citation_count_normalized`: log(citation_count + 1) / max_log_citations in the candidate set
   - `seed_connections`: number of seed papers this candidate is connected to / total seed papers
   - `recency_score`: (year - min_year) / (max_year - min_year)
   - `influential_citation_ratio`: influential_citation_count / (citation_count + 1)
5. Deduplicate against existing papers in `papers.jsonl`
6. Append new candidates with `discovery_method` set to `citation_forward`, `citation_backward`, or `recommendation`
7. Write expansion log to `expansions/`

**Depth parameter:** If `depth > 1`, run iteratively: after the first expansion, take the top N newly discovered papers and expand from them. Use with caution—depth 2 can produce thousands of candidates. Default to depth 1.

---

### 5.4 `retrieve.py` — Full-Text Retrieval

**Purpose:** For each paper in `papers.jsonl` where `fulltext_status == "not_attempted"`, attempt to retrieve the full text through a configurable fallback chain. Retrieves both PDF and structured text formats when available. After running, generates a manual retrieval list for papers that couldn't be obtained programmatically.

**CLI interface:**
```bash
# Retrieve full text for all unretrieved papers
python -m litscout.retrieve

# Retrieve only for papers with a specific tag
python -m litscout.retrieve --tag seed

# Retry previously failed papers
python -m litscout.retrieve --retry-failed

# Retry papers flagged for manual retrieval (e.g., after gaining institutional access)
python -m litscout.retrieve --retry-manual-pending

# Dry run: show what would be attempted without downloading
python -m litscout.retrieve --dry-run

# Regenerate the manual retrieval list without re-running downloads
python -m litscout.retrieve --update-manual-list
```

**Retrieval logic per paper:**

The module attempts to get both a PDF and structured text independently, not just one or the other. The fallback chain determines the order of sources tried for each format.

```
For each paper:

  PDF retrieval (try in order, stop at first success):
    1. Semantic Scholar openAccessPdf URL → download PDF
    2. Unpaywall best_oa_location.url_for_pdf → download PDF
    3. bioRxiv/medRxiv direct URL (if DOI matches 10.1101/*) → download PDF
    4. arXiv direct URL (if arxiv_id exists) → download PDF

  Structured text retrieval (try in order, stop at first success):
    1. PMC BioC API (if PMCID exists or can be mapped from PMID) → save XML/JSON
    2. PubMed efetch full-text XML from PMC (if PMCID exists) → save XML

  Update paper record:
    - If at least one format retrieved → fulltext_status = "retrieved"
    - If nothing retrieved → fulltext_status = "failed", needs_manual_retrieval = true
```

**For each paper, the module should:**

1. Try PDF sources and structured text sources as described above
2. Save retrieved files to the appropriate subdirectories (`fulltext/pdf/`, `fulltext/xml/`)
3. Update `papers.jsonl`: set `fulltext_status`, `fulltext_pdf_path`, `fulltext_xml_path`, `fulltext_source`, `needs_manual_retrieval`
4. Log each attempt (success or failure with reason) to `retrieval_log.jsonl`
5. After all papers are processed, generate `manual_retrieval_list.md`

**Manual retrieval list generation:**

After a retrieval run completes, the module writes `manual_retrieval_list.md` at the project root. This is a human-readable document designed to make manual PDF retrieval as frictionless as possible.

Format:
```markdown
# Papers Needing Manual Retrieval

Generated: 2025-02-19T15:30:00Z
Total: 23 papers

## How to add papers

1. Download the PDF from the link below (use institutional access, interlibrary loan, etc.)
2. Name the file using the filename shown below (or any name — the ingest tool will match by content)
3. Drop it into: `fulltext/inbox/`
4. Run: `python -m litscout.ingest`

---

### 1. Alpha-synuclein strains and their relevance to Parkinson's disease (2022)
- **Authors:** Smith J, Doe A, et al.
- **Venue:** Annual Review of Neuroscience
- **DOI:** 10.1146/annurev-neuro-012345-678910
- **Citations:** 89
- **Publisher link:** https://doi.org/10.1146/annurev-neuro-012345-678910
- **Why it matters:** Discovered via citation_forward from 3 seed papers
- **Suggested filename:** `10.1146_annurev-neuro-012345-678910.pdf`

### 2. ...
```

Papers are sorted by a priority heuristic: seed papers first, then by number of seed connections, then by citation count. This way the most important missing papers are at the top.

**Download implementation notes:**
- Use `httpx` (async) or `requests` for HTTP downloads
- Follow redirects (publishers often redirect from DOI URLs)
- Verify content type: check that the response is actually `application/pdf` or XML, not an HTML paywall page
- Set a reasonable User-Agent header identifying your tool and contact email
- Implement concurrent downloads (configurable, default 5) with per-domain rate limiting
- Timeout: 30 seconds per download attempt

**Retrieval log entry schema:**
```json
{
  "doi": "10.1038/...",
  "paper_id": "s2:abc123",
  "timestamp": "2025-02-19T14:30:00Z",
  "format_attempted": "pdf",
  "source_attempted": "unpaywall",
  "url_attempted": "https://...",
  "status": "success",
  "file_path": "fulltext/pdf/10.1038_xxx.pdf",
  "file_size_bytes": 1234567,
  "content_type": "application/pdf",
  "error": null
}
```

Multiple entries may exist per paper (one per format × source attempt).

---

### 5.5 `ingest.py` — Manual PDF Ingestion

**Purpose:** Match manually downloaded PDFs in the inbox directory to papers in `papers.jsonl`, move them into the correct location, and trigger text extraction. This closes the loop for paywalled papers.

**CLI interface:**
```bash
# Ingest all PDFs in the inbox
python -m litscout.ingest

# Ingest and immediately extract text
python -m litscout.ingest --extract

# Preview what would be matched without moving files
python -m litscout.ingest --dry-run
```

**Matching strategy:**

The module needs to figure out which paper in `papers.jsonl` each inbox PDF belongs to. It tries these approaches in order:

1. **Filename match.** If the filename matches the suggested filename format from the manual retrieval list (i.e., a sanitized DOI like `10.1038_s41586-023-06424-7.pdf`), match directly.
2. **DOI in filename.** If the filename contains a recognizable DOI pattern (e.g., `nature_10.1038_s41586-023-06424-7_download.pdf`), extract and match.
3. **PDF metadata match.** Extract the PDF title from document metadata (`/Title` field) and fuzzy-match against paper titles in `papers.jsonl` (Levenshtein ratio > 0.85).
4. **First-page text match.** Extract text from the first page of the PDF and search for exact title substring matches against papers with `needs_manual_retrieval == true`.
5. **Ambiguous or no match.** If no confident match is found, report the unmatched file and skip it. Do not guess.

**Logic:**

1. Scan `fulltext/inbox/` for PDF files
2. For each PDF, attempt matching using the strategy above
3. On successful match:
   - Copy the PDF to `fulltext/pdf/{sanitized_doi_or_id}.pdf`
   - Update `papers.jsonl`:
     - `fulltext_pdf_path` → new path
     - `fulltext_status` → `"manual_retrieved"`
     - `fulltext_source` → `"manual"`
     - `needs_manual_retrieval` → `false`
   - Move the original file to `fulltext/inbox/processed/`
   - Log the ingestion to `retrieval_log.jsonl`
4. If `--extract` is passed, run `extract.py` on the newly ingested papers
5. Regenerate `manual_retrieval_list.md` (removing ingested papers)
6. Print a summary: N files ingested, M files unmatched, K papers still needing manual retrieval

**Console output example:**
```
Scanning inbox: 5 PDFs found

✓ 10.1146_annurev-neuro-012345-678910.pdf → matched by filename
  → Alpha-synuclein strains and their relevance to Parkinson's disease (2022)

✓ nature_article_download.pdf → matched by first-page title
  → Gut microbiome signatures in early Parkinson's disease (2024)

✗ paper_v2_final_FINAL.pdf → no confident match found
  Closest candidate (score 0.72): "Mitochondrial dysfunction in PD models" — skipped

Summary: 2 ingested, 1 unmatched, 21 papers still need manual retrieval
```

---

### 5.6 `extract.py` — Text Extraction & Preparation

**Purpose:** Convert retrieved PDFs and XMLs into clean, structured plain text suitable for LLM consumption. When both formats are available for a paper, prefers structured XML for text extraction (better section boundaries, cleaner text) but both remain available on disk.

**CLI interface:**
```bash
# Extract all retrieved papers that haven't been extracted yet
python -m litscout.extract

# Re-extract a specific paper
python -m litscout.extract --doi "10.1038/xxx"

# Extract with a custom token limit
python -m litscout.extract --max-tokens 12000

# Extract only recently ingested manual papers
python -m litscout.extract --status manual_retrieved
```

**Source selection per paper:**

When a paper has both `fulltext_xml_path` and `fulltext_pdf_path`, the module prefers XML because it provides explicitly labeled sections. When only a PDF is available (common for manually ingested paywalled papers), it falls back to PDF extraction.

```
if fulltext_xml_path exists → extract from XML (highest quality)
elif fulltext_pdf_path exists → extract from PDF
else → skip (no full text available)
```

**Extraction strategies by source format (using existing libraries):**

| Format | Library | Strategy |
|--------|---------|----------|
| PMC BioC XML/JSON | [`pubmed_parser`](https://github.com/titipata/pubmed_parser) | Parse structured sections directly. This is the highest quality source—sections (Abstract, Introduction, Methods, Results, Discussion) are explicitly labeled. `pubmed_parser` extracts paragraphs, references, and figure captions from PMC XML. |
| PDF | [`pymupdf4llm`](https://github.com/pymupdf/pymupdf4llm) | Converts PDF to clean markdown with preserved document hierarchy (headers, lists, tables). Purpose-built for LLM consumption. For scanned PDFs, supports OCR fallback. |
| arXiv PDF | `pymupdf4llm` | Same as PDF. LaTeX artifacts may be present in some cases; post-process to strip common residue. |

**Output format** (saved to `fulltext/txt/{sanitized_doi_or_id}.txt`):

```
TITLE: Alpha-synuclein aggregation pathways in Parkinson's disease
AUTHORS: Jane Smith, John Doe
YEAR: 2023
DOI: 10.1038/s41586-023-06424-7
SOURCE: Nature

--- ABSTRACT ---
Alpha-synuclein aggregation is a hallmark...

--- INTRODUCTION ---
Parkinson's disease (PD) affects approximately...

--- RESULTS ---
We found that...

--- DISCUSSION ---
Our findings suggest...

--- REFERENCES ---
[omitted for brevity; include count only]
Total references: 87
```

**Processing logic:**

1. Select source format as described above
2. For BioC XML/JSON: use `pubmed_parser` to extract sections by their type labels, output in order
3. For PDFs: use `pymupdf4llm` to convert to markdown (preserves headers and structure), then reformat into the LitScout text output format
4. Apply token-aware truncation if the extracted text exceeds `max_tokens_per_doc`:
   - Always keep: title, authors, abstract
   - Prioritize sections from `priority_sections` config
   - Truncate methods section first (usually the least useful for synthesis)
   - Add a note: `[TRUNCATED: full text is {N} tokens, showing {M} tokens from priority sections]`
5. Update `papers.jsonl`: set `fulltext_txt_path` to the `.txt` file

---

### 5.7 `report.py` — Corpus Summary & Statistics

**Purpose:** Generate a human-readable summary of the current state of the literature corpus. Useful for inspecting what you have before feeding papers to Claude for synthesis.

**CLI interface:**
```bash
python -m litscout.report
python -m litscout.report --format markdown
python -m litscout.report --format json
```

**Output includes:**

- Total papers in corpus, broken down by discovery method
- Retrieval statistics:
  - Papers with full text (PDF, structured text, or both), by source
  - Papers with extracted LLM-ready text
  - Papers awaiting manual retrieval (count + top 5 by priority)
  - Papers where only abstract is available
- Year distribution histogram (text-based)
- Top venues by paper count
- Top cited papers (top 20)
- Most recent papers (top 20)
- Tag distribution
- Papers with failed retrieval (for manual follow-up)
- Citation network summary: average citations per paper, most connected papers

---

## 6. Shared Utilities

### 6.1 `utils/rate_limiter.py`

A token-bucket rate limiter that supports per-API-source limits:

```python
class RateLimiter:
    def __init__(self, requests_per_second: float):
        ...

    async def acquire(self):
        """Block until a request can be made."""
        ...
```

Default rates:
- Semantic Scholar (with key): 10 req/s (conservative, below the 100 req/s limit)
- Semantic Scholar (without key): 0.8 req/s
- PubMed (with key): 8 req/s
- PubMed (without key): 2 req/s
- Unpaywall: 10 req/s
- OpenAlex: 10 req/s

### 6.2 `utils/dedup.py`

Deduplication logic:

1. Exact DOI match (case-insensitive, strip URL prefix if present)
2. Exact PMID match
3. Fuzzy title match (normalize whitespace, lowercase, strip punctuation, then Levenshtein ratio > 0.92 AND same year)

### 6.3 `utils/identifiers.py`

- `normalize_doi(doi)` → strip URL prefixes, lowercase
- `pmid_to_pmcid(pmid)` → call NCBI ID converter API
- `doi_to_s2_id(doi)` → query Semantic Scholar paper endpoint via `semanticscholar` library
- `sanitize_for_filename(identifier)` → replace `/` with `_`, strip unsafe chars
- `reconstruct_abstract(inverted_index)` → convert OpenAlex inverted-index abstract to plain text

### 6.4 `utils/io.py`

- `append_papers(papers, filepath)` → append to JSONL, handle dedup
- `load_papers(filepath, filters)` → load from JSONL with optional filtering by tags, status, etc.
- `update_paper(filepath, paper_id, updates)` → update specific fields of a paper in-place
- `scan_inbox(inbox_dir)` → list PDF files in the inbox directory with file metadata (name, size, modification time)
- `generate_manual_list(papers_filepath, output_filepath)` → write the prioritized manual retrieval markdown file from current paper data

---

## 7. Dependencies

```
# Core
httpx>=0.27          # Async HTTP client (for Unpaywall, BioC, and direct downloads)
pydantic>=2.0        # Data validation for paper schema
click>=8.0           # CLI interface
tomli>=2.0           # TOML config parsing (or tomllib in Python 3.11+)

# API client libraries (reused, not reimplemented)
semanticscholar>=0.8 # Semantic Scholar API wrapper (search, citations, recommendations)
pyalex>=0.14         # OpenAlex API wrapper (works, authors, cursor pagination)
biopython>=1.84      # Bio.Entrez for PubMed/NCBI E-utilities

# Text extraction (reused, not reimplemented)
pymupdf4llm>=0.0.17  # PDF → clean markdown optimized for LLM consumption
pubmed_parser>=0.4   # PMC XML structured section extraction

# Utilities
rapidfuzz>=3.0       # Fast fuzzy string matching for dedup
tqdm>=4.66           # Progress bars for batch operations
tenacity>=8.0        # Retry logic with backoff

# Optional
tiktoken>=0.7        # Token counting for truncation (uses OpenAI's tokenizer as a proxy; close enough for Claude)
```

---

## 8. Usage Patterns with Claude Code

### Pattern 1: Initial literature survey

Tell Claude Code:
> "I'm starting a project on alpha-synuclein aggregation pathways in Parkinson's disease.
> Run a search using LitScout, then expand from the top 10 most-cited results.
> Retrieve full text where available. Then read through the extracted texts and
> give me a synthesis of the current state of the field, identifying the major
> open questions and contradictions in the literature."

Claude Code would:
1. Run `search.py` with appropriate queries
2. Review results, tag the most relevant as seeds
3. Run `expand.py` from those seeds
4. Run `retrieve.py` to get full text
5. Run `extract.py` to prepare clean text
6. Read the extracted texts and produce a synthesis

Each step produces artifacts on disk that you can inspect, modify, or re-run.

### Pattern 2: Targeted gap analysis

> "I have a hypothesis that gut microbiome composition influences alpha-synuclein
> aggregation in PD. Search for papers at this intersection. Tell me what's been
> studied, what evidence exists, and where the gaps are relative to my hypothesis."

### Pattern 3: Manual retrieval loop

After running the pipeline, `manual_retrieval_list.md` shows 23 papers behind paywalls. You:
1. Open the list, use your institutional access to download the top-priority PDFs
2. Drop them into `fulltext/inbox/` (using the suggested filenames or not—the ingester handles both)
3. Run `python -m litscout.ingest --extract`
4. The ingester matches files to papers, moves them into place, extracts text
5. Tell Claude Code: "I've added 15 new papers. Read the newly extracted texts and update the synthesis."

This loop can be repeated as many times as needed. The manual retrieval list automatically updates to show only the remaining gaps.

### Pattern 4: Updating an existing review

> "It's been 3 months since my last search. Run the same queries from the
> config file but limit to papers published since 2025-01-01. Show me what's new
> and whether any of it changes the synthesis we developed."

---

## 9. Implementation Notes & Caveats

### What this system will NOT get you

- **Paywalled papers without OA versions.** No legal programmatic approach can bypass this. The system identifies these papers, flags them with `needs_manual_retrieval`, and generates a prioritized `manual_retrieval_list.md` with direct publisher links and suggested filenames. You retrieve these through institutional access, interlibrary loan, or other means, drop the PDFs into `fulltext/inbox/`, and run `python -m litscout.ingest` to integrate them. The design goal is that the manual step takes as little effort as possible per paper.
- **Perfect recall.** No single search API covers everything. Using both Semantic Scholar and PubMed helps, but niche papers may only appear in domain-specific databases.
- **Guaranteed PDF quality.** Some OA PDFs are scanned images, watermarked proofs, or preprint versions that differ from the final publication. The extraction module should flag likely issues (very short extracted text, possible scan artifacts).

### API key management

- Never commit API keys to version control
- Store in environment variables: `SEMANTIC_SCHOLAR_API_KEY`, `NCBI_API_KEY`, `OPENALEX_API_KEY`
- The `litscout.toml` file can reference env vars or contain empty strings (which signals "use env var")
- Unpaywall only needs an email, not a key

### Content type verification for downloads

This is critical for both PDF and XML retrieval. Many publisher URLs that look like they should return a PDF actually return an HTML paywall page. The retrieve module must:
1. Check the `Content-Type` response header
2. For PDFs, verify the file starts with `%PDF`
3. For XML, verify the file parses as valid XML
4. If HTML is received instead, log this as a paywall hit and mark retrieval as `failed_paywall`
5. Do not count a paywall page as a successful retrieval under either format

### Respect for terms of service

- All APIs used here explicitly allow programmatic access
- PMC bulk retrieval must use their designated services (E-Utilities, BioC, FTP, OAI-PMH)
- bioRxiv full-text TDM is explicitly consented to by authors during submission
- Unpaywall only returns legal OA copies
- Do not scrape publisher websites directly; only use their APIs and OA repositories

### Semantic Scholar TLDR availability

The `tldr` field is AI-generated and not available for all papers. When it is available, it's a useful quick summary. When absent, fall back to the abstract for triage.

---

## 10. Future Extensions

These are out of scope for v1 but worth noting as natural extensions:

- **Zotero integration:** Export the paper registry to Zotero for reference management, or import from an existing Zotero library as seed papers.
- **Embeddings-based clustering:** Use paper embeddings (Semantic Scholar provides SPECTER2 embeddings via their API) to cluster the corpus into subtopics and visualize the landscape.
- **Automated quality assessment:** Use Claude to score each paper's methodological rigor based on the extracted text, producing a quality column in the paper registry.
- **Watchlist mode:** Periodically re-run searches and alert when new papers matching criteria are published.
- **OpenAlex bibliometric dashboards:** Use OpenAlex's grouping and counting features to generate publication trend charts for the research area.
