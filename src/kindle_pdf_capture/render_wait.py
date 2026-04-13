"""Render-completion detection using frame-diff polling.

Instead of a fixed sleep, this module polls a small central region of the
screen and waits until consecutive frames become sufficiently similar,
indicating that Kindle has finished drawing the new page.
"""

from __future__ import annotations

import enum
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Default sampling region: a 200x200 patch from the image centre
_SAMPLE_SIZE = 200


class WaitStatus(enum.Enum):
    CONVERGED = "converged"
    TIMEOUT = "timeout"


@dataclass
class WaitResult:
    """Outcome of a wait_for_render() call."""

    status: WaitStatus
    elapsed: float  # seconds
    iterations: int

    @property
    def converged(self) -> bool:
        return self.status == WaitStatus.CONVERGED


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_diff_ratio(
    a: np.ndarray,
    b: np.ndarray,
    *,
    sample_size: int = _SAMPLE_SIZE,
) -> float:
    """Return the fraction of pixels that changed between two frames.

    Compares a central *sample_size x sample_size* patch to avoid being
    dominated by static UI elements near the edges.

    Args:
        a: First uint8 BGR frame.
        b: Second uint8 BGR frame (same shape as *a*).
        sample_size: Side length of the central patch to compare.

    Returns:
        Float in [0.0, 1.0]: 0.0 = identical, 1.0 = completely different.
    """
    h, w = a.shape[:2]
    cy, cx = h // 2, w // 2
    half = sample_size // 2
    y0, y1 = max(0, cy - half), min(h, cy + half)
    x0, x1 = max(0, cx - half), min(w, cx + half)

    patch_a = a[y0:y1, x0:x1]
    patch_b = b[y0:y1, x0:x1]

    if patch_a.size == 0:
        return 0.0

    gray_a = cv2.cvtColor(patch_a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray_b = cv2.cvtColor(patch_b, cv2.COLOR_BGR2GRAY).astype(np.float32)

    diff = np.abs(gray_a - gray_b)
    # Normalise by max possible difference (255) and pixel count
    return float(diff.sum() / (255.0 * diff.size))


def wait_for_render(
    *,
    capture_fn: Callable[[], np.ndarray],
    threshold: float = 0.02,
    timeout: float = 8.0,
    poll_interval: float = 0.05,
    stable_count: int = 2,
) -> WaitResult:
    """Poll until the captured frame stabilises or timeout is reached.

    After a page-turn key is sent, this function repeatedly captures a frame
    and compares it to the previous one.  Once *stable_count* consecutive
    comparisons all have a diff ratio <= *threshold*, the page is considered
    rendered.

    Args:
        capture_fn: Zero-argument callable that returns a uint8 BGR ndarray.
        threshold: Maximum diff ratio to consider two frames "the same".
        timeout: Maximum seconds to wait before giving up.
        poll_interval: Seconds to sleep between polls (use 0.0 in tests).
        stable_count: Number of consecutive stable comparisons required.

    Returns:
        WaitResult with CONVERGED or TIMEOUT status.
    """
    t0 = time.monotonic()
    prev = capture_fn()
    consecutive_stable = 0
    iterations = 0

    while True:
        elapsed = time.monotonic() - t0
        if elapsed >= timeout:
            logger.warning("wait_for_render timed out after %.1fs", timeout)
            return WaitResult(status=WaitStatus.TIMEOUT, elapsed=elapsed, iterations=iterations)

        if poll_interval > 0:
            time.sleep(poll_interval)

        curr = capture_fn()
        iterations += 1
        ratio = compute_diff_ratio(prev, curr)

        if ratio <= threshold:
            consecutive_stable += 1
            if consecutive_stable >= stable_count:
                elapsed = time.monotonic() - t0
                logger.debug("Render converged in %.2fs (%d iters)", elapsed, iterations)
                return WaitResult(
                    status=WaitStatus.CONVERGED, elapsed=elapsed, iterations=iterations
                )
        else:
            consecutive_stable = 0

        prev = curr
