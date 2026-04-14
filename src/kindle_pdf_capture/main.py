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

from kindle_pdf_capture.cropper import CropError, _has_dark_border, detect_content_region
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
    KEY_LEFT,
    KEY_RIGHT,
    AccessibilityError,
    check_accessibility,
    focus_window,
    send_page_turn_key,
)
from kindle_pdf_capture.pdf_builder import build_pdf, optimise_pdf
from kindle_pdf_capture.render_wait import WaitStatus, wait_for_render
from kindle_pdf_capture.window_capture import (
    WindowCaptureError,
    capture_window,
    find_kindle_window,
    resize_kindle_window,
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


def _run_capture(
    config: CaptureConfig,
    *,
    pages_to_retry: list[int],
    key_code: int,
) -> None:
    """Inner capture loop; separated for testability."""
    config.ensure_dirs()

    log = logging.getLogger(__name__)

    check_accessibility()

    window = find_kindle_window()
    focus_window(window)

    # --- Phase 0: detect cover page rect, resize window to match ---
    # Runs before the capture loop so the window width is fixed for all pages.
    # Requires the cover page (dark-chrome bordered) to be visible in Kindle.
    orig_window_size: tuple[int, int] | None = None
    try:
        import cv2 as _cv2

        cover_frame = capture_window(window)
        cover_gray = _cv2.cvtColor(cover_frame, _cv2.COLOR_BGR2GRAY)
        if _has_dark_border(cover_gray):
            from kindle_pdf_capture.cropper import _detect_by_brightness

            cover_region = _detect_by_brightness(cover_frame, margin=0, min_area_ratio=0.10)
            if cover_region is not None:
                scale_factor = cover_frame.shape[1] / window.width
                target_logical_w = round(cover_region.w / scale_factor)
                target_logical_h = window.height
                log.info(
                    "Cover page rect: %dpx wide (frame: %dpx, scale: %.1f). "
                    "Resizing window to %d logical px.",
                    cover_region.w,
                    cover_frame.shape[1],
                    scale_factor,
                    target_logical_w,
                )
                orig_window_size = resize_kindle_window(
                    window, target_width=target_logical_w, target_height=target_logical_h
                )
                # Wait for Kindle to reflow at the new window size
                time.sleep(1.5)
            else:
                log.debug("Cover brightness detection returned nothing; skipping resize.")
        else:
            log.debug("First frame has no dark chrome border; skipping cover-based resize.")
    except Exception as exc:
        log.warning("Cover-based window resize failed: %s — continuing at current size.", exc)

    session = CaptureSession(config)

    if config.start_delay > 0:
        log.info("Starting in %d s …", config.start_delay)
        time.sleep(config.start_delay)

    page_num = 1

    try:
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

            frame = capture_window(window)

            # Save raw if requested
            if config.save_raw:
                raw_path = session.raw_path(page_num)
                save_jpeg(frame, raw_path, quality=config.jpeg_quality)

            # Detect content region and crop
            try:
                region = detect_content_region(frame)
                cropped = frame[region.slice()]
                # Scale the cropped region proportionally to the raw frame width so
                # that all pages share the same pixels-per-physical-unit ratio and
                # text appears at a consistent size throughout the PDF.
                scale = config.resize_width / frame.shape[1]
                target_w = max(1, round(region.w * scale))
            except CropError as exc:
                log.warning("Page %d crop failed: %s — using full frame.", page_num, exc)
                cropped = frame
                target_w = config.resize_width

            # Normalise and save
            normalised = normalize_image(cropped, resize_width=target_w)
            cropped_path = session.cropped_path(page_num)
            save_jpeg(normalised, cropped_path, quality=config.jpeg_quality)

            session.record_result(
                PageResult(page_num=page_num, status=PageStatus.OK, cropped_path=cropped_path)
            )
            log.debug("Page %d saved to %s", page_num, cropped_path)

            # Turn to next page, then wait for the new page to render
            send_page_turn_key(window.pid, key_code)
            wait_result = wait_for_render(
                capture_fn=lambda: capture_window(window),
            )
            if wait_result.status == WaitStatus.TIMEOUT:
                log.warning("Page %d: render timed out after %.1fs", page_num, wait_result.elapsed)

            # Check for duplicate (end-of-book detection)
            next_frame = capture_window(window)
            session.record_duplicate(next_frame)

            page_num += 1

    finally:
        # Always restore original window size, even if the loop exits via error.
        if orig_window_size is not None:
            orig_w, orig_h = orig_window_size
            resize_kindle_window(window, target_width=orig_w, target_height=orig_h)
            log.info("Kindle window restored to original size (%dx%d).", orig_w, orig_h)

    save_session(config, session.results)

    # Build PDF
    jpeg_paths = sorted((config.out_dir / "cropped").glob("page_*.jpg"))
    if not jpeg_paths:
        log.warning("No pages captured; skipping PDF build.")
        return

    pdf_path = config.out_dir / "pdf" / "book.pdf"
    log.info("Building PDF from %d pages …", len(jpeg_paths))
    build_pdf(jpeg_paths, pdf_path, dpi=config.pdf_dpi)
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
    default=0,
    show_default=True,
    help="Additional seconds to wait after the ready prompt before capture begins.",
)
@click.option(
    "--direction",
    type=click.Choice(["left", "right"], case_sensitive=False),
    default="right",
    show_default=True,
    help=(
        "Page-advance direction. "
        "Use 'right' for LTR books (English etc.) and "
        "'left' for RTL books (Japanese manga etc.)."
    ),
)
@click.option(
    "--pdf-dpi",
    default=300.0,
    show_default=True,
    help="DPI for PDF page sizing. 300 maps 1800 px to 6 inches.",
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
    direction: str,
    pdf_dpi: float,
    ocr: bool,
    ocr_lang: str,
    ocr_optimize: int,
    retry_failed: bool,
    debug: bool,
) -> None:
    """Capture Kindle for Mac pages and assemble them into a PDF."""
    _setup_logging(debug)
    log = logging.getLogger(__name__)

    key_code = KEY_LEFT if direction == "left" else KEY_RIGHT

    config = CaptureConfig(
        out_dir=out,
        max_pages=max_pages,
        resize_width=resize_width,
        jpeg_quality=jpeg_quality,
        save_raw=save_raw,
        start_delay=start_delay,
        pdf_dpi=pdf_dpi,
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

    console.print(
        "\n[bold]Ready to capture.[/bold]\n"
        "  Navigate Kindle to the [bold]cover page[/bold] of the book,\n"
        "  then press [bold]Enter[/bold] to start.\n"
        "\n"
        "[bold]キャプチャの準備ができました。[/bold]\n"
        "  Kindle で本の[bold]表紙ページ[/bold]を表示してから、\n"
        "  [bold]Enter[/bold] を押してください。\n"
    )
    click.pause(info="")

    try:
        _run_capture(config, pages_to_retry=pages_to_retry, key_code=key_code)
    except (AccessibilityError, WindowCaptureError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        log.debug("Fatal error", exc_info=True)
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
