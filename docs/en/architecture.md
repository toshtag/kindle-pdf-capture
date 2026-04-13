# Architecture

## Module overview

```
src/kindle_pdf_capture/
  __init__.py        # version
  main.py            # CLI entry point (click)
  orchestrator.py    # session state, skip logic, end-of-book detection
  window_capture.py  # Kindle window detection and screenshot (Quartz)
  page_turner.py     # right-arrow key injection (Quartz Event Services)
  render_wait.py     # frame-diff polling for render completion
  cropper.py         # content-region detection (OpenCV contours)
  normalize.py       # resize, whiten, sharpen, JPEG save (Pillow)
  pdf_builder.py     # JPEG -> PDF assembly (img2pdf) and optimization (pikepdf)
  ocr.py             # ocrmypdf subprocess wrapper
```

## Capture loop (per page)

```
find_kindle_window()
  -> CGWindowList filter: PID, layer=0, on-screen, largest area
  -> capture + content-page validation (brightness + edge density)

for each page:
  wait_for_render()        # poll frame diff until stable
  capture_window()         # take screenshot
  detect_content_region()  # contour analysis -> bounding box
  normalize_image()        # resize, whiten, sharpen
  save_jpeg()              # write cropped/page_XXXX.jpg
  send_right_arrow()       # turn page
  record_duplicate()       # MD5 of 16x16 downscale for end detection

build_pdf()                # img2pdf: JPEGs -> PDF
optimise_pdf()             # pikepdf: compress streams, atomic in-place
run_ocr()                  # ocrmypdf subprocess (optional)
```

## Testability

All macOS-specific calls (Quartz, AppKit) are abstracted behind injectable
function parameters with default implementations. Tests inject mocks, so the
full test suite runs on any platform without Screen Recording or Accessibility
permissions.

```python
# Production
find_kindle_window()

# Test
find_kindle_window(
    get_pid_fn=lambda _: 1234,
    list_windows_fn=lambda: [fake_window_info],
    capture_fn=lambda w: np.zeros((900, 1200, 3), dtype=np.uint8),
)
```

## End-of-book detection

The session tracks a duplicate-frame streak. After each page turn, the new
frame is hashed (MD5 of a 16x16 downscale). If the same hash appears
`_DUPLICATE_STREAK_LIMIT` (= 3) consecutive times without a successful capture
in between, the loop stops.

## CI / testing

- Tests: pytest, no macOS permissions required
- Lint: ruff check + ruff format
- Matrix: Python 3.11 and 3.12, macos-latest
- Unit tests are hermetic; E2E requires a real Kindle session (manual only)
