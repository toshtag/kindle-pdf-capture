"""Shared pytest fixtures for kindle_pdf_capture tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Return a temporary output directory mirroring the project layout."""
    out = tmp_path / "book"
    (out / "cropped").mkdir(parents=True)
    (out / "raw").mkdir(parents=True)
    (out / "pdf").mkdir(parents=True)
    (out / "logs").mkdir(parents=True)
    return out
