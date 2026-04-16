"""Tests for the orchestrator module.

All I/O, Quartz, and subprocess calls are mocked so the suite is
hermetic and fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from kindle_pdf_capture.orchestrator import (
    CaptureConfig,
    CaptureSession,
    PageResult,
    PageStatus,
    load_session,
    save_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _white_bgr(w: int = 1200, h: int = 900) -> np.ndarray:
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _content_bgr() -> np.ndarray:
    img = _white_bgr()
    img[200:700, 100:1100] = 30  # solid dark region — distinct from white at any downscale
    return img


def _sparse_text_bgr(text_rows: list[tuple[int, int, int, int]]) -> np.ndarray:
    """White background with thin horizontal text-like stripes at specified rows.

    Each tuple is (y0, y1, x0, x1) defining a text block region filled with dark pixels.
    Simulates sparse-text pages (title page, half-title, etc.) that differ only
    slightly — the kind that fooled the old 16x16 hash-based detector.
    """
    img = _white_bgr()
    for y0, y1, x0, x1 in text_rows:
        img[y0:y1, x0:x1] = 40
    return img


def _config(tmp_path: Path, **overrides) -> CaptureConfig:
    defaults = dict(
        out_dir=tmp_path / "book",
        max_pages=10,
        resize_width=800,
        jpeg_quality=80,
        save_raw=False,
        start_delay=0,
        ocr=False,
        ocr_lang="jpn+eng",
        ocr_optimize=2,
    )
    defaults.update(overrides)
    return CaptureConfig(**defaults)


# ---------------------------------------------------------------------------
# CaptureConfig
# ---------------------------------------------------------------------------


class TestCaptureConfig:
    def test_fields_accessible(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        assert cfg.max_pages == 10
        assert cfg.jpeg_quality == 80
        assert cfg.save_raw is False

    def test_directories_created_on_init(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        cfg.ensure_dirs()
        assert (cfg.out_dir / "cropped").is_dir()
        assert (cfg.out_dir / "pdf").is_dir()
        assert (cfg.out_dir / "logs").is_dir()

    def test_raw_dir_not_created_when_save_raw_false(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path, save_raw=False)
        cfg.ensure_dirs()
        assert not (cfg.out_dir / "raw").exists()

    def test_raw_dir_created_when_save_raw_true(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path, save_raw=True)
        cfg.ensure_dirs()
        assert (cfg.out_dir / "raw").is_dir()


# ---------------------------------------------------------------------------
# PageResult / PageStatus
# ---------------------------------------------------------------------------


class TestPageResult:
    def test_fields(self, tmp_path: Path) -> None:
        p = PageResult(
            page_num=1,
            status=PageStatus.OK,
            cropped_path=tmp_path / "p0001.jpg",
        )
        assert p.page_num == 1
        assert p.status == PageStatus.OK

    def test_failed_status(self) -> None:
        r = PageResult(page_num=5, status=PageStatus.FAILED, cropped_path=None)
        assert r.status == PageStatus.FAILED


# ---------------------------------------------------------------------------
# CaptureSession: skip logic
# ---------------------------------------------------------------------------


class TestCaptureSessionSkip:
    def test_existing_page_is_skipped(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        cfg.ensure_dirs()
        existing = cfg.out_dir / "cropped" / "page_0001.jpg"
        existing.write_bytes(b"fake jpeg")

        session = CaptureSession(cfg)
        assert session.should_skip(1) is True

    def test_missing_page_is_not_skipped(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        cfg.ensure_dirs()
        session = CaptureSession(cfg)
        assert session.should_skip(1) is False

    def test_page_path_format(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        session = CaptureSession(cfg)
        path = session.cropped_path(42)
        assert path.name == "page_0042.jpg"


# ---------------------------------------------------------------------------
# CaptureSession: end-of-book detection
# ---------------------------------------------------------------------------


class TestCaptureSessionEndDetection:
    def test_not_finished_initially(self, tmp_path: Path) -> None:
        session = CaptureSession(_config(tmp_path))
        assert session.is_finished() is False

    def test_finished_after_max_pages(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path, max_pages=3)
        session = CaptureSession(cfg)
        session.record_result(PageResult(1, PageStatus.OK, None))
        session.record_result(PageResult(2, PageStatus.OK, None))
        session.record_result(PageResult(3, PageStatus.OK, None))
        assert session.is_finished() is True

    def test_finished_after_consecutive_no_change(self, tmp_path: Path) -> None:
        """Streak reaches limit when before==after for 3 consecutive turns."""
        session = CaptureSession(_config(tmp_path))
        img = _white_bgr()
        for _ in range(3):
            session.record_duplicate(img, img)
        assert session.is_finished() is True

    def test_not_finished_after_few_no_change(self, tmp_path: Path) -> None:
        session = CaptureSession(_config(tmp_path))
        img = _white_bgr()
        session.record_duplicate(img, img)
        session.record_duplicate(img, img)
        assert session.is_finished() is False

    def test_streak_resets_when_page_changes(self, tmp_path: Path) -> None:
        """Streak resets to 0 when before and after differ (page actually turned)."""
        session = CaptureSession(_config(tmp_path))
        img_same = _white_bgr()
        img_new = _content_bgr()
        session.record_duplicate(img_same, img_same)
        session.record_duplicate(img_same, img_same)
        # page turned — before != after
        session.record_duplicate(img_same, img_new)
        assert session.is_finished() is False

    def test_sparse_text_pages_not_mistaken_for_duplicate(self, tmp_path: Path) -> None:
        """Two visually similar but distinct sparse-text pages must reset the streak.

        This is the scenario that broke the old 16x16 hash: a title page and a
        half-title page both have white backgrounds with only a few characters.
        With the before/after approach the comparison is between the captured
        frame *before* the key press and the stable frame *after* — so as long
        as the render_wait returns a genuinely new frame the streak resets.
        """
        session = CaptureSession(_config(tmp_path))
        # Simulate title page (before) → half-title page (after)
        title_page = _sparse_text_bgr(
            [(300, 340, 500, 800), (400, 430, 500, 650), (550, 580, 500, 600)]
        )
        half_title = _sparse_text_bgr([(200, 240, 500, 800)])
        # before=title_page, after=half_title → pages differ → streak stays 0
        session.record_duplicate(title_page, half_title)
        assert session.is_finished() is False

    def test_ok_result_does_not_reset_duplicate_streak(self, tmp_path: Path) -> None:
        """record_result(OK) must NOT reset the duplicate streak."""
        session = CaptureSession(_config(tmp_path))
        img = _white_bgr()

        session.record_duplicate(img, img)
        session.record_duplicate(img, img)

        session.record_result(PageResult(1, PageStatus.OK, None))

        session.record_duplicate(img, img)
        assert session.is_finished() is True, (
            "Duplicate streak should have reached 3; record_result(OK) must not reset it."
        )


# ---------------------------------------------------------------------------
# save_session / load_session (failed_pages.json)
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    def test_save_and_load_failed_pages(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        cfg.ensure_dirs()
        results = [
            PageResult(1, PageStatus.OK, cfg.out_dir / "cropped" / "page_0001.jpg"),
            PageResult(2, PageStatus.FAILED, None),
            PageResult(3, PageStatus.FAILED, None),
        ]
        save_session(cfg, results)

        failed = load_session(cfg)
        assert set(failed) == {2, 3}

    def test_save_creates_metadata_json(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        cfg.ensure_dirs()
        save_session(cfg, [PageResult(1, PageStatus.OK, None)])
        meta = json.loads((cfg.out_dir / "logs" / "metadata.json").read_text())
        assert "page_count" in meta
        assert "jpeg_quality" in meta

    def test_load_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        cfg = _config(tmp_path)
        cfg.ensure_dirs()
        assert load_session(cfg) == []
