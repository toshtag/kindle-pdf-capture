# Installation

## Requirements

- macOS 12 or later
- Python 3.11 or later
- Kindle for Mac (install from the Mac App Store)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Install with uv (recommended)

```bash
uv tool install kindle-pdf-capture
```

## Install with pip

```bash
pip install kindle-pdf-capture
```

## Install with OCR support

OCR requires [Tesseract](https://github.com/tesseract-ocr/tesseract) and [Ghostscript](https://www.ghostscript.com/) as system dependencies, plus the `[ocr]` extra which installs `ocrmypdf`.

```bash
# 1. Install system dependencies (macOS)
brew install tesseract tesseract-lang ghostscript

# 2. Install the package with the OCR extra
uv tool install "kindle-pdf-capture[ocr]"
# or with pip:
pip install "kindle-pdf-capture[ocr]"
```

> **Note:** The `[ocr]` extra installs `ocrmypdf` automatically.
> Without it, running `kpc --ocr` will fail with "No such file or directory: 'ocrmypdf'".

## Install from source

```bash
git clone https://github.com/toshtag/kindle-pdf-capture.git
cd kindle-pdf-capture

# Without OCR support
uv sync

# With OCR support (also installs ocrmypdf)
brew install tesseract tesseract-lang ghostscript
uv sync --all-extras

uv run kpc --help
```

## macOS permissions

Before running, grant the following permissions to Terminal (or iTerm, whichever you use):

1. **Screen Recording** — System Settings > Privacy & Security > Screen Recording
2. **Accessibility** — System Settings > Privacy & Security > Accessibility

See the [permissions guide](permissions.md) for step-by-step instructions.
