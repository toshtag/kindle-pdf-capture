"""Tests for the CLI entry point.

All hardware-level calls (window capture, page-turn, screen recording) are
mocked so the suite is hermetic and fast.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from click.testing import CliRunner

from kindle_pdf_capture.main import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _white_bgr(w: int = 1200, h: int = 900) -> np.ndarray:
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _content_bgr() -> np.ndarray:
    img = _white_bgr()
    img[200:700:20, 100:1100] = 30
    return img


def _make_window():
    from kindle_pdf_capture.window_capture import KindleWindow

    return KindleWindow(pid=1234, window_id=10, x=0, y=0, width=1200, height=900)


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------


class TestCliHelp:
    def test_help_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    def test_help_shows_key_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "--out" in result.output
        assert "--max-pages" in result.output
        assert "--ocr" in result.output


# ---------------------------------------------------------------------------
# Basic happy path (smoke)
# ---------------------------------------------------------------------------


class TestCliHappyPath:
    def _run(self, tmp_path: Path, extra_args: list[str] | None = None) -> object:
        """Run the CLI with all heavy calls mocked, capturing one page then stopping."""
        runner = CliRunner()
        window = _make_window()
        frame = _content_bgr()

        # After the first real capture, return a static frame so duplicate-streak
        # terminates the loop quickly (3 identical frames).
        capture_frames = [frame, frame, frame, frame]
        capture_iter = iter(capture_frames)

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch(
                "kindle_pdf_capture.main.capture_window",
                side_effect=lambda w: next(capture_iter, frame),
            ),
            patch("kindle_pdf_capture.main.send_right_arrow"),
            patch("kindle_pdf_capture.main.wait_for_render") as mock_wait,
            patch("kindle_pdf_capture.main.detect_content_region") as mock_detect,
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
        ):
            from kindle_pdf_capture.cropper import ContentRegion
            from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

            mock_wait.return_value = WaitResult(
                status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2
            )
            mock_detect.return_value = ContentRegion(x=50, y=50, w=1100, h=800)

            args = ["--out", str(tmp_path / "out"), "--start-delay", "0"]
            if extra_args:
                args.extend(extra_args)

            return runner.invoke(cli, args)

    def test_exits_zero_on_success(self, tmp_path: Path) -> None:
        result = self._run(tmp_path)
        assert result.exit_code == 0, result.output

    def test_max_pages_option(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ["--max-pages", "5"])
        assert result.exit_code == 0, result.output

    def test_jpeg_quality_option(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ["--jpeg-quality", "90"])
        assert result.exit_code == 0, result.output

    def test_save_raw_flag(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ["--save-raw"])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Kindle not running
# ---------------------------------------------------------------------------


class TestCliKindleNotRunning:
    def test_exits_nonzero_when_kindle_not_found(self, tmp_path: Path) -> None:
        from kindle_pdf_capture.window_capture import WindowCaptureError

        runner = CliRunner()

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch(
                "kindle_pdf_capture.main.find_kindle_window",
                side_effect=WindowCaptureError("Kindle is not running"),
            ),
        ):
            result = runner.invoke(
                cli, ["--out", str(tmp_path / "out"), "--start-delay", "0"]
            )
        assert result.exit_code != 0

    def test_error_message_shown(self, tmp_path: Path) -> None:
        from kindle_pdf_capture.window_capture import WindowCaptureError

        runner = CliRunner()

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch(
                "kindle_pdf_capture.main.find_kindle_window",
                side_effect=WindowCaptureError("Kindle is not running"),
            ),
        ):
            result = runner.invoke(
                cli, ["--out", str(tmp_path / "out"), "--start-delay", "0"]
            )
        assert "Kindle" in result.output or "Error" in result.output


# ---------------------------------------------------------------------------
# Accessibility permission denied
# ---------------------------------------------------------------------------


class TestCliAccessibilityDenied:
    def test_exits_nonzero_when_no_permission(self, tmp_path: Path) -> None:
        from kindle_pdf_capture.page_turner import AccessibilityError

        runner = CliRunner()

        with patch(
            "kindle_pdf_capture.main.check_accessibility",
            side_effect=AccessibilityError("No permission"),
        ):
            result = runner.invoke(
                cli, ["--out", str(tmp_path / "out"), "--start-delay", "0"]
            )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# --retry-failed flag
# ---------------------------------------------------------------------------


class TestCliRetryFailed:
    def test_retry_flag_accepted(self, tmp_path: Path) -> None:
        """--retry-failed is a valid flag and does not cause an error."""
        runner = CliRunner()
        out_dir = tmp_path / "out"

        window = _make_window()
        frame = _content_bgr()

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_right_arrow"),
            patch("kindle_pdf_capture.main.wait_for_render") as mock_wait,
            patch("kindle_pdf_capture.main.detect_content_region") as mock_detect,
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
        ):
            from kindle_pdf_capture.cropper import ContentRegion
            from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

            mock_wait.return_value = WaitResult(
                status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2
            )
            mock_detect.return_value = ContentRegion(x=50, y=50, w=1100, h=800)

            result = runner.invoke(
                cli,
                ["--out", str(out_dir), "--start-delay", "0", "--retry-failed"],
            )
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# --ocr flag
# ---------------------------------------------------------------------------


class TestCliOcr:
    def test_ocr_flag_triggers_ocr_call(self, tmp_path: Path) -> None:
        runner = CliRunner()
        out_dir = tmp_path / "out"

        window = _make_window()
        frame = _content_bgr()

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_right_arrow"),
            patch("kindle_pdf_capture.main.wait_for_render") as mock_wait,
            patch("kindle_pdf_capture.main.detect_content_region") as mock_detect,
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.run_ocr") as mock_ocr,
        ):
            from kindle_pdf_capture.cropper import ContentRegion
            from kindle_pdf_capture.ocr import OcrResult, OcrStatus
            from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

            mock_wait.return_value = WaitResult(
                status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2
            )
            mock_detect.return_value = ContentRegion(x=50, y=50, w=1100, h=800)
            mock_ocr.return_value = OcrResult(
                status=OcrStatus.SUCCESS, output="", returncode=0
            )

            result = runner.invoke(
                cli,
                ["--out", str(out_dir), "--start-delay", "0", "--ocr"],
            )
        assert result.exit_code == 0, result.output
        mock_ocr.assert_called_once()
