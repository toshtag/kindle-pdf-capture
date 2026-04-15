"""Tests for the OCR wrapper module.

All tests mock subprocess so they do not require ocrmypdf or tesseract
to be installed on the CI runner.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from kindle_pdf_capture.ocr import OcrResult, OcrStatus, run_ocr, validate_ocr_lang

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
    def test_returns_success_on_zero_returncode(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = run_ocr(src, dst)

        assert result.status == OcrStatus.SUCCESS
        assert result.returncode == 0

    def test_output_path_is_dst(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = run_ocr(src, dst)

        assert result.output == dst

    def test_subprocess_called_with_correct_args(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            run_ocr(src, dst, lang="jpn+eng", optimize=2)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "ocrmypdf"
        assert "--skip-text" in cmd
        assert "-l" in cmd
        assert "jpn+eng" in cmd
        assert "--optimize" in cmd
        assert "2" in cmd or 2 in cmd
        assert str(src) in cmd
        assert str(dst) in cmd

    def test_lang_parameter_passed(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            run_ocr(src, dst, lang="eng")

        cmd = mock_run.call_args[0][0]
        idx = cmd.index("-l")
        assert cmd[idx + 1] == "eng"


# ---------------------------------------------------------------------------
# run_ocr: failure path (must not raise)
# ---------------------------------------------------------------------------


class TestRunOcrFailure:
    def test_returns_failed_on_nonzero_returncode(self, tmp_path: Path) -> None:
        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="some OCR error")
            result = run_ocr(src, dst)

        assert result.status == OcrStatus.FAILED
        assert result.returncode == 1
        assert result.succeeded is False

    def test_does_not_raise_on_subprocess_error(self, tmp_path: Path) -> None:
        """Even if subprocess raises, run_ocr must return a result, not propagate."""

        src = tmp_path / "book.pdf"
        dst = tmp_path / "book_ocr.pdf"
        src.write_bytes(b"%PDF-1.4")

        with patch("subprocess.run", side_effect=FileNotFoundError("ocrmypdf not found")):
            result = run_ocr(src, dst)

        assert result.status == OcrStatus.FAILED
        assert result.succeeded is False

    def test_returns_failed_when_src_missing(self, tmp_path: Path) -> None:
        src = tmp_path / "missing.pdf"
        dst = tmp_path / "out.pdf"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="")
            result = run_ocr(src, dst)

        # Either it returns FAILED without calling subprocess, or subprocess
        # fails — either way, result.succeeded must be False
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

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            run_ocr(src, dst)

        assert src.exists()
        assert src.read_bytes() == b"%PDF-1.4 original"
