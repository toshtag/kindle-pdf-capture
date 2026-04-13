"""PDF assembly and optimisation.

Assembles a sequence of JPEG files into a PDF using img2pdf (which preserves
pixel-perfect dimensions) and then runs pikepdf to remove redundant objects
and optionally linearise the output.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

import img2pdf
import pikepdf

logger = logging.getLogger(__name__)


def build_pdf(jpeg_paths: list[Path], output: Path) -> None:
    """Assemble JPEG files into a single PDF.

    Page size in the PDF matches each image's pixel dimensions exactly
    (img2pdf embeds at 72 DPI by default so 1px = 1pt).

    Args:
        jpeg_paths: Ordered list of JPEG file paths (one per page).
        output: Destination PDF path. Parent directories are created
            automatically.

    Raises:
        ValueError: If *jpeg_paths* is empty.
        FileNotFoundError: If any path in *jpeg_paths* does not exist.
    """
    if not jpeg_paths:
        raise ValueError("jpeg_paths must not be empty")

    for p in jpeg_paths:
        p = Path(p)
        if not p.exists():
            raise FileNotFoundError(f"JPEG not found: {p}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Building PDF from %d pages -> %s", len(jpeg_paths), output)
    pdf_bytes = img2pdf.convert([str(p) for p in jpeg_paths])
    output.write_bytes(pdf_bytes)
    logger.debug("PDF written: %s (%d bytes)", output, len(pdf_bytes))


def optimise_pdf(src: Path, dst: Path) -> None:
    """Optimise a PDF with pikepdf to reduce file size.

    Removes unused objects and compresses streams.  When *src* and *dst*
    are the same path, the optimisation is performed atomically via a
    temporary file.

    Args:
        src: Input PDF path.
        dst: Output PDF path (may equal *src* for in-place optimisation).
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    same_file = src.resolve() == dst.resolve()

    with pikepdf.open(src) as pdf:
        if same_file:
            # Write to a temp file then replace atomically
            with tempfile.NamedTemporaryFile(suffix=".pdf", dir=dst.parent, delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                pdf.save(tmp_path, compress_streams=True, recompress_flate=True)
                shutil.move(str(tmp_path), str(dst))
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
        else:
            pdf.save(dst, compress_streams=True, recompress_flate=True)

    logger.info("Optimised PDF saved: %s", dst)
