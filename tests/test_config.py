"""Tests for litscout.config."""

import os
from pathlib import Path

from litscout.config import Config, generate_default_toml, load_config


def test_default_config():
    config = Config()
    assert config.apis.semantic_scholar_api_key == ""
    assert config.search.year_range == [2015, 2025]
    assert config.search.max_results_per_query == 100
    assert config.retrieval.concurrency == 5


def test_load_config_no_toml(tmp_path: Path):
    config = load_config(tmp_path)
    assert config.project_dir == tmp_path
    assert config.apis.semantic_scholar_api_key == ""


def test_load_config_with_toml(tmp_path: Path):
    toml_content = '''\
[project]
name = "test_project"

[apis]
unpaywall_email = "test@example.com"

[search.defaults]
max_results_per_query = 50
year_range = [2020, 2025]
'''
    (tmp_path / "litscout.toml").write_text(toml_content)
    config = load_config(tmp_path)
    assert config.project.name == "test_project"
    assert config.apis.unpaywall_email == "test@example.com"
    assert config.search.max_results_per_query == 50
    assert config.search.year_range == [2020, 2025]


def test_env_var_overlay(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-key-123")
    config = load_config(tmp_path)
    assert config.apis.semantic_scholar_api_key == "test-key-123"


def test_generate_default_toml():
    toml = generate_default_toml()
    assert "[project]" in toml
    assert "[apis]" in toml
    assert "unpaywall_email" in toml
