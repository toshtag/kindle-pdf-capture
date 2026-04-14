# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/toshtag/kindle-pdf-capture/releases/tag/v0.1.0
