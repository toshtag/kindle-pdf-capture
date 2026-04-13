"""Tests for the PDF builder module (img2pdf + pikepdf)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kindle_pdf_capture.normalize import save_jpeg
from kindle_pdf_capture.pdf_builder import build_pdf, optimise_pdf


def _make_jpeg(tmp_path: Path, name: str, width: int = 400, height: int = 300) -> Path:
    img = np.full((height, width, 3), 200, dtype=np.uint8)
    # Add some structure so JPEG isn't trivial
    img[50:250, 50:350] = 100
    p = tmp_path / name
    save_jpeg(img, p, quality=80)
    return p


# ---------------------------------------------------------------------------
# build_pdf
# ---------------------------------------------------------------------------


class TestBuildPdf:
    def test_creates_pdf_file(self, tmp_path: Path) -> None:
        jpegs = [_make_jpeg(tmp_path, f"p{i:04d}.jpg") for i in range(3)]
        out = tmp_path / "book.pdf"
        build_pdf(jpegs, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_pdf_starts_with_header(self, tmp_path: Path) -> None:
        jpegs = [_make_jpeg(tmp_path, "page.jpg")]
        out = tmp_path / "book.pdf"
        build_pdf(jpegs, out)
        assert out.read_bytes()[:4] == b"%PDF"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        jpegs = [_make_jpeg(tmp_path, "p.jpg")]
        out = tmp_path / "sub" / "dir" / "book.pdf"
        build_pdf(jpegs, out)
        assert out.exists()

    def test_page_count_matches_input(self, tmp_path: Path) -> None:
        import pikepdf

        n = 5
        jpegs = [_make_jpeg(tmp_path, f"p{i}.jpg") for i in range(n)]
        out = tmp_path / "book.pdf"
        build_pdf(jpegs, out)
        with pikepdf.open(out) as pdf:
            assert len(pdf.pages) == n

    def test_page_aspect_ratio_matches_image(self, tmp_path: Path) -> None:
        """PDF page aspect ratio should match the source JPEG dimensions.

        img2pdf converts px -> pt using the image's embedded DPI (or 96 DPI
        when no DPI metadata is present): pt = px * 72 / dpi.  We verify the
        aspect ratio rather than absolute point values so the test is robust
        to any default DPI assumption.
        """
        import pikepdf

        jpeg = _make_jpeg(tmp_path, "p.jpg", width=600, height=400)
        out = tmp_path / "book.pdf"
        build_pdf([jpeg], out)
        with pikepdf.open(out) as pdf:
            page = pdf.pages[0]
            mb = page.mediabox
            w_pt = float(mb[2])
            h_pt = float(mb[3])
            # Expected aspect ratio: 600/400 = 1.5
            assert abs(w_pt / h_pt - 600 / 400) < 0.01

    def test_raises_on_empty_list(self, tmp_path: Path) -> None:
        out = tmp_path / "book.pdf"
        with pytest.raises((ValueError, Exception)):
            build_pdf([], out)

    def test_raises_on_missing_jpeg(self, tmp_path: Path) -> None:
        out = tmp_path / "book.pdf"
        with pytest.raises(FileNotFoundError):
            build_pdf([tmp_path / "nonexistent.jpg"], out)


# ---------------------------------------------------------------------------
# optimise_pdf
# ---------------------------------------------------------------------------


class TestOptimisePdf:
    def test_output_is_valid_pdf(self, tmp_path: Path) -> None:
        import pikepdf

        jpegs = [_make_jpeg(tmp_path, "p.jpg")]
        src = tmp_path / "src.pdf"
        dst = tmp_path / "dst.pdf"
        build_pdf(jpegs, src)
        optimise_pdf(src, dst)
        assert dst.exists()
        with pikepdf.open(dst) as pdf:
            assert len(pdf.pages) == 1

    def test_optimise_in_place_when_dst_is_src(self, tmp_path: Path) -> None:
        import pikepdf

        jpegs = [_make_jpeg(tmp_path, "p.jpg")]
        path = tmp_path / "book.pdf"
        build_pdf(jpegs, path)
        optimise_pdf(path, path)
        assert path.exists()
        with pikepdf.open(path) as pdf:
            assert len(pdf.pages) == 1

    def test_page_count_preserved(self, tmp_path: Path) -> None:
        import pikepdf

        n = 3
        jpegs = [_make_jpeg(tmp_path, f"p{i}.jpg") for i in range(n)]
        src = tmp_path / "src.pdf"
        dst = tmp_path / "dst.pdf"
        build_pdf(jpegs, src)
        optimise_pdf(src, dst)
        with pikepdf.open(dst) as pdf:
            assert len(pdf.pages) == n
