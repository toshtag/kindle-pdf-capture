# kindle-pdf-capture

Capture Kindle for Mac pages via screen recording and build a high-quality PDF (with optional OCR).

> 📚 Languages: [English](docs/en/) · [日本語](docs/ja/)

## Features

- Automatic content-region detection (strips window chrome, title bar, and Kindle header)
- Background capture via Quartz — no need to keep Kindle in the foreground
- Smart page-turn detection (frame-diff polling, no fixed sleep)
- LTR and RTL (manga) support via `--direction`
- Book-like PDF page sizing (300 DPI default)
- Optional OCR text layer (Japanese + English)
- End-of-book auto-detection (duplicate-frame streak)

## Quick start

```bash
# Install
uv sync

# Capture a book (open Kindle to the first page first)
uv run kpc --out output/my-book

# Capture a right-to-left book (manga)
uv run kpc --out output/my-manga --direction left

# Capture with OCR
uv run kpc --out output/my-book --ocr

# See all options
uv run kpc --help
```

## Documentation

- [Installation](docs/en/installation.md) · [インストール](docs/ja/installation.md)
- [Usage](docs/en/usage.md) · [使い方](docs/ja/usage.md)
- [macOS permissions](docs/en/permissions.md) · [macOS 権限](docs/ja/permissions.md)
- [Architecture](docs/en/architecture.md) · [アーキテクチャ](docs/ja/architecture.md)
- [Troubleshooting](docs/en/troubleshooting.md) · [トラブルシューティング](docs/ja/troubleshooting.md)
- [Legal](docs/en/legal.md) · [法的事項](docs/ja/legal.md)

## License

MIT — see [LICENSE](LICENSE).
