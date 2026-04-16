"""Session control, skip logic, end-of-book detection, and persistence.

Separates the stateful concerns (which pages are done, when to stop)
from the capture loop so each can be tested independently.
"""

from __future__ import annotations

import enum
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
    max_pages: int | None = None
    resize_width: int = 1800
    jpeg_quality: int = 80
    save_raw: bool = False
    start_delay: int = 3
    pdf_dpi: float = 300.0
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

    def record_duplicate(self, before: np.ndarray, after: np.ndarray) -> None:
        """Compare frames captured before and after a page-turn key press.

        If the two frames differ (page actually turned), the streak resets to 0.
        If they are visually identical (key had no effect), the streak increments.
        This is more robust than hashing a single frame because it detects change
        regardless of how similar adjacent pages look in isolation.
        """
        if _frames_differ(before, after):
            self._duplicate_streak = 0
        else:
            self._duplicate_streak += 1
        logger.debug("Duplicate streak: %d", self._duplicate_streak)

    # ------------------------------------------------------------------
    # Termination
    # ------------------------------------------------------------------

    def is_finished(self) -> bool:
        """Return True when the capture loop should stop."""
        if self._cfg.max_pages is not None and len(self._results) >= self._cfg.max_pages:
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


def _frames_differ(before: np.ndarray, after: np.ndarray, threshold: float = 0.01) -> bool:
    """Return True when *before* and *after* differ enough to indicate a page turn.

    Unlike render_wait.compute_diff_ratio (which inspects only a central patch
    to detect mid-transition jitter), this function downscales the *whole* frame
    before comparing.  This is necessary for Japanese vertical-writing books
    where text sits near the left/right edges and the centre is blank background
    — a central-patch comparison would score 0 even when two distinct pages are
    being compared.

    Strategy: resize both frames to 64x64 grayscale, compute mean absolute
    difference (MAD), normalise to [0, 1].  A threshold of 0.01 (1 % of max
    pixel range) is conservative enough to survive JPEG compression artefacts
    while catching any genuine page-content change.
    """
    import cv2

    small_a = cv2.resize(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY), (64, 64)).astype(np.float32)
    small_b = cv2.resize(cv2.cvtColor(after, cv2.COLOR_BGR2GRAY), (64, 64)).astype(np.float32)
    mad = float(np.abs(small_a - small_b).mean() / 255.0)
    return mad > threshold
