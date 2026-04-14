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


def _find_titlebar_bottom(bgr: np.ndarray, *, search_fraction: float = 0.25) -> int:
    """Return the y-coordinate of the macOS title bar bottom edge only.

    Uses Sobel Y to find the last full-width horizontal edge in the top
    *search_fraction* of the image.  This is the boundary between the macOS
    title bar and whatever is below (Kindle chrome, header band, or content).

    Returns 0 if no such edge is found.
    """
    h_img, w_img = bgr.shape[:2]
    search_h = max(1, int(h_img * search_fraction))

    gray = cv2.cvtColor(bgr[:search_h], cv2.COLOR_BGR2GRAY)

    sobel = cv2.Sobel(gray.astype(np.float64), cv2.CV_64F, 0, 1, ksize=3)
    abs_sobel = np.abs(sobel)

    edge_thresh = 20.0
    edge_w = max(1, w_img // 20)  # leftmost / rightmost 5%

    edge_mask = abs_sobel > edge_thresh
    row_density = edge_mask.sum(axis=1) / w_img
    left_density = edge_mask[:, :edge_w].sum(axis=1) / edge_w
    right_density = edge_mask[:, w_img - edge_w :].sum(axis=1) / edge_w

    min_span = 0.50
    min_edge_span = 0.50
    boundary_rows = (
        (row_density >= min_span)
        & (left_density >= min_edge_span)
        & (right_density >= min_edge_span)
    )

    indices = np.where(boundary_rows)[0]
    if len(indices) == 0:
        return 0

    return int(indices[-1]) + 1


def _find_header_bottom(bgr: np.ndarray) -> int:
    """Return the y-coordinate immediately after the Kindle book-title text block.

    The Kindle reading-mode header consists of:
      1. macOS title bar — detected by _find_titlebar_bottom (Sobel Y peak).
      2. A short uniform-background band (Kindle chrome).
      3. The book title text (non-uniform rows, centered only).

    This function locates the macOS title bar bottom, then scans downward
    (up to 100 rows) for the first non-uniform band (std >= 10), which is the
    book-title text.  It returns the first uniform row (std < 5) after that
    text block — the point where Kindle chrome ends and book content begins.

    Returns 0 if:
      - no macOS title bar is detected (titlebar_y == 0), or
      - no non-uniform block follows the title bar within 100 rows.
    """
    # Use a narrow search window (top 10%) so that Kindle chrome elements
    # below the macOS title bar (divider lines, header bands) are excluded
    # from the title-bar detection step.
    titlebar_y = _find_titlebar_bottom(bgr, search_fraction=0.10)
    if titlebar_y == 0:
        return 0

    h_img = bgr.shape[0]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    search_end = min(titlebar_y + 100, h_img)
    title_block_started = False

    for y in range(titlebar_y, search_end):
        row_std = float(gray[y].std())
        if not title_block_started:
            if row_std >= 10.0:
                title_block_started = True
        else:
            if row_std < 5.0:
                logger.debug("Header bottom at y=%d (titlebar_y=%d)", y, titlebar_y)
                return y

    logger.debug("No header bottom found after titlebar_y=%d", titlebar_y)
    return 0


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


def _has_dark_border(gray: np.ndarray, *, border_width: int = 20, threshold: int = 20) -> bool:
    """Return True when the image has a dark frame on at least two opposite sides.

    Kindle wraps the page in a near-black background.  Checking that two
    opposing edge strips (left+right or top+bottom) are predominantly dark
    distinguishes a Kindle chrome border from a thin UI bar that only appears
    at the top of the image.

    The threshold is set to 20 to capture Kindle chrome (typical value ~16-17)
    while remaining below standard dark cover-page content (value ~40+).
    """
    h, w = gray.shape
    bw = min(border_width, w // 4, h // 4)

    def _dark(strip: np.ndarray) -> bool:
        return float((strip <= threshold).sum()) / strip.size > 0.80

    return (_dark(gray[:, :bw]) and _dark(gray[:, w - bw :])) or (
        _dark(gray[:bw, :]) and _dark(gray[h - bw :, :])
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

    # Use a threshold that captures dark cover pages (value ~40+) while
    # excluding Kindle chrome (value ~16-17).  Threshold 20 sits between them.
    _, mask = cv2.threshold(gray, 20, 255, cv2.THRESH_BINARY)

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

    For bright reading-mode pages, text lines produce many small, scattered
    edge contours.  A large dilation kernel merges them into one coherent blob
    before bounding-box extraction.

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

    # Use a wide kernel to bridge gaps between scattered text-line edges so
    # that all text content merges into a single contour blob.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 20))
    dilated = cv2.dilate(edges, kernel, iterations=3)

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
    top_padding: int = 40,
) -> ContentRegion:
    """Detect the main text-body region in a Kindle screenshot.

    Three-pass strategy:

    1. **Full-width page rect** (reading mode): when a Kindle header is
       detected but no dark chrome border surrounds the image, the entire
       area below the header is the page.  Returning the full frame width
       ensures all reading-mode pages produce the same output size regardless
       of how much text is on the page or where the text margins sit.

    2. **Brightness pass**: threshold pixels above the near-black Kindle
       background to isolate the page blob.  Works for cover pages and
       embedded-chrome layouts where the page is brighter than the surrounding
       chrome frame.

    3. **Edge-detection fallback**: used when the brightness pass yields no
       qualifying region (e.g. the entire image is bright with no dark border
       and no header was detected).

    Args:
        bgr: uint8 BGR ndarray (OpenCV format).
        margin: Pixels to expand the detected bounding box on each side.
        min_area_ratio: Minimum fraction of total image area a candidate
            must cover to be considered valid.
        top_padding: Extra rows to keep above the content start when
            returning a full-width reading-mode rect.  Provides a small
            visual margin at the top of each cropped page.

    Returns:
        ContentRegion describing the detected body area.

    Raises:
        CropError: If no suitable region is found.
    """
    h_img, w_img = bgr.shape[:2]

    gray_full = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Guard: all-black frame (screen recording blocked) — raise CropError below.
    if float(gray_full.max()) <= 20:
        logger.debug("All-black frame; skipping all passes.")
        raise CropError("Frame is all-black — screen recording may be blocked.")

    # Step 1: locate the macOS title bar bottom edge (Sobel only, no header scan).
    # Use a narrow search window (top 10%) so that Kindle chrome elements such
    # as header divider lines are not mistaken for the macOS title bar boundary.
    titlebar_y = _find_titlebar_bottom(bgr, search_fraction=0.10)

    # Step 2: decide whether to also strip the Kindle reading-mode header band.
    # If the row immediately below the title bar is bright (mean ≥ 200), this is
    # a reading-mode page with a light-gray Kindle header that must be stripped.
    # If it is dark (cover chrome, image page), return the full frame from
    # titlebar_y — the dark area is content and must not be trimmed further.
    below_titlebar_mean = (
        float(gray_full[titlebar_y : titlebar_y + 10].mean()) if titlebar_y < h_img else 255.0
    )
    is_reading_mode = below_titlebar_mean >= 200

    if not is_reading_mode:
        # Cover / image page: return everything below the title bar.
        logger.debug(
            "Cover/image page (below-titlebar mean=%.1f): returning full frame from y=%d.",
            below_titlebar_mean,
            titlebar_y,
        )
        return ContentRegion(x=0, y=titlebar_y, w=w_img, h=h_img - titlebar_y)

    # Reading-mode page: also strip the Kindle header band (title text + divider).
    header_y = _find_header_bottom(bgr)
    if header_y > 0:
        body = bgr[header_y:]
        logger.debug("Stripped header: %d rows removed from top.", header_y)
    else:
        body = bgr

    if header_y > 0:
        # Pad upward from header_y, but never above the macOS title bar bottom.
        safe_padding = min(top_padding, header_y - titlebar_y, header_y // 2)
        content_y = max(titlebar_y, header_y - safe_padding)
        logger.debug(
            "Reading-mode page: returning full-width rect at y=%d (header_y=%d, titlebar_y=%d, padding=%d).",
            content_y,
            header_y,
            titlebar_y,
            safe_padding,
        )
        return ContentRegion(x=0, y=content_y, w=w_img, h=h_img - content_y)

    region = _detect_by_brightness(body, margin=margin, min_area_ratio=min_area_ratio)
    if region is not None:
        # Shift y back to original image coordinates
        region = ContentRegion(x=region.x, y=region.y + header_y, w=region.w, h=region.h)
        logger.debug(
            "Content region (brightness): x=%d y=%d w=%d h=%d",
            region.x,
            region.y,
            region.w,
            region.h,
        )
        return region

    logger.debug("Brightness pass found nothing; trying edge detection.")
    region = _detect_by_edges(body, margin=margin, min_area_ratio=min_area_ratio)
    if region is not None:
        region = ContentRegion(x=region.x, y=region.y + header_y, w=region.w, h=region.h)
        logger.debug(
            "Content region (edges): x=%d y=%d w=%d h=%d",
            region.x,
            region.y,
            region.w,
            region.h,
        )
        return region

    # Last resort: if a header was detected, return the entire area below it.
    # This preserves the header-stripping benefit even when content detection
    # cannot isolate a precise bounding box.
    if header_y > 0:
        safe_padding = min(top_padding, header_y - titlebar_y, header_y // 2)
        content_y = max(titlebar_y, header_y - safe_padding)
        logger.debug(
            "Both passes failed; returning full area below header (y=%d, titlebar_y=%d, padding=%d).",
            header_y,
            titlebar_y,
            safe_padding,
        )
        return ContentRegion(x=0, y=content_y, w=w_img, h=h_img - content_y)

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
