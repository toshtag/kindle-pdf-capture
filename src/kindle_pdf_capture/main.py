"""CLI entry point for kindle-pdf-capture.

Invoked as: kpc [OPTIONS]

All hardware-level calls are imported at the top so tests can patch them
at the module level via ``patch("kindle_pdf_capture.main.<name>")``.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

from kindle_pdf_capture.cropper import CropError, detect_content_region
from kindle_pdf_capture.normalize import normalize_image, save_jpeg
from kindle_pdf_capture.ocr import run_ocr
from kindle_pdf_capture.orchestrator import (
    CaptureConfig,
    CaptureSession,
    PageResult,
    PageStatus,
    load_session,
    save_session,
)
from kindle_pdf_capture.page_turner import (
    AccessibilityError,
    check_accessibility,
    focus_window,
    send_right_arrow,
)
from kindle_pdf_capture.pdf_builder import build_pdf, optimise_pdf
from kindle_pdf_capture.render_wait import WaitStatus, wait_for_render
from kindle_pdf_capture.window_capture import (
    WindowCaptureError,
    capture_window,
    find_kindle_window,
)

console = Console(stderr=True)


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )


# ---------------------------------------------------------------------------
# Capture loop
# ---------------------------------------------------------------------------


def _run_capture(config: CaptureConfig, *, pages_to_retry: list[int]) -> None:
    """Inner capture loop; separated for testability."""
    config.ensure_dirs()

    log = logging.getLogger(__name__)

    check_accessibility()

    window = find_kindle_window()
    focus_window(window)

    session = CaptureSession(config)

    if config.start_delay > 0:
        log.info("Starting in %d s — switch to Kindle now.", config.start_delay)
        time.sleep(config.start_delay)

    page_num = 1

    while not session.is_finished():
        # If retrying, skip pages not in the retry list
        if pages_to_retry and page_num not in pages_to_retry:
            page_num += 1
            continue

        if session.should_skip(page_num):
            log.info("Page %d already captured — skipping.", page_num)
            session.record_result(
                PageResult(page_num=page_num, status=PageStatus.SKIPPED, cropped_path=None)
            )
            page_num += 1
            continue

        log.info("Capturing page %d …", page_num)

        # Capture and wait for render to settle
        wait_result = wait_for_render(
            capture_fn=lambda: capture_window(window),
        )
        if wait_result.status == WaitStatus.TIMEOUT:
            log.warning("Page %d: render timed out after %.1fs", page_num, wait_result.elapsed)

        frame = capture_window(window)

        # Save raw if requested
        if config.save_raw:
            raw_path = session.raw_path(page_num)
            save_jpeg(frame, raw_path, quality=config.jpeg_quality)

        # Detect content region and crop
        try:
            region = detect_content_region(frame)
            cropped = frame[region.slice()]
        except CropError as exc:
            log.warning("Page %d crop failed: %s — using full frame.", page_num, exc)
            cropped = frame

        # Normalise and save
        normalised = normalize_image(cropped, resize_width=config.resize_width)
        cropped_path = session.cropped_path(page_num)
        save_jpeg(normalised, cropped_path, quality=config.jpeg_quality)

        session.record_result(
            PageResult(page_num=page_num, status=PageStatus.OK, cropped_path=cropped_path)
        )
        log.debug("Page %d saved to %s", page_num, cropped_path)

        # Turn to next page
        send_right_arrow()

        # Check for duplicate (end-of-book detection)
        time.sleep(0.3)
        next_frame = capture_window(window)
        session.record_duplicate(next_frame)

        page_num += 1

    save_session(config, session.results)

    # Build PDF
    jpeg_paths = sorted((config.out_dir / "cropped").glob("page_*.jpg"))
    if not jpeg_paths:
        log.warning("No pages captured; skipping PDF build.")
        return

    pdf_path = config.out_dir / "pdf" / "book.pdf"
    log.info("Building PDF from %d pages …", len(jpeg_paths))
    build_pdf(jpeg_paths, pdf_path)
    optimise_pdf(pdf_path, pdf_path)
    log.info("PDF saved to %s", pdf_path)

    # Optional OCR
    if config.ocr:
        ocr_path = config.out_dir / "pdf" / "book_ocr.pdf"
        log.info("Running OCR (%s) …", config.ocr_lang)
        result = run_ocr(pdf_path, ocr_path, lang=config.ocr_lang, optimize=config.ocr_optimize)
        if result.succeeded:
            log.info("OCR PDF saved to %s", ocr_path)
        else:
            log.warning("OCR failed (rc=%s); non-OCR PDF is still available.", result.returncode)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--out",
    required=True,
    type=click.Path(file_okay=False, writable=True, path_type=Path),
    help="Output directory for captured images and PDF.",
)
@click.option(
    "--max-pages",
    default=1000,
    show_default=True,
    help="Maximum number of pages to capture.",
)
@click.option(
    "--resize-width",
    default=1800,
    show_default=True,
    help="Width in pixels to resize each page to.",
)
@click.option(
    "--jpeg-quality",
    default=80,
    show_default=True,
    help="JPEG quality (1-95).",
)
@click.option(
    "--save-raw",
    is_flag=True,
    default=False,
    help="Save raw (uncropped) screenshots alongside cropped pages.",
)
@click.option(
    "--start-delay",
    default=3,
    show_default=True,
    help="Seconds to wait before capture begins (use to switch to Kindle).",
)
@click.option(
    "--ocr",
    is_flag=True,
    default=False,
    help="Run OCR on the assembled PDF (requires the [ocr] extra).",
)
@click.option(
    "--ocr-lang",
    default="jpn+eng",
    show_default=True,
    help="Tesseract language string passed to ocrmypdf.",
)
@click.option(
    "--ocr-optimize",
    default=2,
    show_default=True,
    help="ocrmypdf --optimize level (0-3).",
)
@click.option(
    "--retry-failed",
    is_flag=True,
    default=False,
    help="Re-capture only the pages listed in logs/failed_pages.json.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug-level logging.",
)
def cli(
    out: Path,
    max_pages: int,
    resize_width: int,
    jpeg_quality: int,
    save_raw: bool,
    start_delay: int,
    ocr: bool,
    ocr_lang: str,
    ocr_optimize: int,
    retry_failed: bool,
    debug: bool,
) -> None:
    """Capture Kindle for Mac pages and assemble them into a PDF."""
    _setup_logging(debug)
    log = logging.getLogger(__name__)

    config = CaptureConfig(
        out_dir=out,
        max_pages=max_pages,
        resize_width=resize_width,
        jpeg_quality=jpeg_quality,
        save_raw=save_raw,
        start_delay=start_delay,
        ocr=ocr,
        ocr_lang=ocr_lang,
        ocr_optimize=ocr_optimize,
    )

    pages_to_retry: list[int] = []
    if retry_failed:
        pages_to_retry = load_session(config)
        if pages_to_retry:
            log.info("Retrying %d failed page(s): %s", len(pages_to_retry), pages_to_retry)
        else:
            log.info("No failed pages found; capturing from the beginning.")

    try:
        _run_capture(config, pages_to_retry=pages_to_retry)
    except (AccessibilityError, WindowCaptureError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        log.debug("Fatal error", exc_info=True)
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
