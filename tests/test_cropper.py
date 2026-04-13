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
