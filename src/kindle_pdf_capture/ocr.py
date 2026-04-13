"""OCR wrapper: runs ocrmypdf as a subprocess on the generated PDF.

OCR is an optional post-processing step (Phase 3).  Failures are logged
and returned as OcrResult; they never raise exceptions so the caller's
main flow continues regardless.
"""

from __future__ import annotations

import enum
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class OcrStatus(enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class OcrResult:
    """Outcome of an OCR run."""

    status: OcrStatus
    output: Path
    returncode: int

    @property
    def succeeded(self) -> bool:
        return self.status == OcrStatus.SUCCESS


def run_ocr(
    src: Path,
    dst: Path,
    *,
    lang: str = "jpn+eng",
    optimize: int = 2,
) -> OcrResult:
    """Run ocrmypdf on *src* and write the result to *dst*.

    The function never raises: all errors are captured and returned as
    OcrResult with status=FAILED so the caller's PDF (src) is always safe.

    Args:
        src: Input PDF (already generated book.pdf).
        dst: Output path for the OCR-enriched PDF (book_ocr.pdf).
        lang: Tesseract language codes, e.g. ``"jpn+eng"``.
        optimize: ocrmypdf --optimize level (0-3).

    Returns:
        OcrResult with SUCCESS or FAILED status.
    """
    src = Path(src)
    dst = Path(dst)

    cmd = [
        "ocrmypdf",
        "--skip-text",
        "--optimize",
        str(optimize),
        "-l",
        lang,
        str(src),
        str(dst),
    ]

    logger.info("Running OCR: %s", " ".join(cmd))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        logger.error("ocrmypdf could not be started: %s", exc)
        return OcrResult(status=OcrStatus.FAILED, output=dst, returncode=-1)

    if proc.returncode != 0:
        logger.error("ocrmypdf exited with code %d: %s", proc.returncode, proc.stderr.strip())
        return OcrResult(status=OcrStatus.FAILED, output=dst, returncode=proc.returncode)

    logger.info("OCR completed: %s", dst)
    return OcrResult(status=OcrStatus.SUCCESS, output=dst, returncode=0)
