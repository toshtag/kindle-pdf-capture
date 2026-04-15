"""OCR wrapper: runs ocrmypdf as an in-process call on the generated PDF.

OCR is an optional post-processing step (Phase 3).  Failures are logged
and returned as OcrResult; they never raise exceptions so the caller's
main flow continues regardless.
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass
from pathlib import Path

try:
    import ocrmypdf as _ocrmypdf
except ImportError:  # optional dependency — only needed when --ocr is used
    _ocrmypdf = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Tesseract language code pattern: three lowercase letters, optionally repeated
# with '+' as separator.  Examples: "jpn", "eng", "jpn+eng", "jpn+eng+fra".
_LANG_RE = re.compile(r"^[a-z]{3}(\+[a-z]{3})*$")


def validate_ocr_lang(lang: str) -> bool:
    """Return True if *lang* is a well-formed Tesseract language string.

    Valid examples: ``"jpn"``, ``"eng"``, ``"jpn+eng"``.
    Rejects empty strings, uppercase, path characters, or shell metacharacters.
    """
    return bool(_LANG_RE.match(lang))


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
    optimize: int = 1,
) -> OcrResult:
    """Run ocrmypdf on *src* and write the result to *dst*.

    Uses the ocrmypdf Python API directly so that the built-in progress bar
    (one line per page) is shown in the terminal during processing.

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
    languages = lang.split("+")

    logger.info("Running OCR: src=%s lang=%s optimize=%d", src, lang, optimize)

    if _ocrmypdf is None:
        logger.error(
            "ocrmypdf is not installed. Install with: pip install 'kindle-pdf-capture[ocr]'"
        )
        return OcrResult(status=OcrStatus.FAILED, output=dst, returncode=-1)

    try:
        exit_code = _ocrmypdf.ocr(
            src,
            dst,
            language=languages,
            skip_text=True,
            optimize=optimize,
            progress_bar=True,
        )
    except Exception as exc:
        logger.error("ocrmypdf raised an exception: %s", exc)
        return OcrResult(status=OcrStatus.FAILED, output=dst, returncode=-1)

    returncode = int(exit_code)
    if exit_code == _ocrmypdf.ExitCode.ok:
        logger.info("OCR completed: %s", dst)
        return OcrResult(status=OcrStatus.SUCCESS, output=dst, returncode=returncode)

    logger.error("ocrmypdf exited with code %d: %s", returncode, exit_code.name)
    return OcrResult(status=OcrStatus.FAILED, output=dst, returncode=returncode)
