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

    def test_page_dimensions_match_image(self, tmp_path: Path) -> None:
        """PDF page size should match the JPEG pixel dimensions."""
        import pikepdf

        jpeg = _make_jpeg(tmp_path, "p.jpg", width=600, height=400)
        out = tmp_path / "book.pdf"
        build_pdf([jpeg], out)
        with pikepdf.open(out) as pdf:
            page = pdf.pages[0]
            mb = page.mediabox
            # img2pdf embeds at 72 DPI by default: points = pixels * 72/72 = pixels
            # Tolerance of 2pt to account for rounding
            w_pt = float(mb[2])
            h_pt = float(mb[3])
            assert abs(w_pt - 600) <= 2
            assert abs(h_pt - 400) <= 2

    def test_raises_on_empty_list(self, tmp_path: Path) -> None:
        out = tmp_path / "book.pdf"
        with pytest.raises((ValueError, Exception)):
            build_pdf([], out)

    def test_raises_on_missing_jpeg(self, tmp_path: Path) -> None:
        out = tmp_path / "book.pdf"
        with pytest.raises(Exception):
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
        original_size = path.stat().st_size
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
