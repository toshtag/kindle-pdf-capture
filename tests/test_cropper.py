"""Tests for the content-region detection (cropper) module.

Fixtures use synthetic images built with numpy/Pillow to avoid any
dependency on real Kindle screenshots.

Coordinate system: (x, y, w, h) — OpenCV convention.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from kindle_pdf_capture.cropper import (
    ContentRegion,
    CropError,
    _find_header_bottom,
    detect_content_region,
    fallback_crop,
)

# ---------------------------------------------------------------------------
# Helpers: synthetic image builders
# ---------------------------------------------------------------------------


def _make_white_canvas(width: int = 1200, height: int = 900) -> np.ndarray:
    """Return a uint8 BGR image filled with white."""
    return np.full((height, width, 3), 255, dtype=np.uint8)


def _draw_text_block(
    img: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    line_height: int = 12,
    line_gap: int = 6,
) -> np.ndarray:
    """Simulate a text block by drawing black horizontal lines inside a rect."""
    result = img.copy()
    for row_y in range(y, y + h, line_height + line_gap):
        result[row_y : row_y + line_height, x : x + w] = 0
    return result


def _pil_to_bgr(pil_image: Image.Image) -> np.ndarray:
    rgb = np.array(pil_image.convert("RGB"))
    return rgb[:, :, ::-1].copy()


# ---------------------------------------------------------------------------
# ContentRegion dataclass
# ---------------------------------------------------------------------------


class TestContentRegion:
    def test_fields(self) -> None:
        r = ContentRegion(x=10, y=20, w=800, h=600)
        assert r.x == 10
        assert r.y == 20
        assert r.w == 800
        assert r.h == 600

    def test_area(self) -> None:
        r = ContentRegion(x=0, y=0, w=100, h=50)
        assert r.area == 5000

    def test_slice(self) -> None:
        """slice() should return (y_slice, x_slice) for numpy indexing."""
        r = ContentRegion(x=10, y=20, w=80, h=60)
        ys, xs = r.slice()
        assert ys == slice(20, 80)
        assert xs == slice(10, 90)


# ---------------------------------------------------------------------------
# detect_content_region: happy path
# ---------------------------------------------------------------------------


class TestDetectContentRegion:
    def test_detects_central_text_block(self) -> None:
        """A white image with a central text block should be detected."""
        img = _make_white_canvas(1200, 900)
        # Text block in the centre — roughly 80% of the canvas
        img = _draw_text_block(img, x=100, y=80, w=1000, h=740)

        region = detect_content_region(img)

        # Detected region should cover the drawn text block (with some margin)
        assert region.x <= 120
        assert region.y <= 100
        assert region.x + region.w >= 1080
        assert region.y + region.h >= 800

    def test_detected_region_covers_at_least_20pct_of_image(self) -> None:
        img = _make_white_canvas(1200, 900)
        img = _draw_text_block(img, x=100, y=80, w=1000, h=740)

        region = detect_content_region(img)

        total = 1200 * 900
        assert region.area >= total * 0.20

    def test_ui_elements_at_top_excluded(self) -> None:
        """Thin UI bar at top (< 5% height) should not dominate the result."""
        img = _make_white_canvas(1200, 900)
        # Title bar — thin strip at top
        img[0:30, :] = 50
        # Main text block
        img = _draw_text_block(img, x=80, y=60, w=1040, h=800)

        region = detect_content_region(img)

        # Result top should NOT be at pixel 0 (UI bar excluded)
        assert region.y > 0

    def test_returns_content_region_instance(self) -> None:
        img = _make_white_canvas()
        img = _draw_text_block(img, x=100, y=80, w=1000, h=740)
        region = detect_content_region(img)
        assert isinstance(region, ContentRegion)

    def test_margin_applied(self) -> None:
        """detect_content_region accepts an optional margin parameter."""
        img = _make_white_canvas(1200, 900)
        img = _draw_text_block(img, x=200, y=150, w=800, h=600)

        r_no_margin = detect_content_region(img, margin=0)
        r_with_margin = detect_content_region(img, margin=20)

        # With margin, region should be at least as large
        assert r_with_margin.x <= r_no_margin.x
        assert r_with_margin.y <= r_no_margin.y

    def test_accepts_bgr_array(self) -> None:
        """Input must be a uint8 BGR ndarray (standard OpenCV format)."""
        img = _make_white_canvas()
        img = _draw_text_block(img, x=100, y=80, w=1000, h=740)
        assert img.dtype == np.uint8
        assert img.ndim == 3
        detect_content_region(img)  # should not raise


# ---------------------------------------------------------------------------
# detect_content_region: edge cases
# ---------------------------------------------------------------------------


class TestDetectContentRegionEdgeCases:
    def test_blank_image_raises_crop_error(self) -> None:
        """A completely white image has no detectable content."""
        img = _make_white_canvas()
        with pytest.raises(CropError):
            detect_content_region(img)

    def test_all_black_image_raises_crop_error(self) -> None:
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        with pytest.raises(CropError):
            detect_content_region(img)

    def test_region_clipped_to_image_bounds(self) -> None:
        """Margin must not produce a region outside the image."""
        img = _make_white_canvas(1200, 900)
        # Text almost touching every edge
        img = _draw_text_block(img, x=2, y=2, w=1196, h=896)

        region = detect_content_region(img, margin=50)

        assert region.x >= 0
        assert region.y >= 0
        assert region.x + region.w <= 1200
        assert region.y + region.h <= 900


# ---------------------------------------------------------------------------
# detect_content_region: Kindle black-border layout
# ---------------------------------------------------------------------------


class TestDetectContentRegionKindleLayout:
    def test_detects_page_inside_black_border(self) -> None:
        """White page centred in a black Kindle window should be detected.

        Kindle surrounds the book page with a black background.  The cropper
        must isolate the bright page area, not the entire window.
        """
        # 1200x900 black canvas
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        # White page occupying the central ~70% of the window
        px, py, pw, ph = 180, 90, 840, 720
        img[py : py + ph, px : px + pw] = 240

        region = detect_content_region(img)

        # The detected region must be inside the page, not the black border
        assert region.x >= 0
        assert region.y >= 0
        # Should not extend into the black border on either side by more than
        # the expansion margin (15 px default)
        assert region.x <= px + 20
        assert region.y <= py + 20
        assert region.x + region.w >= px + pw - 20
        assert region.y + region.h >= py + ph - 20

    def test_dark_cover_page_inside_black_border(self) -> None:
        """A dark (non-white) cover page inside a black border must not raise.

        Cover pages may be dark-brown / dark-coloured.  As long as there is
        a meaningful brightness difference between the page and the Kindle
        chrome, cropping should succeed.
        """
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        # Dark-brown cover page — value ~40, clearly brighter than pure black (0)
        px, py, pw, ph = 180, 90, 840, 720
        img[py : py + ph, px : px + pw] = 40

        # Must not raise — a dark cover is still a valid page
        region = detect_content_region(img)
        assert isinstance(region, ContentRegion)

    def test_black_border_excluded_from_region(self) -> None:
        """The detected region must not start at x=0 when there is a black border."""
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        # White page with clear black borders on left and right
        img[0:900, 150:1050] = 240

        region = detect_content_region(img)

        # x must be > 0; the black left border should be excluded
        assert region.x > 0


# ---------------------------------------------------------------------------
# fallback_crop
# ---------------------------------------------------------------------------


class TestFallbackCrop:
    def test_trims_fixed_fraction(self) -> None:
        """fallback_crop removes a fraction from each edge."""
        img = _make_white_canvas(1200, 900)
        region = fallback_crop(img, fraction=0.05)

        # 5% of 1200 = 60px from left/right → x=60, w=1080
        assert region.x == pytest.approx(60, abs=2)
        assert region.y == pytest.approx(45, abs=2)  # 5% of 900
        assert region.w == pytest.approx(1080, abs=2)
        assert region.h == pytest.approx(810, abs=2)

    def test_returns_content_region(self) -> None:
        img = _make_white_canvas()
        result = fallback_crop(img)
        assert isinstance(result, ContentRegion)

    def test_default_fraction_is_sensible(self) -> None:
        """Default fraction should crop at least 2% per side."""
        img = _make_white_canvas(1200, 900)
        region = fallback_crop(img)
        assert region.x >= 24  # ≥ 2% of 1200
        assert region.y >= 18  # ≥ 2% of 900

    def test_zero_fraction_returns_full_image(self) -> None:
        img = _make_white_canvas(1200, 900)
        region = fallback_crop(img, fraction=0.0)
        assert region.x == 0
        assert region.y == 0
        assert region.w == 1200
        assert region.h == 900


# ---------------------------------------------------------------------------
# Helpers: synthetic Kindle window images with chrome
# ---------------------------------------------------------------------------


def _make_kindle_window_with_header(
    width: int = 1200,
    height: int = 900,
    title_bar_height: int = 56,
    header_height: int = 40,
    divider_thickness: int = 2,
) -> tuple[np.ndarray, int]:
    """Build a synthetic Kindle window with macOS title bar and Kindle header.

    Returns (bgr_image, expected_content_start_y).
    The layout from top to bottom:
      1. macOS title bar (gray)
      2. Kindle header area (light gray, simulates book title text)
      3. Horizontal divider line (dark, full width)
      4. White content area with simulated text
    """
    img = np.full((height, width, 3), 255, dtype=np.uint8)

    # macOS title bar: dark gray
    img[:title_bar_height, :] = 80

    # Kindle header: light gray with some "text" (darker pixels)
    header_top = title_bar_height
    header_bottom = header_top + header_height
    img[header_top:header_bottom, :] = 230
    # Simulate book title text in the center of the header
    text_y = header_top + 10
    img[text_y : text_y + 14, width // 4 : 3 * width // 4] = 60

    # Horizontal divider line (dark, spanning full width)
    divider_y = header_bottom
    img[divider_y : divider_y + divider_thickness, :] = 30

    content_start = divider_y + divider_thickness

    # Content area: white with text blocks
    img = _draw_text_block(
        img, x=80, y=content_start + 20, w=width - 160, h=height - content_start - 60
    )

    return img, content_start


# ---------------------------------------------------------------------------
# Helpers: real-world Kindle window layouts
# ---------------------------------------------------------------------------


def _make_reading_mode_page(
    width: int = 2240,
    height: int = 2358,
    title_bar_height: int = 56,
    header_height: int = 44,
    divider_thickness: int = 2,
) -> tuple[np.ndarray, int]:
    """Build a synthetic Kindle reading-mode page (Retina 2x, mostly white).

    Layout (top to bottom):
      1. macOS title bar (light gray, value ~210)
      2. Kindle header (light gray, book title text in center only)
      3. Thin horizontal divider (dark gray, value ~30, spanning full width)
      4. White content area with centered text block

    The title bar and header are light-colored (not dark), matching real
    captures where Kindle is in light mode.  The divider is the only
    full-width dark band in the top 25% of the image.

    Returns (bgr_image, expected_content_start_y).
    """
    img = np.full((height, width, 3), 255, dtype=np.uint8)

    # macOS title bar: light gray (not dark — matches real Kindle in light mode)
    img[:title_bar_height, :] = 210

    # Kindle header: light gray with book title text only in center region
    header_top = title_bar_height
    header_bottom = header_top + header_height
    img[header_top:header_bottom, :] = 220
    # Book title text: dark, but only in center (not reaching edges)
    title_x_start = width // 3
    title_x_end = 2 * width // 3
    text_y = header_top + 12
    img[text_y : text_y + 16, title_x_start:title_x_end] = 40

    # Divider: dark, full width (this is what we detect)
    divider_y = header_bottom
    img[divider_y : divider_y + divider_thickness, :] = 30

    content_start = divider_y + divider_thickness

    # Content: white with text block indented from both sides
    # Text spans only inner 70% of width (realistic margin)
    text_x = int(width * 0.15)
    text_w = int(width * 0.70)
    img = _draw_text_block(
        img, x=text_x, y=content_start + 30, w=text_w, h=height - content_start - 80
    )

    return img, content_start


def _make_dark_chrome_page(
    width: int = 2240,
    height: int = 2358,
    chrome_border: int = 60,
) -> tuple[np.ndarray, int]:
    """Build a synthetic Kindle dark-chrome layout (book cover / embed mode).

    Layout: near-black chrome surrounds all four sides of the image, with the
    book page embedded as a bright rectangle in the center.  This matches real
    Kindle captures where the chrome forms a border frame rather than just a
    top band.

    The chrome value (16) is slightly above the old threshold (15) but below
    the new threshold (20), so it will now be correctly masked out.
    """
    img = np.zeros((height, width, 3), dtype=np.uint8)

    # Near-black chrome on all four sides (value ~16, matches real captures)
    img[:, :] = 16

    # White page content in the center (inset by chrome_border on each side)
    content_y = chrome_border
    content_x = chrome_border
    content_h = height - 2 * chrome_border
    content_w = width - 2 * chrome_border
    img[content_y : content_y + content_h, content_x : content_x + content_w] = 240

    # Text in content area, indented further from page edges
    text_x = content_x + int(content_w * 0.10)
    text_w = int(content_w * 0.80)
    img = _draw_text_block(img, x=text_x, y=content_y + 30, w=text_w, h=content_h - 60)

    return img, content_y


# ---------------------------------------------------------------------------
# _find_header_bottom
# ---------------------------------------------------------------------------


class TestFindHeaderBottom:
    def test_detects_divider_line(self) -> None:
        """Should detect the horizontal divider line and return its bottom y."""
        img, expected_y = _make_kindle_window_with_header()
        result = _find_header_bottom(img)
        # Allow small tolerance (a few pixels)
        assert abs(result - expected_y) <= 5

    def test_returns_zero_for_no_header(self) -> None:
        """An image with no header/divider should return 0."""
        img = _make_white_canvas(1200, 900)
        img = _draw_text_block(img, x=80, y=40, w=1040, h=820)
        result = _find_header_bottom(img)
        assert result == 0

    def test_returns_zero_for_black_bordered_kindle(self) -> None:
        """Kindle dark-mode layout (black border, white page) has no header divider."""
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        img[90:810, 180:1020] = 240
        result = _find_header_bottom(img)
        assert result == 0

    def test_thick_divider(self) -> None:
        """Should work with a thicker divider line (e.g. 4px)."""
        img, expected_y = _make_kindle_window_with_header(divider_thickness=4)
        result = _find_header_bottom(img)
        assert abs(result - expected_y) <= 6

    def test_different_window_sizes(self) -> None:
        """Should work regardless of window dimensions."""
        for w, h in [(800, 600), (1600, 1200), (2560, 1600)]:
            img, expected_y = _make_kindle_window_with_header(width=w, height=h)
            result = _find_header_bottom(img)
            assert abs(result - expected_y) <= 5, (
                f"Failed for {w}x{h}: got {result}, expected ~{expected_y}"
            )

    def test_detects_divider_in_light_mode_reading_page(self) -> None:
        """Real-world reading mode: light-gray title bar + thin dark divider.

        The title bar and header are light-colored (not dark).  The only full-
        width dark band in the top 25% is the thin horizontal divider between
        the Kindle header and the book content.
        """
        img, expected_y = _make_reading_mode_page()
        result = _find_header_bottom(img)
        assert abs(result - expected_y) <= 5, (
            f"Reading-mode divider: got {result}, expected ~{expected_y}"
        )

    def test_returns_zero_for_dark_chrome_page(self) -> None:
        """Dark-chrome layout has no thin divider in top 25%; should return 0.

        The entire top portion is near-black chrome (hundreds of rows).
        _find_header_bottom should NOT try to strip it — the brightness
        pass in detect_content_region handles this case instead.
        """
        img, _ = _make_dark_chrome_page()
        result = _find_header_bottom(img)
        assert result == 0

    def test_text_content_not_mistaken_for_divider(self) -> None:
        """Text lines must NOT be detected as divider lines.

        Text content is indented and does NOT span the full width including
        both left and right edge strips.
        """
        img = _make_white_canvas(2240, 2358)
        # Text block spanning only 70% of width (indented, realistic)
        text_x = int(2240 * 0.15)
        text_w = int(2240 * 0.70)
        img = _draw_text_block(img, x=text_x, y=100, w=text_w, h=2000)
        result = _find_header_bottom(img)
        assert result == 0, f"Text incorrectly detected as divider; got {result}"

    def test_skips_kindle_header_band_with_title_text(self) -> None:
        """_find_header_bottom must skip the full Kindle header band.

        Real-world reading pages have:
          1. macOS title bar (white, rows 0-55)
          2. Full-width Sobel Y edge at title-bar/header boundary (rows 55-56)
          3. Kindle header background (uniform gray, rows 57-107)
          4. Book title text in center (rows 108-128, non-uniform)
          5. Kindle header background again (uniform gray, rows 129-183)
          6. Book content starts (rows 184+, non-uniform)

        The function must return the start of book content (~184), not just
        row 57 (the first row after the Sobel boundary). The header band
        (rows 57-183), which includes "ロードマップ (JAPANESE EDITION)", must
        be fully stripped.

        The key constraint: rows 183-184 do NOT produce a full-width Sobel
        edge (the transition from uniform gray to book text is gradual and the
        text is indented), so the boundary-detection Sobel Y step alone
        returns row 57 as content_start for this layout.  The implementation
        must use a secondary strategy (e.g. skipping uniform header-background
        rows) to advance past the header band.
        """
        # Build the real-world layout synthetically.
        # IMPORTANT: rows 183→184 must NOT create a full-width Sobel Y edge.
        # In the real Kindle, the header-band-to-content transition is gradual:
        # the gray background simply continues and sparse indented text starts
        # appearing — no abrupt full-width step-change at rows 183-184.
        # We achieve this by keeping the same gray (222) value throughout rows
        # 57-194 and placing text on top of it starting at row 195.
        width, height = 2240, 2358

        # Start with uniform light gray so rows 57-194 have no color step
        img = np.full((height, width, 3), 222, dtype=np.uint8)

        # macOS title bar: white (rows 0-55)
        img[:55, :] = 255

        # Full-width boundary band at rows 55-56 (Sobel Y detects this)
        img[55:57, :] = 180  # abrupt brightness step across full width

        # Kindle header band 1 (57-107) and band 2 (128-183): already gray(222)

        # Book title text (centered only, does NOT reach left/right edges)
        title_x = width // 4
        title_w = width // 2
        img[108:128, title_x : title_x + title_w] = 40  # dark text (centered only)

        # Book content: rows 184+ with indented text on gray background.
        # Rows 183→184 stay at gray(222) — no full-width Sobel Y edge here.
        text_x = int(width * 0.15)  # 15% indent
        text_w_val = int(width * 0.70)  # 70% of width (never reaching edge strips)
        img = _draw_text_block(img, x=text_x, y=195, w=text_w_val, h=height - 300)

        result = _find_header_bottom(img)

        # Must return the start of book content (184+), NOT row 57 (which is
        # the first row after the detected Sobel boundary).
        assert result >= 180, (
            f"Expected content start >= 180 (full header band stripped), got {result}. "
            "The implementation must skip the uniform header-background rows "
            "after the Sobel boundary edge."
        )
        assert result <= 220, (
            f"Expected content start <= 220, got {result} (overshot into book content)"
        )


# ---------------------------------------------------------------------------
# detect_content_region: header stripping integration
# ---------------------------------------------------------------------------


class TestDetectContentRegionWithHeader:
    def test_excludes_title_bar_and_header(self) -> None:
        """detect_content_region should exclude macOS title bar and Kindle header."""
        img, content_start = _make_kindle_window_with_header()
        region = detect_content_region(img)

        # The detected region's top should be at or below the content start
        assert region.y >= content_start - 5

    def test_content_region_does_not_include_title_bar(self) -> None:
        """The detected region must not start in the title bar area (y < 56)."""
        img, _ = _make_kindle_window_with_header(title_bar_height=56)
        region = detect_content_region(img)
        assert region.y >= 50  # Should be well below the title bar

    def test_still_works_without_header(self) -> None:
        """Regular images (no header) should still work as before."""
        img = _make_white_canvas(1200, 900)
        img = _draw_text_block(img, x=100, y=80, w=1000, h=740)
        region = detect_content_region(img)
        assert region.y <= 100
        assert region.area >= 1200 * 900 * 0.20

    def test_real_world_reading_mode_excludes_header(self) -> None:
        """Real-world reading mode: header must be stripped before content detection.

        Retina-scale (2240x2358), light-gray title bar, thin dark divider.
        The content region must start below the divider.
        """
        img, content_start = _make_reading_mode_page()
        region = detect_content_region(img)
        # Must not include the Kindle header area
        assert region.y >= content_start - 5, (
            f"Header not stripped: region.y={region.y}, content_start={content_start}"
        )

    def test_real_world_reading_mode_does_not_raise(self) -> None:
        """detect_content_region must not raise CropError for reading-mode pages.

        Previously, mostly-white pages with no dark border caused Canny thresholds
        to be too high (~165-255), resulting in CropError.
        """
        img, _ = _make_reading_mode_page()
        # Must not raise
        region = detect_content_region(img)
        assert isinstance(region, ContentRegion)

    def test_dark_chrome_page_does_not_raise(self) -> None:
        """detect_content_region must not raise for dark-chrome (cover/embed) pages.

        The Kindle chrome has value ~16, just above the threshold=15 cutoff.
        The page content is brighter and must be detected correctly.
        """
        img, content_start = _make_dark_chrome_page()
        # Must not raise
        region = detect_content_region(img)
        assert isinstance(region, ContentRegion)
        # Content region must be below or at chrome boundary
        assert region.y >= content_start - 20, (
            f"Chrome included: region.y={region.y}, content_start={content_start}"
        )

    def test_reading_mode_returns_full_width_page_rect(self) -> None:
        """Reading-mode pages (no dark chrome) must return the full-width page rect.

        Real-world reading pages have no dark border — the entire area below the
        Kindle header is the page content.  detect_content_region must return a
        region that spans (nearly) the full image width, NOT just the text block
        width, so that all pages produce the same-size output image regardless of
        how much text is on the page.

        Previously, the edge-detection pass returned a narrow text-block bounding
        box, causing output width to vary from page to page.
        """
        img, content_start = _make_reading_mode_page()
        h_img, w_img = img.shape[:2]

        region = detect_content_region(img)

        # Width must be close to full image width — at most 10% narrower.
        assert region.w >= w_img * 0.90, (
            f"Expected full-width region (>= {w_img * 0.90:.0f}px), "
            f"got region.w={region.w} (image width={w_img})"
        )
        # Must still start below the header
        assert region.y >= content_start - 5
