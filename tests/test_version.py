"""Smoke test: verify the package is importable and version is set."""

import kindle_pdf_capture


def test_version_is_string() -> None:
    assert isinstance(kindle_pdf_capture.__version__, str)


def test_version_is_not_empty() -> None:
    assert kindle_pdf_capture.__version__ != ""
