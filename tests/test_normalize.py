"""Tests for the image normalisation module."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from kindle_pdf_capture.normalize import (
    normalize_image,
    save_jpeg,
    sharpen,
    whiten_background,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bgr(width: int = 800, height: int = 600, fill: int = 255) -> np.ndarray:
    return np.full((height, width, 3), fill, dtype=np.uint8)


def _grey_bgr(width: int = 800, height: int = 600, grey: int = 220) -> np.ndarray:
    """Return a slightly grey image to test whitening."""
    return np.full((height, width, 3), grey, dtype=np.uint8)


# ---------------------------------------------------------------------------
# normalize_image
# ---------------------------------------------------------------------------


class TestNormalizeImage:
    def test_output_width_matches_target(self) -> None:
        img = _bgr(1200, 900)
        result = normalize_image(img, resize_width=800)
        assert result.shape[1] == 800

    def test_aspect_ratio_preserved(self) -> None:
        img = _bgr(1200, 900)
        result = normalize_image(img, resize_width=600)
        expected_height = round(900 * 600 / 1200)
        assert abs(result.shape[0] - expected_height) <= 1

    def test_output_is_uint8(self) -> None:
        img = _bgr()
        result = normalize_image(img, resize_width=400)
        assert result.dtype == np.uint8

    def test_output_is_3channel(self) -> None:
        img = _bgr()
        result = normalize_image(img, resize_width=400)
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_same_width_no_scaling(self) -> None:
        img = _bgr(800, 600)
        result = normalize_image(img, resize_width=800)
        assert result.shape[1] == 800
        assert result.shape[0] == 600

    def test_upscale_allowed(self) -> None:
        """resize_width larger than original is allowed."""
        img = _bgr(400, 300)
        result = normalize_image(img, resize_width=800)
        assert result.shape[1] == 800


# ---------------------------------------------------------------------------
# whiten_background
# ---------------------------------------------------------------------------


class TestWhitenBackground:
    def test_near_white_becomes_white(self) -> None:
        """Pixels brighter than threshold should be pushed to 255."""
        img = _grey_bgr(grey=230)
        result = whiten_background(img, threshold=200)
        assert result.max() == 255

    def test_dark_pixels_unchanged(self) -> None:
        """Pixels below threshold (text) must not be altered."""
        img = np.full((100, 100, 3), 50, dtype=np.uint8)
        result = whiten_background(img, threshold=200)
        assert result.max() <= 50

    def test_output_same_shape(self) -> None:
        img = _bgr(400, 300)
        result = whiten_background(img)
        assert result.shape == img.shape

    def test_output_is_uint8(self) -> None:
        img = _bgr()
        assert whiten_background(img).dtype == np.uint8


# ---------------------------------------------------------------------------
# sharpen
# ---------------------------------------------------------------------------


class TestSharpen:
    def test_output_same_shape_and_dtype(self) -> None:
        img = _bgr()
        result = sharpen(img)
        assert result.shape == img.shape
        assert result.dtype == np.uint8

    def test_uniform_image_unchanged(self) -> None:
        """Sharpening a uniform image should produce minimal change."""
        img = _bgr(fill=180)
        result = sharpen(img)
        diff = np.abs(result.astype(int) - img.astype(int)).max()
        assert diff <= 5  # allow tiny rounding

    def test_sharpened_edges_increase_contrast(self) -> None:
        """An image with a sharp edge should have higher local variance after sharpening."""
        img = _bgr(200, 200, fill=255)
        img[:, 100:] = 0  # hard vertical edge

        original_var = float(np.var(img))
        sharpened_var = float(np.var(sharpen(img)))
        assert sharpened_var >= original_var


# ---------------------------------------------------------------------------
# save_jpeg
# ---------------------------------------------------------------------------


class TestSaveJpeg:
    def test_writes_valid_jpeg(self, tmp_path) -> None:
        img = _bgr(200, 150)
        path = tmp_path / "out.jpg"
        save_jpeg(img, path, quality=80)
        assert path.exists()
        # Verify it's a valid JPEG
        pil_img = Image.open(path)
        assert pil_img.format == "JPEG"

    def test_file_size_respects_quality(self, tmp_path) -> None:
        img = _bgr(400, 300, fill=128)
        # Draw some structure so quality has an effect
        img[50:250, 50:350] = 0

        path_hq = tmp_path / "hq.jpg"
        path_lq = tmp_path / "lq.jpg"
        save_jpeg(img, path_hq, quality=95)
        save_jpeg(img, path_lq, quality=50)
        assert path_hq.stat().st_size >= path_lq.stat().st_size

    def test_optimize_flag_is_set(self, tmp_path) -> None:
        """JPEG saved with optimize=True should be <= non-optimized size."""
        img = _bgr(200, 150, fill=200)
        buf_opt = io.BytesIO()
        buf_no = io.BytesIO()
        pil = Image.fromarray(img[:, :, ::-1])  # BGR -> RGB
        pil.save(buf_opt, format="JPEG", quality=80, optimize=True)
        pil.save(buf_no, format="JPEG", quality=80, optimize=False)
        assert buf_opt.tell() <= buf_no.tell()

    def test_creates_parent_directories(self, tmp_path) -> None:
        img = _bgr(100, 80)
        path = tmp_path / "a" / "b" / "page.jpg"
        save_jpeg(img, path, quality=75)
        assert path.exists()

    def test_quality_range_accepted(self, tmp_path) -> None:
        img = _bgr(100, 80)
        for q in (50, 75, 80, 85, 95):
            p = tmp_path / f"q{q}.jpg"
            save_jpeg(img, p, quality=q)
            assert p.exists()
