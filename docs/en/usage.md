# Usage

## Basic capture

Open Kindle for Mac and navigate to the first page of a book, then run:

```bash
kpc --out output/my-book
```

You have `--start-delay` seconds (default 3) to switch focus to Kindle before capture begins.

## All options

| Option | Default | Description |
|--------|---------|-------------|
| `--out PATH` | (required) | Output directory |
| `--max-pages N` | 1000 | Stop after N pages |
| `--resize-width N` | 1800 | Resize each page to N pixels wide |
| `--jpeg-quality N` | 80 | JPEG quality 1-95 |
| `--save-raw` | off | Also save uncropped screenshots |
| `--start-delay N` | 3 | Seconds before capture starts |
| `--direction DIR` | `right` | Page-advance direction: `right` for LTR, `left` for RTL (manga) |
| `--pdf-dpi N` | 300 | DPI for PDF page sizing (300 maps 1800 px to 6 inches) |
| `--ocr` | off | Embed a Tesseract text layer in the PDF (requires the `[ocr]` extra — see [installation](installation.md#install-with-ocr-support) and the note below) |
| `--ocr-lang LANG` | `jpn+eng` | Tesseract language string |
| `--ocr-optimize N` | 1 | OCR optimization level 0-3 |
| `--manual-crop` | off | Manually select the cover region via drag-to-select UI instead of auto-detection (useful when the cover is all-white) |
| `--retry-failed` | off | Re-capture pages from `logs/failed_pages.json` |
| `--debug` | off | Enable debug logging |

## Output layout

```
output/my-book/
  cropped/          # page_0001.jpg, page_0002.jpg, ...
  raw/              # uncropped screenshots (only with --save-raw)
  pdf/
    book.pdf        # assembled PDF
    book_ocr.pdf    # OCR version (only with --ocr)
  logs/
    metadata.json   # run summary
    failed_pages.json
```

## OCR and macOS Live Text

**On macOS (the only supported platform), you likely do not need `--ocr`.**

`book.pdf` contains no text data — it is a sequence of JPEG images. However,
macOS Preview and other PDF viewers use Apple's built-in Live Text engine to
recognise characters on the fly. This gives you accurate text selection, copy,
and right-click search without any extra step, and Apple's Japanese recognition
quality is generally higher than Tesseract's.

`--ocr` embeds a Tesseract-generated text layer directly into `book_ocr.pdf`.
The viewer then uses that embedded layer instead of Live Text. If Tesseract's
character positions differ slightly from the actual glyph positions, text
selection will appear to drift or select the wrong characters.

**When `--ocr` is useful:**

- You need the PDF to be searchable on Windows, Linux, or older macOS versions
  where Live Text is unavailable.
- You are passing the PDF to a tool (full-text indexer, screen reader, etc.)
  that reads embedded text rather than running its own OCR.

## Retrying failed pages

If some pages failed (captured as blank or with errors), re-run with `--retry-failed`:

```bash
kpc --out output/my-book --retry-failed
```

This reads `logs/failed_pages.json` and recaptures only those pages, leaving all others intact.

## Examples

```bash
# Capture up to 300 pages, high quality
kpc --out output/my-book --max-pages 300 --jpeg-quality 90

# Capture a right-to-left book (Japanese manga etc.)
kpc --out output/my-manga --direction left

# Capture with OCR (Japanese + English)
kpc --out output/my-book --ocr --ocr-lang jpn+eng

# Capture a book with an all-white cover (manual region selection)
kpc --out output/my-book --manual-crop

# Capture with extra logging and save raw screenshots
kpc --out output/my-book --save-raw --debug
```
