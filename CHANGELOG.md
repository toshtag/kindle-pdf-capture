# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.3] - 2026-04-15

### Fixed

- Horizontal rule lines rendered by Kindle immediately below the book-title
  header band are now always excluded from the cropped output.  A fixed
  `_HEADER_RULE_MARGIN = 20` px offset is added to `header_y` when computing
  `content_y`, replacing the previous `header_y - top_padding` formula that
  moved the crop boundary upward and could leave the rule visible.

## [1.0.2] - 2026-04-15

### Fixed

- `_find_header_bottom` now detects the book-title text block boundary
  instead of using a fraction-based search window, eliminating the
  168/308-page misdetection where the title text was included in the
  title-bar search region and returned a wrong `titlebar_y=139`.
- Cover/image pages (bright but no title text) no longer fall through to
  the brightness/edge-detection passes. `detect_content_region` now
  returns the full frame from `titlebar_y` directly when `header_y == 0`,
  preventing a regression where the cover page was cropped to a small
  interior rect instead of the full page.
- `_find_titlebar_bottom` gains a `search_h` parameter (fixed 60-row
  window) so Kindle chrome elements below y=60 are never mistaken for
  the macOS title bar boundary.
- `detect_content_region` simplified to two passes only (title-bar strip
  + header strip); brightness/edge-detection passes removed as they were
  unreachable after the header-detection logic was corrected.

## [1.0.1] - 2026-04-14

### Fixed

- `--ocr-optimize` default changed from 2 to 1. Level 2/3 requires
  `pngquant`, which is not installed by default and has no effect on
  this tool's JPEG-only PDF pipeline. Level 1 (lossless) works without
  any additional system dependency.

### Changed

- `--ocr-optimize` help text now notes that level 2/3 requires `pngquant`.
- Troubleshooting guide (en): OCR section aligned with Japanese version —
  `--debug` tip added.

## [1.0.0] - 2026-04-14

### Added

- **Phase 0 window resize**: before capture begins, the cover page rect is
  measured via brightness analysis and the Kindle window is resized to match,
  so all body pages render at a consistent physical width with no per-page
  reflow variance.
- **Bilingual ready prompt**: CLI now prints an English/Japanese prompt asking
  the user to navigate to the cover page before pressing Enter to start.
- `_find_titlebar_bottom()` in cropper: Sobel Step 1 only — returns the bottom
  edge of the macOS title bar without scanning the Kindle header band. Used as
  a lightweight, image-derived reference y-coordinate.
- `force` parameter on `resize_kindle_window()`: bypasses the size-equality
  guard so the window restore call in `finally` always fires even when the
  `KindleWindow` snapshot still holds the pre-resize dimensions.
- Crop y-coordinate locking: the first reading-mode page's top edge is locked
  and applied to all subsequent full-width pages, eliminating per-frame height
  variance from `_find_header_bottom`.

### Fixed

- **CGImage reshape crash on Retina displays**: `CGWindowListCreateImage` pads
  rows for memory alignment (`bytes_per_row` > `width * channels`). The raw
  buffer is now reshaped using the actual stride and then sliced to the true
  pixel width, preventing `numpy.reshape` from raising a size mismatch error.
- **Cover page over-cropped after window resize**: after Phase 0 resizes the
  Kindle window, Kindle reflows the cover into reading mode with no dark
  chrome border, causing `_has_dark_border` to return False and
  `_find_header_bottom` to treat the Kindle chrome as a header band (~589 px
  stripped). Fixed by replacing the `_has_dark_border` dispatch with luminance
  sampling immediately below the macOS title bar: dark mean → cover/image page
  (return full frame from `titlebar_y`); bright mean → reading mode (also
  strip header band).
- **Window not restored after capture**: `KindleWindow` is an immutable
  snapshot, so `window.width` still holds the original value after Phase 0
  resizes the window. The `finally` block compared equal sizes and skipped the
  osascript call. Fixed with `force=True` on the restore call.
- **Inconsistent body page heights**: `_find_header_bottom` returned slightly
  different y values per frame due to rendering variance (up to 44 px),
  producing pages of unequal height. Fixed by locking the crop y from the
  first reading-mode page dynamically (no hardcoded offsets).
- `--start-delay` default changed from 3 to 0; the ready prompt replaces its
  original "wait before starting" purpose.

### Changed

- Page-type discrimination replaced: `_has_dark_border` (checks for dark
  pixels at the left edge) removed from `detect_content_region`. Now uses
  luminance sampling below the macOS title bar — fully image-derived, no
  fixed thresholds.
- Phase 0 runs after the user presses Enter (post `click.pause()`), so Kindle
  is guaranteed to be displaying the cover page when the measurement occurs.

## [0.2.0] - 2026-04-14

### Added

- `_find_header_bottom()` in cropper: detects and strips macOS title bar,
  Kindle book-title header, and horizontal divider line from captures using
  image analysis (no fixed coordinates).
- `--pdf-dpi` CLI option (default 300) to control PDF page sizing. At 300
  DPI, 1800 px maps to 6 inches — a natural book-page width.
- Expanded README with feature list and practical usage examples.
- `--direction` and `--pdf-dpi` added to English and Japanese usage docs.

### Fixed

- PDF pages were excessively large (~25 inches wide) due to missing DPI
  layout. Pages are now sized for comfortable reading at 100% zoom.
- Captured images included macOS window chrome (title bar, traffic-light
  buttons) and Kindle header (book title, divider line). These are now
  automatically stripped before content-region detection.

### Changed

- Architecture docs updated to reflect the corrected capture-loop order
  (capture → header strip → crop → normalize → page turn → wait).

## [0.1.3] - 2026-04-13

### Added

- `--direction left/right` CLI option (default `right`) to select the
  page-advance key direction. Use `left` for RTL books (Japanese manga
  etc.) and `right` for LTR books (English etc.).

### Fixed

- Page-turn key is now sent *before* `wait_for_render`, not after.
  Previously the render-wait polled for a change that had not yet been
  triggered, causing a guaranteed timeout on every page.
- Replaced osascript key-code delivery with `CGEventPostToPid` (Quartz).
  osascript only targets the frontmost application, so key events were
  silently dropped whenever Kindle was in the background.
- `focus_window()` is now called once at startup to bring Kindle to the
  foreground before the capture loop begins.
- Brightness-based content detection added to the cropper via a
  `_has_dark_border` guard. Kindle's black chrome border and toolbar are
  now excluded from captured pages.
- Removed a duplicate-streak counter reset that fired on every
  successfully saved page, preventing end-of-book detection from ever
  accumulating to its threshold. The loop now stops automatically after
  3 consecutive identical frames.

## [0.1.2] - 2026-04-13

### Fixed

- Book cover pages with dark backgrounds no longer cause a fatal error.
  Capture now continues with a warning instead of stopping. Only a
  completely black frame (Screen Recording permission missing) or a
  completely white frame (Kindle loading screen) raises an error.

## [0.1.1] - 2026-04-13

### Fixed

- Replace Quartz `CGEventPost` with `osascript` for key-event injection.
  Accessibility permission now needs to be granted only to the terminal
  application (Terminal.app, iTerm2, Cursor, VSCode, etc.), not to the
  virtual-environment Python binary.

## [0.1.0] - 2026-04-13

### Added

- `cropper`: content-region detection via OpenCV contour analysis
- `normalize`: image resize, background whitening, sharpening, JPEG save
- `render_wait`: frame-diff polling for render completion detection
- `pdf_builder`: JPEG-to-PDF assembly (img2pdf) and optimisation (pikepdf)
- `ocr`: non-fatal ocrmypdf subprocess wrapper
- `window_capture`: Kindle window detection and screenshot (Quartz)
- `page_turner`: right-arrow key injection (Quartz Event Services)
- `orchestrator`: session state, skip logic, end-of-book detection, persistence
- `main`: Click CLI with all capture options (`kpc` entry point)
- Full test suite (hermetic, no macOS permissions required)
- Bilingual documentation (English and Japanese)
- GitHub PR/issue templates, Dependabot, and security policy

[Unreleased]: https://github.com/toshtag/kindle-pdf-capture/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/toshtag/kindle-pdf-capture/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/toshtag/kindle-pdf-capture/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/toshtag/kindle-pdf-capture/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/toshtag/kindle-pdf-capture/releases/tag/v0.1.0
