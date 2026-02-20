"""Configuration loading for LitScout — reads litscout.toml + env var overlays."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ApiConfig:
    semantic_scholar_api_key: str = ""
    unpaywall_email: str = ""
    ncbi_api_key: str = ""
    ncbi_email: str = ""
    openalex_api_key: str = ""


@dataclass
class SearchDefaults:
    year_range: list[int] = field(default_factory=lambda: [2015, 2025])
    min_citation_count: int = 0
    max_results_per_query: int = 100
    fields_of_study: list[str] = field(default_factory=lambda: ["Medicine", "Biology"])


@dataclass
class RetrievalConfig:
    fallback_chain: list[str] = field(
        default_factory=lambda: ["semantic_scholar", "unpaywall", "pmc_bioc", "biorxiv"]
    )
    retrieve_both_formats: bool = True
    concurrency: int = 5
    inbox_dir: str = "fulltext/inbox/"
    processed_dir: str = "fulltext/inbox/processed/"


@dataclass
class ExtractionConfig:
    max_tokens_per_doc: int = 8000
    priority_sections: list[str] = field(
        default_factory=lambda: ["abstract", "introduction", "results", "discussion", "conclusion"]
    )


@dataclass
class ProjectConfig:
    name: str = ""
    description: str = ""
    created: str = ""


@dataclass
class Config:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    apis: ApiConfig = field(default_factory=ApiConfig)
    search: SearchDefaults = field(default_factory=SearchDefaults)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    project_dir: Path = field(default_factory=lambda: Path.cwd())


# Env var → ApiConfig field mapping
_ENV_OVERRIDES = {
    "SEMANTIC_SCHOLAR_API_KEY": "semantic_scholar_api_key",
    "UNPAYWALL_EMAIL": "unpaywall_email",
    "NCBI_API_KEY": "ncbi_api_key",
    "NCBI_EMAIL": "ncbi_email",
    "OPENALEX_API_KEY": "openalex_api_key",
}


def load_config(project_dir: Path | None = None) -> Config:
    """Load config from litscout.toml in *project_dir*, overlaying env vars for API keys."""
    project_dir = Path(project_dir) if project_dir else Path.cwd()
    config = Config(project_dir=project_dir)

    toml_path = project_dir / "litscout.toml"
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        # Project section
        if "project" in data:
            for k, v in data["project"].items():
                if hasattr(config.project, k):
                    setattr(config.project, k, v)

        # APIs section
        if "apis" in data:
            for k, v in data["apis"].items():
                if hasattr(config.apis, k):
                    setattr(config.apis, k, v)

        # Search defaults
        if "search" in data and "defaults" in data["search"]:
            for k, v in data["search"]["defaults"].items():
                if hasattr(config.search, k):
                    setattr(config.search, k, v)

        # Retrieval section
        if "retrieval" in data:
            for k, v in data["retrieval"].items():
                if k == "manual_ingest":
                    if "inbox_dir" in v:
                        config.retrieval.inbox_dir = v["inbox_dir"]
                    if "processed_dir" in v:
                        config.retrieval.processed_dir = v["processed_dir"]
                elif hasattr(config.retrieval, k):
                    setattr(config.retrieval, k, v)

        # Extraction section
        if "extraction" in data:
            for k, v in data["extraction"].items():
                if hasattr(config.extraction, k):
                    setattr(config.extraction, k, v)

    # Env var overlays for API keys (override empty or missing toml values)
    for env_var, field_name in _ENV_OVERRIDES.items():
        env_val = os.environ.get(env_var, "")
        if env_val:
            setattr(config.apis, field_name, env_val)

    return config


def generate_default_toml() -> str:
    """Return the contents of a default litscout.toml template."""
    return '''\
[project]
name = ""
description = ""
created = ""

[apis]
semantic_scholar_api_key = ""  # Or set SEMANTIC_SCHOLAR_API_KEY env var
unpaywall_email = ""           # Required for Unpaywall
ncbi_api_key = ""              # Or set NCBI_API_KEY env var
ncbi_email = ""                # Required for PubMed
openalex_api_key = ""          # Or set OPENALEX_API_KEY env var

[search.defaults]
year_range = [2015, 2025]
min_citation_count = 0
max_results_per_query = 100
fields_of_study = ["Medicine", "Biology"]

[retrieval]
fallback_chain = ["semantic_scholar", "unpaywall", "pmc_bioc", "biorxiv"]
retrieve_both_formats = true
concurrency = 5

[retrieval.manual_ingest]
inbox_dir = "fulltext/inbox/"
processed_dir = "fulltext/inbox/processed/"

[extraction]
max_tokens_per_doc = 8000
priority_sections = ["abstract", "introduction", "results", "discussion", "conclusion"]
'''
