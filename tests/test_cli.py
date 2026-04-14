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
        """Run the CLI with all heavy calls mocked for exactly 1 page."""
        runner = CliRunner()
        window = _make_window()
        frame = _content_bgr()

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key"),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=ContentRegion(x=50, y=50, w=1100, h=800),
            ),
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
        ):
            args = [
                "--out",
                str(tmp_path / "out"),
                "--start-delay",
                "0",
                "--max-pages",
                "1",
            ]
            if extra_args:
                args.extend(extra_args)

            return runner.invoke(cli, args)

    def test_exits_zero_on_success(self, tmp_path: Path) -> None:
        result = self._run(tmp_path)
        assert result.exit_code == 0, result.output

    def test_max_pages_option(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ["--max-pages", "1"])
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
            result = runner.invoke(cli, ["--out", str(tmp_path / "out"), "--start-delay", "0"])
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
            result = runner.invoke(cli, ["--out", str(tmp_path / "out"), "--start-delay", "0"])
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
            result = runner.invoke(cli, ["--out", str(tmp_path / "out"), "--start-delay", "0"])
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

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key"),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=ContentRegion(x=50, y=50, w=1100, h=800),
            ),
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
        ):
            result = runner.invoke(
                cli,
                [
                    "--out",
                    str(out_dir),
                    "--start-delay",
                    "0",
                    "--max-pages",
                    "1",
                    "--retry-failed",
                ],
            )
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Page-turn order: send_page_turn_key must be called BEFORE wait_for_render
# ---------------------------------------------------------------------------


class TestPageTurnOrder:
    def test_send_page_turn_key_called_before_wait_for_render(self, tmp_path: Path) -> None:
        """After capturing a page, the key event must be sent first, then
        wait_for_render polls until the *new* page has settled.

        The wrong order (wait_for_render → capture → send_page_turn_key) causes
        the render-wait to converge immediately on the already-stable page,
        so every capture ends up being the same page.
        """
        call_order: list[str] = []

        runner = CliRunner()
        window = _make_window()
        frame = _content_bgr()

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

        def _record_arrow(*_a, **_kw) -> None:
            call_order.append("send_page_turn_key")

        def _record_wait(*_a, **_kw) -> WaitResult:
            call_order.append("wait_for_render")
            return WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2)

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key", side_effect=_record_arrow),
            patch("kindle_pdf_capture.main.wait_for_render", side_effect=_record_wait),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=ContentRegion(x=50, y=50, w=1100, h=800),
            ),
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
        ):
            result = runner.invoke(
                cli,
                ["--out", str(tmp_path / "out"), "--start-delay", "0", "--max-pages", "1"],
            )

        assert result.exit_code == 0, result.output
        # send_page_turn_key must appear before wait_for_render in the call sequence
        assert "send_page_turn_key" in call_order
        assert "wait_for_render" in call_order
        arrow_idx = call_order.index("send_page_turn_key")
        wait_idx = call_order.index("wait_for_render")
        assert arrow_idx < wait_idx, (
            f"Expected send_page_turn_key (pos {arrow_idx}) before "
            f"wait_for_render (pos {wait_idx}), got: {call_order}"
        )


# ---------------------------------------------------------------------------
# --ocr flag
# ---------------------------------------------------------------------------


class TestCliOcr:
    def test_ocr_flag_triggers_ocr_call(self, tmp_path: Path) -> None:
        runner = CliRunner()
        out_dir = tmp_path / "out"

        window = _make_window()
        frame = _content_bgr()

        # Pre-create a fake JPEG so jpeg_paths is non-empty and OCR is reached.
        (out_dir / "cropped").mkdir(parents=True)
        (out_dir / "pdf").mkdir(parents=True)
        (out_dir / "logs").mkdir(parents=True)
        fake_jpeg = out_dir / "cropped" / "page_0001.jpg"
        fake_jpeg.write_bytes(b"FAKE")

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.ocr import OcrResult, OcrStatus
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key"),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=ContentRegion(x=50, y=50, w=1100, h=800),
            ),
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch(
                "kindle_pdf_capture.main.run_ocr",
                return_value=OcrResult(status=OcrStatus.SUCCESS, output="", returncode=0),
            ) as mock_ocr,
            patch("kindle_pdf_capture.main.time.sleep"),
        ):
            result = runner.invoke(
                cli,
                [
                    "--out",
                    str(out_dir),
                    "--start-delay",
                    "0",
                    "--max-pages",
                    "1",
                    "--ocr",
                ],
            )
        assert result.exit_code == 0, result.output
        mock_ocr.assert_called_once()


# ---------------------------------------------------------------------------
# --direction option
# ---------------------------------------------------------------------------


def _run_with_direction(tmp_path: Path, direction: str) -> tuple[object, list]:
    """Helper: run kpc with --direction and return (result, captured key_codes)."""
    runner = CliRunner()
    window = _make_window()
    frame = _content_bgr()
    key_codes_used: list[int] = []

    from kindle_pdf_capture.cropper import ContentRegion
    from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

    def _capture_key(*args, **kwargs) -> None:
        # send_page_turn_key(pid, key_code, ...) — positional args
        if len(args) >= 2:
            key_codes_used.append(args[1])

    with (
        patch("kindle_pdf_capture.main.check_accessibility"),
        patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
        patch("kindle_pdf_capture.main.focus_window"),
        patch("kindle_pdf_capture.main.capture_window", return_value=frame),
        patch("kindle_pdf_capture.main.send_page_turn_key", side_effect=_capture_key),
        patch(
            "kindle_pdf_capture.main.wait_for_render",
            return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
        ),
        patch(
            "kindle_pdf_capture.main.detect_content_region",
            return_value=ContentRegion(x=50, y=50, w=1100, h=800),
        ),
        patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
        patch("kindle_pdf_capture.main.save_jpeg"),
        patch("kindle_pdf_capture.main.build_pdf"),
        patch("kindle_pdf_capture.main.optimise_pdf"),
        patch("kindle_pdf_capture.main.time.sleep"),
    ):
        result = runner.invoke(
            cli,
            [
                "--out",
                str(tmp_path / "out"),
                "--start-delay",
                "0",
                "--max-pages",
                "1",
                "--direction",
                direction,
            ],
        )
    return result, key_codes_used


class TestCliDirection:
    def test_direction_right_uses_key_124(self, tmp_path: Path) -> None:
        """--direction right must send right-arrow (key code 124)."""
        result, codes = _run_with_direction(tmp_path, "right")
        assert result.exit_code == 0, result.output
        assert codes == [124], f"Expected [124] for --direction right, got {codes}"

    def test_direction_left_uses_key_123(self, tmp_path: Path) -> None:
        """--direction left must send left-arrow (key code 123) for RTL books."""
        result, codes = _run_with_direction(tmp_path, "left")
        assert result.exit_code == 0, result.output
        assert codes == [123], f"Expected [123] for --direction left, got {codes}"

    def test_default_direction_is_right(self, tmp_path: Path) -> None:
        """Omitting --direction must default to right-arrow (key code 124)."""
        runner = CliRunner()
        window = _make_window()
        frame = _content_bgr()
        key_codes_used: list[int] = []

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

        def _capture_key(*args, **kwargs) -> None:
            if len(args) >= 2:
                key_codes_used.append(args[1])

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key", side_effect=_capture_key),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=ContentRegion(x=50, y=50, w=1100, h=800),
            ),
            patch("kindle_pdf_capture.main.normalize_image", return_value=frame),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
        ):
            result = runner.invoke(
                cli,
                ["--out", str(tmp_path / "out"), "--start-delay", "0", "--max-pages", "1"],
            )
        assert result.exit_code == 0, result.output
        assert key_codes_used == [124], f"Default should be right (124), got {key_codes_used}"


# ---------------------------------------------------------------------------
# Consistent scale: normalize_image must use raw-frame width as basis
# ---------------------------------------------------------------------------


class TestConsistentScale:
    """normalize_image must receive a resize_width derived from the raw frame
    width, not from the cropped region width.

    Without this, pages with different content-region widths (e.g. 1100 px on
    a wide page vs. 800 px on a narrow page) would be scaled to the same
    resize_width, making text appear larger on narrow pages than wide ones.

    With frame-based scaling, every page is scaled by the same factor
    (resize_width / raw_frame_width), so text size is consistent across pages.
    """

    def _run_capture_and_capture_normalize_args(
        self,
        tmp_path: Path,
        frame_width: int,
        frame_height: int,
        region_width: int,
        resize_width: int = 1800,
    ) -> list[tuple]:
        """Run one page capture and return args passed to normalize_image."""
        runner = CliRunner()
        frame = _white_bgr(frame_width, frame_height)
        # Give the frame some content so detect_content_region is not called with blank
        frame[100:800:20, 50 : frame_width - 50] = 30

        window = _make_window()
        normalize_calls: list[tuple] = []

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

        def _capture_normalize(img, *, resize_width):
            normalize_calls.append((img.shape, resize_width))
            return img

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key"),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=ContentRegion(x=50, y=50, w=region_width, h=700),
            ),
            patch("kindle_pdf_capture.main.normalize_image", side_effect=_capture_normalize),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
            patch(
                "kindle_pdf_capture.main.resize_kindle_window",
                return_value=(window.width, window.height),
            ),
        ):
            runner.invoke(
                cli,
                [
                    "--out",
                    str(tmp_path / "out"),
                    "--start-delay",
                    "0",
                    "--max-pages",
                    "1",
                    "--resize-width",
                    str(resize_width),
                ],
            )
        return normalize_calls

    def test_normalize_width_based_on_frame_not_region(self, tmp_path: Path) -> None:
        """normalize_image resize_width must equal round(region.w * resize/frame_w).

        When frame is 2240 wide and resize_width=1800, scale = 1800/2240 = 0.804.
        A region of width 1100 must be normalized to round(1100 * 0.804) = 884,
        NOT to 1800 (which would be scale=1800/1100, incorrect).
        """
        frame_w = 2240
        region_w = 1100
        resize_width = 1800

        calls = self._run_capture_and_capture_normalize_args(
            tmp_path, frame_w, 2000, region_w, resize_width
        )
        assert calls, "normalize_image was never called"

        _, actual_resize_w = calls[0]
        expected = round(region_w * resize_width / frame_w)  # = round(1100 * 1800 / 2240) = 884

        assert actual_resize_w == expected, (
            f"normalize_image got resize_width={actual_resize_w}, "
            f"expected {expected} (frame-based scaling)"
        )

    def test_two_pages_different_region_widths_same_scale(self, tmp_path: Path) -> None:
        """Two pages with different content widths must use the same scale factor.

        If page 1 has region_w=1100 and page 2 has region_w=800, both captured
        from a 2240-wide frame with resize_width=1800, then:
          - page 1: normalize to round(1100 * 1800/2240) = 884
          - page 2: normalize to round(800 * 1800/2240) = 643

        The ratio 884/643 ≈ 1100/800 — content fills the same fraction of
        the frame, so text is rendered at the same physical size.
        """
        frame_w = 2240
        resize_width = 1800
        scale = resize_width / frame_w

        runner = CliRunner()
        frame = _white_bgr(frame_w, 2000)
        frame[100:1800:20, 50 : frame_w - 50] = 30

        window = _make_window()
        normalize_calls: list[int] = []
        # Phase 0 uses _detect_by_brightness directly (not detect_content_region).
        # detect_content_region is only called for body pages: index 0=page1, index 1=page2.
        region_widths_all = [1100, 800]
        call_count = 0

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus

        detect_count = 0

        def _detect_region(*_a, **_kw):
            nonlocal detect_count
            idx = min(detect_count, len(region_widths_all) - 1)
            detect_count += 1
            return ContentRegion(x=50, y=50, w=region_widths_all[idx], h=700)

        def _capture_normalize(img, *, resize_width):
            normalize_calls.append(resize_width)
            return img

        def _do_capture(*_a, **_kw):
            nonlocal call_count
            call_count += 1
            return frame

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", side_effect=_do_capture),
            patch("kindle_pdf_capture.main.send_page_turn_key"),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            patch("kindle_pdf_capture.main.detect_content_region", side_effect=_detect_region),
            patch("kindle_pdf_capture.main.normalize_image", side_effect=_capture_normalize),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
            patch(
                "kindle_pdf_capture.main.resize_kindle_window",
                return_value=(window.width, window.height),
            ),
        ):
            runner.invoke(
                cli,
                [
                    "--out",
                    str(tmp_path / "out"),
                    "--start-delay",
                    "0",
                    "--max-pages",
                    "2",
                    "--resize-width",
                    str(resize_width),
                ],
            )

        assert len(normalize_calls) >= 2, "normalize_image was not called for 2 pages"
        w1, w2 = normalize_calls[0], normalize_calls[1]
        # Pages 1 and 2 use region_widths_all[0] and [1]
        expected_w1 = round(region_widths_all[0] * scale)
        expected_w2 = round(region_widths_all[1] * scale)
        assert w1 == expected_w1, f"Page 1: expected {expected_w1}, got {w1}"
        assert w2 == expected_w2, f"Page 2: expected {expected_w2}, got {w2}"


# ---------------------------------------------------------------------------
# Window resize to match cover page width
# ---------------------------------------------------------------------------


class TestWindowResizeForCoverMatch:
    """The capture loop must resize the Kindle window before page 1 so that
    subsequent body pages produce the same pixel width as the cover page rect."""

    def test_resize_called_before_capture_loop(self, tmp_path: Path) -> None:
        """resize_kindle_window must be called once, before any page is captured.

        Phase 0 strips the title bar via _find_header_bottom, then calls
        _detect_by_brightness to measure cover width. Both are mocked so the
        test does not require a real cover frame.
        """
        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus
        from kindle_pdf_capture.window_capture import KindleWindow

        runner = CliRunner()
        frame_w = 2240
        frame = _white_bgr(frame_w, 2358)
        frame[200:2000:20, 100 : frame_w - 100] = 30

        window = KindleWindow(pid=1, window_id=1, x=0, y=30, width=1120, height=1179)

        resize_calls: list[tuple] = []

        # Cover page brightness rect (narrower than frame)
        cover_region = ContentRegion(x=100, y=60, w=900, h=2200)
        body_region = ContentRegion(x=0, y=183, w=frame_w, h=2175)

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key"),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            # Phase 0: mock title bar detection (0 = no title bar to strip)
            patch("kindle_pdf_capture.cropper._find_header_bottom", return_value=0),
            # Phase 0: mock _detect_by_brightness to return cover_region
            patch(
                "kindle_pdf_capture.cropper._detect_by_brightness",
                return_value=cover_region,
            ),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=body_region,
            ),
            patch("kindle_pdf_capture.main.normalize_image", side_effect=lambda img, **_: img),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
            patch(
                "kindle_pdf_capture.main.resize_kindle_window",
                side_effect=lambda w, **kw: (resize_calls.append(kw), (w.width, w.height))[1],
            ),
        ):
            runner.invoke(
                cli,
                ["--out", str(tmp_path / "out"), "--start-delay", "0", "--max-pages", "2"],
            )

        assert len(resize_calls) >= 1, "resize_kindle_window was never called"

    def test_window_restored_after_capture(self, tmp_path: Path) -> None:
        """resize_kindle_window must be called a second time to restore original size."""
        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.render_wait import WaitResult, WaitStatus
        from kindle_pdf_capture.window_capture import KindleWindow

        runner = CliRunner()
        frame_w = 2240
        frame = _white_bgr(frame_w, 2358)
        frame[200:2000:20, 100 : frame_w - 100] = 30

        window = KindleWindow(pid=1, window_id=1, x=0, y=30, width=1120, height=1179)
        orig_w, orig_h = window.width, window.height

        resize_calls: list[dict] = []

        cover_region = ContentRegion(x=100, y=60, w=900, h=2200)
        body_region = ContentRegion(x=0, y=183, w=frame_w, h=2175)

        with (
            patch("kindle_pdf_capture.main.check_accessibility"),
            patch("kindle_pdf_capture.main.find_kindle_window", return_value=window),
            patch("kindle_pdf_capture.main.focus_window"),
            patch("kindle_pdf_capture.main.capture_window", return_value=frame),
            patch("kindle_pdf_capture.main.send_page_turn_key"),
            patch(
                "kindle_pdf_capture.main.wait_for_render",
                return_value=WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=2),
            ),
            # Phase 0: mock title bar detection and _detect_by_brightness
            patch("kindle_pdf_capture.cropper._find_header_bottom", return_value=0),
            patch(
                "kindle_pdf_capture.cropper._detect_by_brightness",
                return_value=cover_region,
            ),
            patch(
                "kindle_pdf_capture.main.detect_content_region",
                return_value=body_region,
            ),
            patch("kindle_pdf_capture.main.normalize_image", side_effect=lambda img, **_: img),
            patch("kindle_pdf_capture.main.save_jpeg"),
            patch("kindle_pdf_capture.main.build_pdf"),
            patch("kindle_pdf_capture.main.optimise_pdf"),
            patch("kindle_pdf_capture.main.time.sleep"),
            patch(
                "kindle_pdf_capture.main.resize_kindle_window",
                side_effect=lambda w, **kw: (resize_calls.append(kw), (w.width, w.height))[1],
            ),
        ):
            runner.invoke(
                cli,
                ["--out", str(tmp_path / "out"), "--start-delay", "0", "--max-pages", "2"],
            )

        # Last call must restore original dimensions
        assert len(resize_calls) >= 2, "Expected at least 2 resize calls (resize + restore)"
        last = resize_calls[-1]
        assert last["target_width"] == orig_w, (
            f"Restore width: expected {orig_w}, got {last['target_width']}"
        )
        assert last["target_height"] == orig_h, (
            f"Restore height: expected {orig_h}, got {last['target_height']}"
        )


# ---------------------------------------------------------------------------
# _apply_crop_lock unit tests
# ---------------------------------------------------------------------------


class TestApplyCropLock:
    """Unit tests for _apply_crop_lock.

    This function stabilises the crop y-coordinate across reading-mode pages.
    The first reading-mode page sets the lock; subsequent pages are clamped.
    Cover/image pages (region.y == titlebar_y) are not affected.
    """

    def _make_region(self, x, y, w, h):
        from kindle_pdf_capture.cropper import ContentRegion

        return ContentRegion(x=x, y=y, w=w, h=h)

    def _make_frame(self, w=1200, h=900):
        return np.zeros((h, w, 3), dtype=np.uint8)

    def test_first_reading_mode_page_sets_lock(self):
        """First reading-mode page: locked_crop_y must be set to region.y."""
        from kindle_pdf_capture.main import _apply_crop_lock

        frame = self._make_frame(1200, 900)
        titlebar_y = 55
        # Reading-mode: full-width region with y > titlebar_y
        region = self._make_region(x=0, y=130, w=1200, h=770)

        new_region, new_lock = _apply_crop_lock(region, frame, titlebar_y, None)

        assert new_lock == 130, f"Lock should be set to 130, got {new_lock}"
        assert new_region.y == 130

    def test_subsequent_page_clamped_to_lock(self):
        """Second reading-mode page with different y: region.y must be clamped."""
        from kindle_pdf_capture.main import _apply_crop_lock

        frame = self._make_frame(1200, 900)
        titlebar_y = 55
        locked_crop_y = 130
        # Same full-width, but y drifted by 3 pixels (header-detection variance)
        region = self._make_region(x=0, y=133, w=1200, h=767)

        new_region, new_lock = _apply_crop_lock(region, frame, titlebar_y, locked_crop_y)

        assert new_lock == 130, "Lock must not change after first page"
        assert new_region.y == 130, f"y must be clamped to 130, got {new_region.y}"
        # h must be adjusted so the bottom stays at the frame bottom
        assert new_region.h == 900 - 130, f"h must be {900 - 130}, got {new_region.h}"

    def test_cover_page_not_locked(self):
        """Cover/image page (region.y == titlebar_y): must not be locked."""
        from kindle_pdf_capture.main import _apply_crop_lock

        frame = self._make_frame(1200, 900)
        titlebar_y = 55
        # Cover page: region starts exactly at titlebar_y (only macOS bar stripped)
        region = self._make_region(x=0, y=55, w=1200, h=845)

        new_region, new_lock = _apply_crop_lock(region, frame, titlebar_y, None)

        assert new_lock is None, "Cover page must not set locked_crop_y"
        assert new_region.y == 55

    def test_same_y_does_not_rebuild_region(self):
        """If region.y already equals locked_crop_y, region must be returned as-is."""
        from kindle_pdf_capture.main import _apply_crop_lock

        frame = self._make_frame(1200, 900)
        titlebar_y = 55
        locked_crop_y = 130
        region = self._make_region(x=0, y=130, w=1200, h=770)

        new_region, new_lock = _apply_crop_lock(region, frame, titlebar_y, locked_crop_y)

        assert new_region is region, "Region object must be the same when y matches lock"
        assert new_lock == 130

    def test_partial_width_region_not_locked(self):
        """A region narrower than the full frame width must not trigger locking.

        This handles image-only pages where detect_content_region returns a
        sub-frame rect (e.g. a centred illustration narrower than the window).
        """
        from kindle_pdf_capture.main import _apply_crop_lock

        frame = self._make_frame(1200, 900)
        titlebar_y = 55
        # Partial-width region (e.g. a centred cover illustration)
        region = self._make_region(x=100, y=130, w=1000, h=770)  # w=1000 < frame w=1200

        _, new_lock = _apply_crop_lock(region, frame, titlebar_y, None)

        assert new_lock is None, "Partial-width region must not set locked_crop_y"

    def test_lock_preserved_across_multiple_pages(self):
        """Simulate three reading-mode pages; lock set on page 1, stable for 2 and 3."""
        from kindle_pdf_capture.main import _apply_crop_lock

        frame = self._make_frame(1200, 900)
        titlebar_y = 55
        locked = None

        ys = [130, 132, 128]  # slight variance between pages
        for i, y in enumerate(ys):
            region = self._make_region(x=0, y=y, w=1200, h=900 - y)
            region, locked = _apply_crop_lock(region, frame, titlebar_y, locked)
            assert region.y == 130, f"Page {i + 1}: y must be 130, got {region.y}"
        assert locked == 130
