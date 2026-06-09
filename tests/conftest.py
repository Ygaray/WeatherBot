"""Shared pytest fixtures: a tmp SQLite path and a recorded-fixture loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """Read and parse a recorded OpenWeather JSON fixture by file name."""
    path = FIXTURE_DIR / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def load_fixture():
    """Return the recorded-fixture loader (call it with a fixture file name)."""
    return _load_fixture


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a fresh (not-yet-created) SQLite file under tmp_path.

    The store layer (Plan 02) creates the schema on first connect; tests get an
    isolated database per test with no cross-test state.
    """
    return tmp_path / "weatherbot.db"
