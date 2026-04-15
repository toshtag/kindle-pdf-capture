"""Content-region detection for Kindle screenshots.

Extracts the book-body rectangle from a full Kindle window capture,
discarding UI chrome (macOS title bar, Kindle header band).

All functions operate on uint8 BGR ndarrays (OpenCV native format).

## Function map

  _find_titlebar_bottom(bgr, *, search_h)   -- Sobel scan for macOS title bar edge
  _find_header_bottom(bgr)                  -- std-dev scan for Kindle book-title band
  _has_dark_border(gray)                    -- guard: confirms dark Kindle chrome exists
  _detect_by_brightness(bgr, ...)           -- Phase-0 cover-rect detection (uses above)
  _clamp_region / _best_contour_region      -- geometry helpers for contour selection
  detect_content_region(bgr)               -- PUBLIC: main crop entry point
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (single source of truth — import these in tests to avoid
# duplicating magic numbers)
# ---------------------------------------------------------------------------

# Mean pixel value of the 10 rows immediately below the macOS title bar.
# Used by detect_content_region to distinguish reading-mode from cover/image.
#   Reading-mode Kindle header background: ~230-250  (above this threshold)
#   Cover chrome / dark illustration:       < 200    (below this threshold)
READING_MODE_MEAN_THRESHOLD: int = 200

# Sobel edge magnitude threshold for _find_titlebar_bottom.
_TITLEBAR_EDGE_THRESH: float = 20.0

# Row std-dev thresholds for _find_header_bottom.
#   >= _HEADER_TEXT_STD_MIN  → inside the book-title text block
#   <  _HEADER_QUIET_STD_MAX → uniform row (header ended here)
_HEADER_TEXT_STD_MIN: float = 10.0
_HEADER_QUIET_STD_MAX: float = 5.0

# Brightness threshold for _detect_by_brightness (Phase-0 cover detection).
# Kindle chrome background is ~16-17; page content is brighter.
_COVER_BRIGHTNESS_THRESHOLD: int = 20

# Fixed pixel offset added to header_y to clear any horizontal rule that may
# appear immediately below the book-title band.  Kindle places a 1-2 px rule
# there on some pages; adding this margin absorbs it without per-page detection.
_HEADER_RULE_MARGIN: int = 20


@dataclass
class ContentRegion:
    """Bounding rectangle of the detected book-body area.

    Coordinates follow OpenCV convention: origin at top-left,
    x -> right, y -> down.
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


def _find_titlebar_bottom(
    bgr: np.ndarray,
    *,
    search_fraction: float = 0.25,
    search_h: int | None = None,
    gray_strip: np.ndarray | None = None,
) -> int:
    """Return the y-coordinate of the macOS title bar bottom edge.

    Uses Sobel Y to find the last full-width horizontal edge in the search
    region.  The search region is either *search_h* rows (if provided) or
    the top *search_fraction* of the image.

    Pass ``search_h=60`` when the image contains Kindle chrome below the
    title bar (header bands, divider lines) that would otherwise be mistaken
    for the title bar boundary if included in the search region.  60 rows
    is always enough to capture the macOS title bar (~y=55) while keeping
    the Kindle header (~y=110+) outside the window.

    Args:
        bgr: Full BGR frame.
        search_fraction: Fraction of frame height to scan (used when search_h
            is None).
        search_h: Fixed number of rows to scan from the top.
        gray_strip: Pre-computed grayscale of the top *search_h* rows.  When
            provided the internal cvtColor call is skipped.

    Returns 0 if no full-width edge is found.
    """
    h_img, w_img = bgr.shape[:2]
    if search_h is None:
        search_h = max(1, int(h_img * search_fraction))
    else:
        search_h = max(1, min(search_h, h_img))

    if gray_strip is not None:
        gray = gray_strip
    else:
        gray = cv2.cvtColor(bgr[:search_h], cv2.COLOR_BGR2GRAY)
    sobel = cv2.Sobel(gray.astype(np.float64), cv2.CV_64F, 0, 1, ksize=3)
    abs_sobel = np.abs(sobel)

    edge_w = max(1, w_img // 20)  # leftmost / rightmost 5 %

    edge_mask = abs_sobel > _TITLEBAR_EDGE_THRESH
    row_density = edge_mask.sum(axis=1) / w_img
    left_density = edge_mask[:, :edge_w].sum(axis=1) / edge_w
    right_density = edge_mask[:, w_img - edge_w :].sum(axis=1) / edge_w

    boundary_rows = (row_density >= 0.50) & (left_density >= 0.50) & (right_density >= 0.50)
    indices = np.where(boundary_rows)[0]
    if len(indices) == 0:
        return 0
    return int(indices[-1]) + 1


def _find_header_bottom(bgr: np.ndarray, *, gray: np.ndarray | None = None) -> int:
    """Return the y-coordinate immediately after the Kindle book-title text block.

    The Kindle reading-mode header consists of (top to bottom):
      1. macOS title bar  -- detected by _find_titlebar_bottom(search_h=60).
      2. Uniform chrome band (light-gray background, no text).
      3. Book-title text  -- non-uniform rows (row std >= _HEADER_TEXT_STD_MIN).
      4. Divider / quiet band -- uniform again (row std < _HEADER_QUIET_STD_MAX).  <-- return here

    Scans up to 100 rows below the title bar for the text block, then
    returns the first quiet row after it.

    Args:
        bgr: Full BGR frame.
        gray: Pre-computed grayscale of *bgr*.  Passed by callers that already
            hold a grayscale copy to avoid a redundant cvtColor call.  When
            None the conversion is performed internally.

    Returns 0 if:
      - no title bar edge is found in the top 60 rows, or
      - no text block follows within 100 rows (non-reading-mode frame).
    """
    h_img = bgr.shape[0]
    if gray is None:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    search_h = min(60, h_img)
    gray_strip = gray[:search_h]
    titlebar_y = _find_titlebar_bottom(bgr, search_h=search_h, gray_strip=gray_strip)
    if titlebar_y == 0:
        logger.debug("_find_header_bottom: no title bar edge found")
        return 0

    search_end = min(titlebar_y + 100, h_img)

    # Vectorised std-dev computation across the scan rows (avoids per-row Python loop).
    rows = gray[titlebar_y:search_end].astype(np.float32)
    row_stds = rows.std(axis=1)

    title_block_started = False
    for i, row_std in enumerate(row_stds):
        if not title_block_started:
            if row_std >= _HEADER_TEXT_STD_MIN:
                title_block_started = True
        else:
            if row_std < _HEADER_QUIET_STD_MAX:
                y = titlebar_y + i
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

    Used exclusively as a pre-flight guard inside ``_detect_by_brightness``
    (Phase-0 cover detection).  It is NOT used by ``detect_content_region``
    -- that function switched to a brightness-sampling approach in v1.0.2
    because the dark border disappears after Phase-0 resizes the window.

    Two opposing edge strips (left+right OR top+bottom) must be predominantly
    dark (>= 80 % of pixels <= threshold) to return True.  This distinguishes
    the full Kindle chrome border from a thin macOS UI bar that only appears
    at the top.

    Pixel value ranges:
      - Kindle chrome background: ~16-17  (well below threshold=20)
      - Dark cover-page content:  ~40+    (above threshold, not flagged as chrome)
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
    """Find the cover-page rect by thresholding away the dark Kindle chrome.

    Used only in Phase 0 (window resize) to measure the book's natural page
    width from the cover frame.  At this point the Kindle window still has
    its original size and the cover page is surrounded by near-black chrome
    (pixel value ~16-17).

    Algorithm:
      1. _has_dark_border confirms that two opposing edges are dark.
         Returns None immediately if the border is absent (not a cover frame).
      2. Threshold at _COVER_BRIGHTNESS_THRESHOLD: everything brighter is page content.
      3. Morphological close (20x20) merges the page into one solid blob.
      4. Largest qualifying contour -> bounding box = page rect.

    Returns None when the dark border guard fails or no qualifying contour
    is found (e.g. pure-black frame).
    """
    h_img, w_img = bgr.shape[:2]
    total_area = h_img * w_img

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    if not _has_dark_border(gray):
        return None

    _, mask = cv2.threshold(gray, _COVER_BRIGHTNESS_THRESHOLD, 255, cv2.THRESH_BINARY)
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_content_region(
    bgr: np.ndarray,
    *,
    top_padding: int = 0,
) -> ContentRegion:
    """Detect the crop region for a Kindle screenshot.

    Decision flow
    -------------
    .. code-block:: text

        [frame]
           │
           ▼
        _find_titlebar_bottom(search_h=60)
           │   Sobel Y scan of top 60 rows only.
           │   Returns y just below the macOS title bar (~y=55).
           │   Fixed 60-row window keeps Kindle header (~y=110+) out of scope.
           │
           ├─ guard: gray_full.max() <= 20 ──► CropError (all-black frame)
           │
           ▼
        below_titlebar_mean  (mean of rows [titlebar_y : titlebar_y+10])
           │
           ├─ mean < READING_MODE_MEAN_THRESHOLD  ──► COVER / IMAGE PAGE
           │                  Dark Kindle chrome present; return full frame
           │                  from titlebar_y downward.
           │                  ContentRegion(x=0, y=titlebar_y, w=w, h=h-titlebar_y)
           │
           └─ mean >= READING_MODE_MEAN_THRESHOLD ──► READING-MODE PAGE (light-gray Kindle header)
                              │
                              ▼
                           _find_header_bottom(bgr)
                              │   _find_titlebar_bottom(search_h=60) to anchor,
                              │   then std-dev scan for book-title text block.
                              │   Returns first quiet row (std < _HEADER_QUIET_STD_MAX) after text.
                              │
                              ├─ header_y > 0 ──► NORMAL READING PAGE
                              │                   content_y = header_y + _HEADER_RULE_MARGIN
                              │                   ContentRegion(x=0, y=content_y, w=w, h=h-content_y)
                              │
                              └─ header_y == 0 ──► BRIGHT COVER / NO-HEADER PAGE
                                                   White cover or image page that passes
                                                   the mean threshold but has no title text.
                                                   Fall back to titlebar_y.
                                                   ContentRegion(x=0, y=titlebar_y, w=w, h=h-titlebar_y)

    Why READING_MODE_MEAN_THRESHOLD and not _has_dark_border?
    ----------------------------------------------------------
    After Phase 0 resizes the window the dark chrome gutters disappear, so
    _has_dark_border would always return False for subsequent pages.  Instead
    we sample the 10 rows immediately below the macOS title bar:
      - Reading-mode header background: ~230-250 (very light gray)
      - Cover chrome / dark illustration: < 200
    READING_MODE_MEAN_THRESHOLD (200) sits safely between these two bands
    for all tested books.

    Args:
        bgr: uint8 BGR ndarray (OpenCV format).
        top_padding: Extra rows to include above header_y (default 0).

    Returns:
        ContentRegion describing the crop area.

    Raises:
        CropError: Only if the frame is entirely black.
    """
    h_img, w_img = bgr.shape[:2]
    gray_full = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    if float(gray_full.max()) <= 20:
        logger.debug("All-black frame; skipping all passes.")
        raise CropError("Frame is all-black — screen recording may be blocked.")

    # Compute the search-strip grayscale once and pass it to both callers that
    # need the top-60-row Sobel scan, avoiding repeated cvtColor on the same data.
    search_h = min(60, h_img)
    gray_strip = gray_full[:search_h]

    titlebar_y = _find_titlebar_bottom(bgr, search_h=search_h, gray_strip=gray_strip)

    below_titlebar_mean = (
        float(gray_full[titlebar_y : titlebar_y + 10].mean()) if titlebar_y < h_img else 255.0
    )
    is_reading_mode = below_titlebar_mean >= READING_MODE_MEAN_THRESHOLD

    if not is_reading_mode:
        logger.debug(
            "Cover/image page (below-titlebar mean=%.1f): returning full frame from y=%d.",
            below_titlebar_mean,
            titlebar_y,
        )
        return ContentRegion(x=0, y=titlebar_y, w=w_img, h=h_img - titlebar_y)

    header_y = _find_header_bottom(bgr, gray=gray_full)
    if header_y > 0:
        content_y = header_y + _HEADER_RULE_MARGIN
        logger.debug(
            "Reading-mode page: returning full-width rect at y=%d (header_y=%d, titlebar_y=%d).",
            content_y,
            header_y,
            titlebar_y,
        )
        return ContentRegion(x=0, y=content_y, w=w_img, h=h_img - content_y)

    logger.debug(
        "No header found (mean=%.1f): returning full frame from y=%d.",
        below_titlebar_mean,
        titlebar_y,
    )
    return ContentRegion(x=0, y=titlebar_y, w=w_img, h=h_img - titlebar_y)
