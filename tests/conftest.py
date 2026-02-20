"""Shared test fixtures for LitScout."""

import pytest
from pathlib import Path


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with standard structure."""
    (tmp_path / "fulltext" / "pdf").mkdir(parents=True)
    (tmp_path / "fulltext" / "xml").mkdir(parents=True)
    (tmp_path / "fulltext" / "txt").mkdir(parents=True)
    (tmp_path / "fulltext" / "inbox" / "processed").mkdir(parents=True)
    (tmp_path / "searches").mkdir()
    (tmp_path / "expansions").mkdir()
    (tmp_path / "reports").mkdir()
    return tmp_path
