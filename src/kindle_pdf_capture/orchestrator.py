"""Session control, skip logic, end-of-book detection, and persistence.

Separates the stateful concerns (which pages are done, when to stop)
from the capture loop so each can be tested independently.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Number of consecutive duplicate frames that signals the last page
_DUPLICATE_STREAK_LIMIT = 3


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class CaptureConfig:
    """All settings for a capture run."""

    out_dir: Path
    max_pages: int = 1000
    resize_width: int = 1800
    jpeg_quality: int = 80
    save_raw: bool = False
    start_delay: int = 3
    ocr: bool = False
    ocr_lang: str = "jpn+eng"
    ocr_optimize: int = 2

    def ensure_dirs(self) -> None:
        """Create required output directories."""
        (self.out_dir / "cropped").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "pdf").mkdir(parents=True, exist_ok=True)
        (self.out_dir / "logs").mkdir(parents=True, exist_ok=True)
        if self.save_raw:
            (self.out_dir / "raw").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Page results
# ---------------------------------------------------------------------------


class PageStatus(enum.Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PageResult:
    """Outcome for a single captured page."""

    page_num: int
    status: PageStatus
    cropped_path: Path | None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class CaptureSession:
    """Tracks progress, skip decisions, and end-of-book detection."""

    def __init__(self, config: CaptureConfig) -> None:
        self._cfg = config
        self._results: list[PageResult] = []
        self._duplicate_streak: int = 0
        self._last_hash: str | None = None

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def cropped_path(self, page_num: int) -> Path:
        return self._cfg.out_dir / "cropped" / f"page_{page_num:04d}.jpg"

    def raw_path(self, page_num: int) -> Path:
        return self._cfg.out_dir / "raw" / f"raw_{page_num:04d}.jpg"

    # ------------------------------------------------------------------
    # Skip logic
    # ------------------------------------------------------------------

    def should_skip(self, page_num: int) -> bool:
        """Return True if the cropped image already exists on disk."""
        return self.cropped_path(page_num).exists()

    # ------------------------------------------------------------------
    # Result recording
    # ------------------------------------------------------------------

    def record_result(self, result: PageResult) -> None:
        self._results.append(result)

    def record_duplicate(self, frame: np.ndarray) -> None:
        """Call when the page has not changed after a page-turn attempt."""
        h = _frame_hash(frame)
        if h == self._last_hash:
            self._duplicate_streak += 1
        else:
            self._duplicate_streak = 1
        self._last_hash = h
        logger.debug("Duplicate streak: %d", self._duplicate_streak)

    # ------------------------------------------------------------------
    # Termination
    # ------------------------------------------------------------------

    def is_finished(self) -> bool:
        """Return True when the capture loop should stop."""
        if len(self._results) >= self._cfg.max_pages:
            logger.info("Reached max_pages=%d", self._cfg.max_pages)
            return True
        if self._duplicate_streak >= _DUPLICATE_STREAK_LIMIT:
            logger.info("Duplicate streak=%d — last page reached", self._duplicate_streak)
            return True
        return False

    @property
    def results(self) -> list[PageResult]:
        return list(self._results)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def save_session(config: CaptureConfig, results: list[PageResult]) -> None:
    """Write failed_pages.json and metadata.json to the logs directory."""
    logs_dir = config.out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    failed = [r.page_num for r in results if r.status == PageStatus.FAILED]
    (logs_dir / "failed_pages.json").write_text(
        json.dumps({"failed_pages": failed}, indent=2), encoding="utf-8"
    )

    metadata = {
        "run_at": datetime.now(tz=UTC).isoformat(),
        "page_count": len(results),
        "failed_count": len(failed),
        "jpeg_quality": config.jpeg_quality,
        "resize_width": config.resize_width,
        "ocr": config.ocr,
        "ocr_lang": config.ocr_lang,
        "failed_pages": failed,
    }
    (logs_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.info("Session saved: %d pages, %d failed", len(results), len(failed))


def load_session(config: CaptureConfig) -> list[int]:
    """Return the list of failed page numbers from a previous run, or []."""
    path = config.out_dir / "logs" / "failed_pages.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("failed_pages", []))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _frame_hash(frame: np.ndarray) -> str:
    """Return a fast perceptual hash of *frame* for duplicate detection."""
    # Downscale to 16x16 grayscale and MD5 the bytes
    import cv2

    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (16, 16))
    return hashlib.md5(small.tobytes()).hexdigest()
