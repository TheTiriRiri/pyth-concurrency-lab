"""Shared pytest fixtures."""
from pathlib import Path

import pytest


@pytest.fixture
def tmp_csv(tmp_path: Path) -> Path:
    """A temporary CSV path that does not exist yet."""
    return tmp_path / "metrics.csv"
