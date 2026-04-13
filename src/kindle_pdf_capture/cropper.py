"""Content-region detection for Kindle screenshots.

Extracts the book-body rectangle from a full Kindle window capture using
contour analysis, discarding UI chrome (title bar, page arrows, etc.).

All functions operate on uint8 BGR ndarrays (OpenCV native format).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ContentRegion:
    """Bounding rectangle of the detected book-body area.

    Coordinates follow OpenCV convention: origin at top-left,
    x → right, y → down.
    """

    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return self.w * self.h

    def slice(self) -> tuple[slice, slice]:
        """Return (row_slice, col_slice) for direct numpy indexing."""
        return slice(self.y, self.y + self.h), slice(self.x, self.x + self.w)


class CropError(RuntimeError):
    """Raised when no suitable content region can be detected."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_content_region(
    bgr: np.ndarray,
    *,
    margin: int = 15,
    min_area_ratio: float = 0.20,
) -> ContentRegion:
    """Detect the main text-body region in a Kindle screenshot.

    Algorithm:
    1. Grayscale + Gaussian blur to suppress noise.
    2. Canny edge detection to find character strokes.
    3. Dilation to merge nearby strokes into blobs.
    4. Contour detection → bounding rectangles.
    5. Keep the largest candidate whose area ≥ min_area_ratio of the image.
    6. Expand by *margin* pixels, clipped to image bounds.

    Args:
        bgr: uint8 BGR ndarray (OpenCV format).
        margin: Pixels to expand the detected bounding box on each side.
        min_area_ratio: Minimum fraction of total image area a candidate
            contour must cover to be considered valid.

    Returns:
        ContentRegion describing the detected body area.

    Raises:
        CropError: If no suitable region is found.
    """
    h_img, w_img = bgr.shape[:2]
    total_area = h_img * w_img

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Blur to reduce noise while preserving edges
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Canny with auto thresholds derived from the median pixel value
    median_val = float(np.median(blurred))
    low = max(0.0, 0.66 * median_val)
    high = min(255.0, 1.33 * median_val)
    # Fall back to fixed thresholds when image is nearly uniform
    if high - low < 10:
        low, high = 30.0, 100.0
    edges = cv2.Canny(blurred, low, high)

    # Dilate so neighbouring strokes merge into solid blobs
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 8))
    dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise CropError("No contours detected — image may be blank or uniform.")

    # Evaluate candidates: prefer large, centrally-located rectangles
    best: ContentRegion | None = None
    best_score = -1.0
    cx_img, cy_img = w_img / 2.0, h_img / 2.0

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = w * h
        if area < total_area * min_area_ratio:
            continue

        # Score = area_ratio minus normalised centre-distance penalty
        area_ratio = area / total_area
        cnt_cx = x + w / 2.0
        cnt_cy = y + h / 2.0
        dist = ((cnt_cx - cx_img) ** 2 + (cnt_cy - cy_img) ** 2) ** 0.5
        max_dist = (cx_img**2 + cy_img**2) ** 0.5
        score = area_ratio - 0.3 * (dist / (max_dist + 1e-6))

        if score > best_score:
            best_score = score
            best = ContentRegion(x=x, y=y, w=w, h=h)

    if best is None:
        raise CropError(
            f"No contour passed the minimum area threshold ({min_area_ratio:.0%} of image)."
        )

    # Expand by margin, clamped to image bounds
    rx = max(0, best.x - margin)
    ry = max(0, best.y - margin)
    rr = min(w_img, best.x + best.w + margin)
    rb = min(h_img, best.y + best.h + margin)

    logger.debug("Detected content region: x=%d y=%d w=%d h=%d", rx, ry, rr - rx, rb - ry)
    return ContentRegion(x=rx, y=ry, w=rr - rx, h=rb - ry)


def fallback_crop(bgr: np.ndarray, *, fraction: float = 0.04) -> ContentRegion:
    """Return a conservative crop removing *fraction* from each edge.

    Used when detect_content_region fails.  Preserves most of the image
    while cutting the most likely UI-chrome areas.

    Args:
        bgr: uint8 BGR ndarray.
        fraction: Fraction of width/height to remove from each side (0-0.5).

    Returns:
        ContentRegion for the cropped area.
    """
    h_img, w_img = bgr.shape[:2]
    dx = int(w_img * fraction)
    dy = int(h_img * fraction)
    return ContentRegion(x=dx, y=dy, w=w_img - 2 * dx, h=h_img - 2 * dy)
