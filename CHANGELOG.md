# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/toshtag/kindle-pdf-capture/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/toshtag/kindle-pdf-capture/releases/tag/v0.1.0
