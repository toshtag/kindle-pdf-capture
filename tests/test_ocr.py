"""Tests for the OCR wrapper module.

All tests patch kindle_pdf_capture.ocr._ocrmypdf so they do not require
ocrmypdf or tesseract to be installed on the CI runner.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from kindle_pdf_capture.ocr import OcrResult, OcrStatus, run_ocr, validate_ocr_lang

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

# A minimal stand-in for ocrmypdf.ExitCode so tests don't need the real package.


class _ExitCode:
    ok = MagicMock(name="ExitCode.ok")
    ok.__int__ = lambda self: 0
    input_file = MagicMock(name="ExitCode.input_file")
    input_file.__int__ = lambda self: 2
    input_file.name = "input_file"


def _mock_ocrmypdf(exit_code=None, raises=None):
    """Return a MagicMock that stands in for the ocrmypdf module."""
    mod = MagicMock()
    mod.ExitCode = _ExitCode
    if raises is not None:
        mod.ocr.side_effect = raises
    else:
        mock_ec = MagicMock()
        mock_ec.__int__ = lambda self: 0 if exit_code == "ok" else 2
        mock_ec.__eq__ = lambda self, other: exit_code == "ok" and other is _ExitCode.ok
        mock_ec.name = "ok" if exit_code == "ok" else "input_file"
        mod.ocr.return_value = mock_ec
    return mod


# ---------------------------------------------------------------------------
# OcrResult / OcrStatus
# ---------------------------------------------------------------------------


class TestOcrResult:
    def test_fields(self) -> None:
        r = OcrResult(status=OcrStatus.SUCCESS, output=Path("out.pdf"), returncode=0)
        assert r.status == OcrStatus.SUCCESS
        assert r.output == Path("out.pdf")
        assert r.returncode == 0

    def test_succeeded_property(self) -> None:
        ok = OcrResult(status=OcrStatus.SUCCESS, output=Path("a.pdf"), returncode=0)
        fail = OcrResult(status=OcrStatus.FAILED, output=Path("a.pdf"), returncode=1)
        skip = OcrResult(status=OcrStatus.SKIPPED, output=Path("a.pdf"), returncode=0)
        assert ok.succeeded is True
        assert fail.succeeded is False
        assert skip.succeeded is False


# ---------------------------------------------------------------------------
# run_ocr: success path
# ---------------------------------------------------------------------------


class TestRunOcrSuccess:
    def test_returns_success_on_exit_code_ok(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("kindle_pdf_capture.ocr._ocrmypdf", _mock_ocrmypdf("ok")):
            result = run_ocr(src, dst)

        assert result.status == OcrStatus.SUCCESS
        assert result.returncode == 0

    def test_output_path_is_dst(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("kindle_pdf_capture.ocr._ocrmypdf", _mock_ocrmypdf("ok")):
            result = run_ocr(src, dst)

        assert result.output == dst

    def test_ocr_called_with_correct_args(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        mock_mod = _mock_ocrmypdf("ok")
        with patch("kindle_pdf_capture.ocr._ocrmypdf", mock_mod):
            run_ocr(src, dst, lang="jpn+eng", optimize=2)

        mock_mod.ocr.assert_called_once()
        kwargs = mock_mod.ocr.call_args.kwargs
        assert kwargs["language"] == ["jpn", "eng"]
        assert kwargs["optimize"] == 2
        assert kwargs["skip_text"] is True
        assert kwargs["progress_bar"] is True

    def test_lang_parameter_passed(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        mock_mod = _mock_ocrmypdf("ok")
        with patch("kindle_pdf_capture.ocr._ocrmypdf", mock_mod):
            run_ocr(src, dst, lang="eng")

        kwargs = mock_mod.ocr.call_args.kwargs
        assert kwargs["language"] == ["eng"]


# ---------------------------------------------------------------------------
# run_ocr: failure path (must not raise)
# ---------------------------------------------------------------------------


class TestRunOcrFailure:
    def test_returns_failed_on_nonzero_exit_code(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("kindle_pdf_capture.ocr._ocrmypdf", _mock_ocrmypdf("fail")):
            result = run_ocr(src, dst)

        assert result.status == OcrStatus.FAILED
        assert result.succeeded is False

    def test_does_not_raise_on_ocr_exception(self, tmp_path: Path) -> None:
        """Even if ocrmypdf.ocr raises, run_ocr must return a result, not propagate."""
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch(
            "kindle_pdf_capture.ocr._ocrmypdf", _mock_ocrmypdf(raises=RuntimeError("internal"))
        ):
            result = run_ocr(src, dst)

        assert result.status == OcrStatus.FAILED
        assert result.succeeded is False

    def test_returns_failed_when_ocrmypdf_not_installed(self, tmp_path: Path) -> None:
        """When _ocrmypdf is None (package not installed), run_ocr returns FAILED."""
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("kindle_pdf_capture.ocr._ocrmypdf", None):
            result = run_ocr(src, dst)

        assert result.status == OcrStatus.FAILED
        assert result.succeeded is False

    def test_returns_failed_when_src_missing(self, tmp_path: Path) -> None:
        src = tmp_path / "missing.pdf"
        dst = tmp_path / "out.pdf"

        with patch("kindle_pdf_capture.ocr._ocrmypdf", _mock_ocrmypdf("fail")):
            result = run_ocr(src, dst)

        assert result.succeeded is False


# ---------------------------------------------------------------------------
# validate_ocr_lang
# ---------------------------------------------------------------------------


class TestValidateOcrLang:
    def test_valid_single_lang(self) -> None:
        assert validate_ocr_lang("jpn") is True

    def test_valid_eng(self) -> None:
        assert validate_ocr_lang("eng") is True

    def test_valid_combined_lang(self) -> None:
        assert validate_ocr_lang("jpn+eng") is True

    def test_valid_triple_lang(self) -> None:
        assert validate_ocr_lang("jpn+eng+fra") is True

    def test_invalid_uppercase(self) -> None:
        assert validate_ocr_lang("JPN") is False

    def test_invalid_empty(self) -> None:
        assert validate_ocr_lang("") is False

    def test_invalid_path_traversal(self) -> None:
        assert validate_ocr_lang("../etc/passwd") is False

    def test_invalid_shell_metachar(self) -> None:
        assert validate_ocr_lang("eng$(echo)") is False

    def test_invalid_too_short(self) -> None:
        assert validate_ocr_lang("en") is False

    def test_invalid_too_long(self) -> None:
        assert validate_ocr_lang("english") is False

    def test_invalid_numbers(self) -> None:
        assert validate_ocr_lang("eng1") is False

    def test_invalid_starts_with_plus(self) -> None:
        assert validate_ocr_lang("+eng") is False

    def test_invalid_ends_with_plus(self) -> None:
        assert validate_ocr_lang("eng+") is False


class TestRunOcrSideEffects:
    def test_original_pdf_unaffected_on_ocr_failure(self, tmp_path: Path) -> None:
        """book.pdf must exist and be unchanged if OCR fails."""
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4 original")

        with patch("kindle_pdf_capture.ocr._ocrmypdf", _mock_ocrmypdf("fail")):
            run_ocr(src, dst)

        assert src.exists()
        assert src.read_bytes() == b"%PDF-1.4 original"
