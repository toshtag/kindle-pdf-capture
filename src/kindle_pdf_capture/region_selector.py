"""Manual crop region selector using tkinter.

Displays a Kindle window screenshot as a full-screen canvas overlay and lets
the user drag a rectangle to define the capture area.  Pressing Enter confirms
the selection; Escape cancels.

Public API
----------
  select_region(frame) -> ContentRegion
      Show the selector UI and return the chosen ContentRegion.
      Raises RegionSelectorCancelled if the user pressed Escape or closed
      the window without confirming.

Pure-logic helpers (also exported for testing)
----------------------------------------------
  _clamp(value, lo, hi)            -- integer clamping
  _normalise_rect(x0, y0, x1, y1) -- ensure top-left / bottom-right order
  _rect_to_content_region(...)     -- pixel rect → ContentRegion
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

import numpy as np

from kindle_pdf_capture.cropper import ContentRegion

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RegionSelectorCancelled(RuntimeError):
    """Raised when the user cancels the region selector (Escape or close)."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _clamp(value: int, lo: int, hi: int) -> int:
    """Clamp *value* to the closed interval [lo, hi]."""
    return max(lo, min(hi, value))


def _normalise_rect(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) regardless of drag direction."""
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _rect_to_content_region(x0: int, y0: int, x1: int, y1: int) -> ContentRegion:
    """Convert a normalised pixel rectangle to a ContentRegion."""
    left, top, right, bottom = _normalise_rect(x0, y0, x1, y1)
    return ContentRegion(x=left, y=top, w=right - left, h=bottom - top)


# ---------------------------------------------------------------------------
# Selector UI
# ---------------------------------------------------------------------------

# Visual constants
_RECT_COLOUR = "#ff3333"  # red selection box
_RECT_WIDTH = 2
_MASK_COLOUR = "#000000"
_MASK_ALPHA = 0.45  # darken outside selection
_FONT_FAMILY = "Helvetica"
_FONT_SIZE = 14
_INSTRUCTIONS_EN = "Drag to select the book area, then press  Enter  to confirm  /  Esc  to cancel"
_INSTRUCTIONS_JA = "本のページ領域をドラッグで選択し、Enter で確定・Esc でキャンセル"


class RegionSelector:
    """tkinter-based drag-to-select UI.

    Parameters
    ----------
    frame : np.ndarray
        BGR screenshot of the Kindle window (as returned by capture_window).
    title : str
        Window title shown in the title bar.
    """

    def __init__(self, frame: np.ndarray, title: str = "Select capture region") -> None:
        self._frame_h, self._frame_w = frame.shape[:2]
        self._x0 = self._y0 = self._x1 = self._y1 = 0
        self._rect_id: int | None = None
        self._result: ContentRegion | None = None
        self._cancelled = False

        # Convert BGR→RGB then to a PhotoImage
        rgb = frame[:, :, ::-1].copy()
        from PIL import Image, ImageTk  # local import keeps top-level light

        pil_img = Image.fromarray(rgb)
        self._photo = ImageTk.PhotoImage(pil_img)

        self._root = tk.Tk()
        self._root.title(title)
        self._root.resizable(False, False)
        # Keep the window on top so it covers Kindle
        self._root.attributes("-topmost", True)

        self._canvas = tk.Canvas(
            self._root,
            width=self._frame_w,
            height=self._frame_h,
            cursor="crosshair",
            highlightthickness=0,
        )
        self._canvas.pack()
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)

        # Instruction label overlay
        self._canvas.create_text(
            self._frame_w // 2,
            20,
            text=_INSTRUCTIONS_EN,
            fill="white",
            font=(_FONT_FAMILY, _FONT_SIZE, "bold"),
            anchor=tk.N,
        )
        self._canvas.create_text(
            self._frame_w // 2,
            48,
            text=_INSTRUCTIONS_JA,
            fill="white",
            font=(_FONT_FAMILY, _FONT_SIZE),
            anchor=tk.N,
        )

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._root.bind("<Return>", self._on_confirm)
        self._root.bind("<KP_Enter>", self._on_confirm)
        self._root.bind("<Escape>", self._on_cancel)
        self._root.protocol("WM_DELETE_WINDOW", lambda: self._on_cancel(None))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_press(self, event: object) -> None:
        """Record the drag start position."""
        self._x0 = event.x  # type: ignore[attr-defined]
        self._y0 = event.y  # type: ignore[attr-defined]
        self._x1 = self._x0
        self._y1 = self._y0
        # Delete any previous selection box
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, event: object) -> None:
        """Update the selection rectangle as the mouse moves."""
        self._x1 = _clamp(event.x, 0, self._frame_w)  # type: ignore[attr-defined]
        self._y1 = _clamp(event.y, 0, self._frame_h)  # type: ignore[attr-defined]

        left, top, right, bottom = _normalise_rect(self._x0, self._y0, self._x1, self._y1)

        if self._rect_id is not None:
            self._canvas.coords(self._rect_id, left, top, right, bottom)
        else:
            self._rect_id = self._canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline=_RECT_COLOUR,
                width=_RECT_WIDTH,
            )

    def _on_confirm(self, _event: object) -> None:
        """Confirm the selection and stop the event loop."""
        left, top, right, bottom = _normalise_rect(self._x0, self._y0, self._x1, self._y1)
        if right - left < 1 or bottom - top < 1:
            # No meaningful rectangle drawn — treat as cancel
            self._cancelled = True
            if hasattr(self, "_root"):
                self._root.quit()
            return
        self._result = ContentRegion(x=left, y=top, w=right - left, h=bottom - top)
        if hasattr(self, "_root"):
            self._root.quit()

    def _on_cancel(self, _event: object) -> None:
        """Cancel the selection."""
        self._cancelled = True
        if hasattr(self, "_root"):
            self._root.quit()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> ContentRegion:
        """Start the event loop and return the selected ContentRegion.

        Raises
        ------
        RegionSelectorCancelled
            If the user pressed Escape or closed the window.
        """
        self._root.mainloop()
        self._root.destroy()
        if self._cancelled or self._result is None:
            raise RegionSelectorCancelled("User cancelled region selection.")
        return self._result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def select_region(frame: np.ndarray) -> ContentRegion:
    """Show the drag-select UI and return the chosen ContentRegion.

    Parameters
    ----------
    frame : np.ndarray
        BGR image to display as the selection backdrop (typically a
        screenshot of the Kindle window at the cover page).

    Returns
    -------
    ContentRegion
        The rectangle the user drew, in frame pixel coordinates.

    Raises
    ------
    RegionSelectorCancelled
        If the user cancelled without confirming a selection.
    """
    return RegionSelector(frame).run()
