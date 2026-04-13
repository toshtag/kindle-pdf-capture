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
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp_region(
    x: int, y: int, w: int, h: int, w_img: int, h_img: int, margin: int
) -> ContentRegion:
    rx = max(0, x - margin)
    ry = max(0, y - margin)
    rr = min(w_img, x + w + margin)
    rb = min(h_img, y + h + margin)
    return ContentRegion(x=rx, y=ry, w=rr - rx, h=rb - ry)


def _best_contour_region(
    contours: list,
    *,
    w_img: int,
    h_img: int,
    total_area: int,
    min_area_ratio: float,
    margin: int,
) -> ContentRegion | None:
    """Return the highest-scoring ContentRegion from *contours*, or None."""
    best: ContentRegion | None = None
    best_score = -1.0
    cx_img, cy_img = w_img / 2.0, h_img / 2.0

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = w * h
        if area < total_area * min_area_ratio:
            continue

        area_ratio = area / total_area
        cnt_cx = x + w / 2.0
        cnt_cy = y + h / 2.0
        dist = ((cnt_cx - cx_img) ** 2 + (cnt_cy - cy_img) ** 2) ** 0.5
        max_dist = (cx_img**2 + cy_img**2) ** 0.5
        score = area_ratio - 0.3 * (dist / (max_dist + 1e-6))

        if score > best_score:
            best_score = score
            best = _clamp_region(x, y, w, h, w_img, h_img, margin)

    return best


def _has_dark_border(gray: np.ndarray, *, border_width: int = 20, threshold: int = 15) -> bool:
    """Return True when the image has a dark frame on at least two opposite sides.

    Kindle wraps the page in a near-black background.  Checking that two
    opposing edge strips (left+right or top+bottom) are predominantly dark
    distinguishes a Kindle chrome border from a thin UI bar that only appears
    at the top of the image.
    """
    h, w = gray.shape
    bw = min(border_width, w // 4, h // 4)

    def _dark(strip: np.ndarray) -> bool:
        return float((strip <= threshold).sum()) / strip.size > 0.80

    return (_dark(gray[:, :bw]) and _dark(gray[:, w - bw:])) or (
        _dark(gray[:bw, :]) and _dark(gray[h - bw:, :])
    )


def _detect_by_brightness(
    bgr: np.ndarray,
    *,
    margin: int,
    min_area_ratio: float,
) -> ContentRegion | None:
    """Find the page region by thresholding away the dark Kindle chrome.

    Kindle surrounds the book page with a near-black background.  Any pixel
    brighter than a low threshold is considered part of the page.  Morphological
    closing merges the page into a single blob from which the bounding box is
    taken.

    This pass is only attempted when ``_has_dark_border`` confirms that two
    opposing edges are predominantly dark, distinguishing the Kindle chrome
    from an incidental UI bar.

    Returns None when the image has no dark border, or when no qualifying
    region is found (e.g. pure-black image).
    """
    h_img, w_img = bgr.shape[:2]
    total_area = h_img * w_img

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    if not _has_dark_border(gray):
        return None

    # Use a low threshold so even dark cover pages (value ~40) are captured.
    # The Kindle background is pure black (0); anything above 15 is page.
    _, mask = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)

    # Close gaps so the page appears as one solid blob
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    return _best_contour_region(
        contours,
        w_img=w_img,
        h_img=h_img,
        total_area=total_area,
        min_area_ratio=min_area_ratio,
        margin=margin,
    )


def _detect_by_edges(
    bgr: np.ndarray,
    *,
    margin: int,
    min_area_ratio: float,
) -> ContentRegion | None:
    """Detect the content region via Canny edge detection.

    Used as a fallback when the brightness pass fails (e.g. a uniformly
    bright image with no dark border).

    Returns None when no qualifying region is found.
    """
    h_img, w_img = bgr.shape[:2]
    total_area = h_img * w_img

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    median_val = float(np.median(blurred))
    low = max(0.0, 0.66 * median_val)
    high = min(255.0, 1.33 * median_val)
    if high - low < 10:
        low, high = 30.0, 100.0
    edges = cv2.Canny(blurred, low, high)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 8))
    dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    return _best_contour_region(
        contours,
        w_img=w_img,
        h_img=h_img,
        total_area=total_area,
        min_area_ratio=min_area_ratio,
        margin=margin,
    )


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

    Two-pass strategy:

    1. **Brightness pass**: threshold pixels above the near-black Kindle
       background to isolate the page blob.  Works for both white-background
       text pages and dark cover pages, as long as the page is brighter than
       the surrounding chrome.

    2. **Edge-detection fallback**: used when the brightness pass yields no
       qualifying region (e.g. the entire image is bright with no dark border).

    Args:
        bgr: uint8 BGR ndarray (OpenCV format).
        margin: Pixels to expand the detected bounding box on each side.
        min_area_ratio: Minimum fraction of total image area a candidate
            must cover to be considered valid.

    Returns:
        ContentRegion describing the detected body area.

    Raises:
        CropError: If neither pass finds a suitable region.
    """
    region = _detect_by_brightness(bgr, margin=margin, min_area_ratio=min_area_ratio)
    if region is not None:
        logger.debug(
            "Content region (brightness): x=%d y=%d w=%d h=%d",
            region.x, region.y, region.w, region.h,
        )
        return region

    logger.debug("Brightness pass found nothing; trying edge detection.")
    region = _detect_by_edges(bgr, margin=margin, min_area_ratio=min_area_ratio)
    if region is not None:
        logger.debug(
            "Content region (edges): x=%d y=%d w=%d h=%d",
            region.x, region.y, region.w, region.h,
        )
        return region

    raise CropError("Could not detect a content region via brightness or edge detection.")


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
