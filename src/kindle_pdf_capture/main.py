"""CLI entry point for kindle-pdf-capture.

Invoked as: kpc [OPTIONS]

All hardware-level calls are imported at the top so tests can patch them
at the module level via ``patch("kindle_pdf_capture.main.<name>")``.

## Module structure

The capture pipeline is split into focused helpers so each concern can be
read, tested, and reasoned about independently:

  _phase0_resize_window(window)
      Captures the cover frame, measures the page width via brightness
      detection, and resizes the Kindle window to match the book's natural
      aspect ratio.  Returns the original window size (for later restore) or
      None if the resize was skipped.

  _apply_crop_lock(region, frame, titlebar_y, locked_crop_y)
      Enforces a stable y-coordinate across all reading-mode pages.  On the
      first reading-mode page the y is "locked"; subsequent pages are clamped
      to the same value so font/layout variance in _find_header_bottom does
      not produce different heights across pages.

  _capture_one_page(page_num, window, config, session, locked_crop_y)
      Captures, crops, normalises, and saves a single page.  Returns the
      (possibly updated) locked_crop_y.

  _run_capture(config, pages_to_retry, key_code)
      Outer loop: Phase 0, page loop, PDF build, optional OCR.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

from kindle_pdf_capture.cropper import CropError, _find_titlebar_bottom, detect_content_region
from kindle_pdf_capture.normalize import normalize_image, save_jpeg
from kindle_pdf_capture.ocr import run_ocr, validate_ocr_lang
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
    KindleWindow,
    WindowCaptureError,
    capture_window,
    find_kindle_window,
    resize_kindle_window,
)

console = Console(stderr=True)


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.WARNING
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(RichHandler(console=console, show_time=False, show_path=False))


# ---------------------------------------------------------------------------
# Phase 0: cover-based window resize
# ---------------------------------------------------------------------------


def _phase0_resize_window(window: KindleWindow) -> tuple[int, int] | None:
    """Measure the cover page and resize the Kindle window to match.

    Why this exists
    ---------------
    Kindle for Mac may open at an arbitrary window width.  If the window is
    wider than the book's natural page width the side chrome (dark gutters)
    wastes pixels and slightly changes the scale of the captured content.
    Resizing the window so its content area exactly matches the book width
    ensures every page is captured at a consistent pixel density.

    How it works
    ------------
    1. Capture the cover frame (user must already be on the cover page).
    2. Strip the macOS title bar (Sobel scan, top 60 rows only).
    3. Call _detect_by_brightness: Kindle wraps the cover in near-black
       chrome (pixel value ~16-17); the page itself is brighter (≥ 20).
       Threshold at 20 → morphological close → largest contour = page rect.
    4. Compute the logical window width that matches the page pixel width at
       the current HiDPI scale factor, then call resize_kindle_window.
    5. Sleep 1.5 s for Kindle to reflow the content at the new size.

    Returns
    -------
    (orig_w, orig_h) tuple if the window was resized (caller must restore),
    or None if the cover rect was not detected or an error occurred.

    Failure handling
    ----------------
    Any exception is caught and logged as a warning so the capture loop can
    continue at the current window size.  A failed Phase 0 does not abort
    the run — it only means all pages may have a slightly inconsistent width.
    """
    from kindle_pdf_capture.cropper import _detect_by_brightness

    log = logging.getLogger(__name__)
    try:
        cover_frame = capture_window(window)

        # Scan only the top 60 rows so that Kindle header elements
        # (title band at ~y=110, divider at ~y=126) are never mistaken
        # for the macOS title bar boundary.
        titlebar_y = _find_titlebar_bottom(cover_frame, search_h=60)
        cropped_cover = cover_frame[titlebar_y:] if titlebar_y > 0 else cover_frame
        log.info(
            "Cover frame %dx%d. Title bar bottom: y=%d.",
            cover_frame.shape[1],
            cover_frame.shape[0],
            titlebar_y,
        )

        cover_region = _detect_by_brightness(cropped_cover, margin=0, min_area_ratio=0.10)
        if cover_region is None:
            log.info("Cover page rect not detected; skipping window resize.")
            return None

        # scale_factor: physical pixels per logical point (e.g. 2.0 on Retina)
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
        return orig_window_size

    except Exception as exc:
        log.warning("Cover-based window resize failed: %s — continuing at current size.", exc)
        return None


# ---------------------------------------------------------------------------
# Crop-lock helper
# ---------------------------------------------------------------------------


def _apply_crop_lock(
    region,
    frame,
    titlebar_y: int,
    locked_crop_y: int | None,
) -> tuple[object, int | None]:
    """Enforce a stable crop y-coordinate across reading-mode pages.

    Why this exists
    ---------------
    _find_header_bottom uses row-level standard-deviation heuristics to find
    the bottom of the Kindle book-title text block.  The detected y can vary
    by a few pixels between frames (font anti-aliasing, sub-pixel rendering).
    If each page is cropped at a different y the resulting PDF pages have
    slightly different heights, which causes layout jumps when reading.

    Locking strategy
    ----------------
    - A page is "reading mode" when region.w == frame width AND
      region.y > titlebar_y (i.e. the Kindle header band was also stripped,
      not just the macOS title bar).
    - On the *first* such page, record region.y as locked_crop_y.
    - On subsequent pages, if region.y != locked_crop_y, clamp it back to
      locked_crop_y and adjust h so the bottom of the frame is unchanged.
    - Cover/image pages (region.y == titlebar_y) are NOT locked — they
      intentionally include the full frame below the title bar.

    Parameters
    ----------
    region      : ContentRegion returned by detect_content_region.
    frame       : The raw BGR frame (used for shape).
    titlebar_y  : Bottom of the macOS title bar in this frame.
    locked_crop_y : Currently locked y, or None if not yet set.

    Returns
    -------
    (region, locked_crop_y) — region may be a new ContentRegion with the
    clamped y; locked_crop_y may be newly set.
    """
    log = logging.getLogger(__name__)

    is_reading_mode_page = region.w == frame.shape[1] and region.y > titlebar_y
    if not is_reading_mode_page:
        return region, locked_crop_y

    if locked_crop_y is None:
        locked_crop_y = region.y
        log.debug("Locked crop y=%d from first reading-mode page.", locked_crop_y)
    elif region.y != locked_crop_y:
        region = region.__class__(
            x=region.x,
            y=locked_crop_y,
            w=region.w,
            h=frame.shape[0] - locked_crop_y,
        )
        log.debug("Crop y clamped from %d to locked %d.", region.y, locked_crop_y)

    return region, locked_crop_y


# ---------------------------------------------------------------------------
# Single-page capture
# ---------------------------------------------------------------------------


def _capture_one_page(
    page_num: int,
    window: KindleWindow,
    config: CaptureConfig,
    session: CaptureSession,
    locked_crop_y: int | None,
) -> int | None:
    """Capture, crop, normalise, and save one Kindle page.

    Parameters
    ----------
    page_num     : 1-based page index.
    window       : KindleWindow snapshot (pid, geometry).
    config       : CaptureConfig with output paths and image settings.
    session      : Active CaptureSession (used for output paths).
    locked_crop_y: Currently locked reading-mode y, or None.

    Returns
    -------
    Updated locked_crop_y (may be the same value or newly set).

    Side effects
    ------------
    - Writes `cropped/page_XXXX.jpg` (and optionally `raw/page_XXXX.jpg`).
    - Appends a PageResult to session.
    """
    log = logging.getLogger(__name__)

    frame = capture_window(window)

    if config.save_raw:
        raw_path = session.raw_path(page_num)
        save_jpeg(frame, raw_path, quality=config.jpeg_quality)

    try:
        region = detect_content_region(frame)

        titlebar_y = _find_titlebar_bottom(frame, search_h=60)
        region, locked_crop_y = _apply_crop_lock(region, frame, titlebar_y, locked_crop_y)

        cropped = frame[region.slice()]
        # Scale proportionally so all pages share the same pixels-per-unit ratio.
        scale = config.resize_width / frame.shape[1]
        target_w = max(1, round(region.w * scale))
    except CropError as exc:
        log.warning("Page %d crop failed: %s — using full frame.", page_num, exc)
        cropped = frame
        target_w = config.resize_width

    normalised = normalize_image(cropped, resize_width=target_w)
    cropped_path = session.cropped_path(page_num)
    save_jpeg(normalised, cropped_path, quality=config.jpeg_quality)

    session.record_result(
        PageResult(page_num=page_num, status=PageStatus.OK, cropped_path=cropped_path)
    )
    log.debug("Page %d saved to %s", page_num, cropped_path)

    return locked_crop_y


# ---------------------------------------------------------------------------
# Capture loop
# ---------------------------------------------------------------------------


def _run_capture(
    config: CaptureConfig,
    *,
    pages_to_retry: list[int],
    key_code: int,
) -> None:
    """Outer capture loop: Phase 0, page loop, PDF build, optional OCR.

    Separated from the CLI handler for testability.
    """
    config.ensure_dirs()
    log = logging.getLogger(__name__)

    check_accessibility()
    window = find_kindle_window()
    focus_window(window)

    # Phase 0: resize window to the cover page's natural width.
    orig_window_size = _phase0_resize_window(window)

    session = CaptureSession(config)

    if config.start_delay > 0:
        log.info("Starting in %d s …", config.start_delay)
        time.sleep(config.start_delay)

    page_num = 1
    locked_crop_y: int | None = None

    try:
        with console.status("", refresh_per_second=4) as status:
            while not session.is_finished():
                if pages_to_retry and page_num not in pages_to_retry:
                    page_num += 1
                    continue

                if session.should_skip(page_num):
                    log.debug("Page %d already captured — skipping.", page_num)
                    session.record_result(
                        PageResult(page_num=page_num, status=PageStatus.SKIPPED, cropped_path=None)
                    )
                    page_num += 1
                    continue

                page_label = (
                    f"{page_num}/{config.max_pages}"
                    if config.max_pages is not None
                    else str(page_num)
                )
                status.update(f"[bold]Capturing[/bold] page {page_label} …")

                pre_turn_frame = capture_window(window)
                locked_crop_y = _capture_one_page(page_num, window, config, session, locked_crop_y)

                send_page_turn_key(window.pid, key_code)
                wait_result = wait_for_render(capture_fn=lambda: capture_window(window))
                if wait_result.status == WaitStatus.TIMEOUT:
                    log.warning(
                        "Page %d: render timed out after %.1fs", page_num, wait_result.elapsed
                    )

                post_turn_frame = (
                    wait_result.last_frame
                    if wait_result.last_frame is not None
                    else capture_window(window)
                )
                session.record_duplicate(pre_turn_frame, post_turn_frame)

                page_num += 1

    finally:
        # Restore the original window size even if the loop exits via error.
        # force=True bypasses the size-equality guard in resize_kindle_window
        # (the KindleWindow snapshot still holds pre-resize dimensions).
        if orig_window_size is not None:
            orig_w, orig_h = orig_window_size
            resize_kindle_window(window, target_width=orig_w, target_height=orig_h, force=True)
            log.debug("Kindle window restored to original size (%dx%d).", orig_w, orig_h)

    save_session(config, session.results)

    jpeg_paths = sorted((config.out_dir / "cropped").glob("page_*.jpg"))
    if not jpeg_paths:
        log.warning("No pages captured; skipping PDF build.")
        return

    pdf_path = config.out_dir / "pdf" / "book.pdf"
    with console.status(f"[bold]Building PDF[/bold] from {len(jpeg_paths)} pages …"):
        build_pdf(jpeg_paths, pdf_path, dpi=config.pdf_dpi)
        optimise_pdf(pdf_path, pdf_path)
    console.print(f"[green]✓[/green] PDF saved → {pdf_path}")

    if config.ocr:
        ocr_path = config.out_dir / "pdf" / "book_ocr.pdf"
        console.print(f"[bold]Running OCR[/bold] ({config.ocr_lang}) …")
        result = run_ocr(pdf_path, ocr_path, lang=config.ocr_lang, optimize=config.ocr_optimize)
        if result.succeeded:
            console.print(f"[green]✓[/green] OCR PDF saved → {ocr_path}")
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
    default=None,
    type=int,
    show_default=False,
    help="Maximum number of pages to capture (default: no limit).",
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
    default=1,
    show_default=True,
    help="ocrmypdf --optimize level (0-3). Level 2/3 requires pngquant (not needed for this tool's JPEG-only pipeline).",
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

    if ocr and not validate_ocr_lang(ocr_lang):
        raise click.BadParameter(
            f"Invalid language code '{ocr_lang}'. "
            "Use three-letter Tesseract codes, e.g. 'jpn', 'eng', 'jpn+eng'.",
            param_hint="--ocr-lang",
        )

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
