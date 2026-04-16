# Troubleshooting

## "Kindle is not running"

Kindle for Mac is not open, or is not recognized by name.

- Open Kindle for Mac from the Applications folder or Mac App Store.
- Navigate to a book (not the library or store).
- Re-run `kpc`.

## "No suitable reading window was found"

Kindle is running but no suitable window was detected.

- Make sure a book is open and the reading window is visible (not minimized).
- The window must be at least 800x600 pixels.
- Try resizing the Kindle window to be larger.

## "The Kindle window does not appear to show a content page"

The captured window looks like the library, store, or a loading screen rather than a book page.

- Navigate to the first page of the book.
- Wait for the page to fully load before running `kpc`.

## "Accessibility permission is required"

The process does not have permission to send key events.

- See the [permissions guide](permissions.md) for setup instructions.
- After granting permission, restart the terminal and try again.

## Pages are blank or mostly white

The capture is running before the page has finished rendering.

- Increase `--start-delay` to give yourself more time to focus Kindle.
- The `wait_for_render` logic polls for frame stability, but very slow network
  or DRM decryption may exceed the default 8-second timeout. This is logged as
  a warning.

## Content-region detection fails on all-white covers

Books whose cover page is entirely white have no visible contours, so the
auto-detection step cannot infer the correct window size.

- Run with `--manual-crop`. A full-screen overlay appears showing the Kindle
  window screenshot. Drag a rectangle over the cover area, use the 8 handles
  (corners + edge midpoints) to fine-tune, then press **Enter** to confirm.
  Press **Esc** or close the window to abort.
- After confirmation `kpc` resizes the window to match your selection and
  proceeds with the normal pipeline for all subsequent pages.

## PDF has wrong page order

Pages are assembled from `cropped/page_XXXX.jpg` in alphabetical order.
If files from a previous partial run exist, they may interleave with new ones.

- Delete the `cropped/` directory and re-run, or
- Use `--retry-failed` to fill in only the missing pages.

## OCR fails silently

OCR failure is non-fatal by design. The non-OCR PDF is always produced.

- Check the log for a warning line containing the return code.
- Verify that `tesseract` and `ghostscript` are installed: `which tesseract && which gs`
- Try running `ocrmypdf` directly on the PDF to see the full error output.
- Add `--debug` to see detailed logs including the exact `ocrmypdf` exit code.

## Capturing wrong window

If another application shares the "Kindle" process name, the wrong window may be selected.

- Close other applications and try again.
- Use `--debug` to see which window (PID, size, position) was selected.
