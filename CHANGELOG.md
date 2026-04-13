# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/toshtag/kindle-pdf-capture/compare/HEAD...HEAD
