"""Manual crop region selector using tkinter.

Displays a Kindle window screenshot scaled to fit the screen and lets
the user drag a rectangle to define the capture area.  Pressing Enter
confirms the selection; Escape cancels.

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

import numpy as np

from kindle_pdf_capture.cropper import ContentRegion

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
# Visual constants
# ---------------------------------------------------------------------------

_RECT_COLOUR = "#00d4ff"  # bright cyan selection box
_RECT_WIDTH = 3
_MASK_COLOUR = "#000000"  # semi-transparent dark overlay outside selection
_MASK_STIPPLE = "gray50"  # tkinter stipple pattern (~50% opacity)
_FONT_FAMILY = "Helvetica"
_FONT_SIZE = 15
_INSTRUCTIONS_EN = "Drag to select the book area  •  Enter to confirm  •  Esc to cancel"
_INSTRUCTIONS_JA = "本のページ領域をドラッグ選択  •  Enter で確定  •  Esc でキャンセル"
# Margin reserved at the top for the instruction bar (logical pixels)
_INSTR_BAR_H = 60


class RegionSelector:
    """tkinter-based drag-to-select UI.

    The frame is scaled down to fit inside the usable screen area so that
    Retina / HiDPI frames (e.g. 2560x1758 physical pixels) are displayed at
    a sensible size.  All coordinates the user drags are in *display* pixels;
    they are scaled back to *frame* pixels before returning the ContentRegion.

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
        # Four overlay rectangles (top, bottom, left, right) that darken the
        # area outside the current selection.
        self._mask_ids: list[int] = []
        self._result: ContentRegion | None = None
        self._cancelled = False

        # --- Tk root (must exist before PhotoImage) ---
        self._root = tk.Tk()
        self._root.title(title)
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)

        # --- Determine display scale so the image fits the screen ---
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        # Reserve space for macOS menu bar (~25 px) + instruction bar
        usable_h = screen_h - 25 - _INSTR_BAR_H
        scale = min(screen_w / self._frame_w, usable_h / self._frame_h, 1.0)
        self._scale = scale
        self._disp_w = max(1, int(self._frame_w * scale))
        self._disp_h = max(1, int(self._frame_h * scale))

        # --- Scale the image for display ---
        from PIL import Image, ImageTk

        rgb = frame[:, :, ::-1].copy()
        pil_img = Image.fromarray(rgb)
        if scale < 1.0:
            pil_img = pil_img.resize(
                (self._disp_w, self._disp_h),
                Image.LANCZOS,  # type: ignore[attr-defined]
            )
        self._photo = ImageTk.PhotoImage(pil_img)

        # Total canvas height: instruction bar + image
        total_h = _INSTR_BAR_H + self._disp_h

        # --- Canvas ---
        self._canvas = tk.Canvas(
            self._root,
            width=self._disp_w,
            height=total_h,
            cursor="crosshair",
            highlightthickness=0,
            bg="#1a1a1a",
        )
        self._canvas.pack()

        # Instruction bar background
        self._canvas.create_rectangle(
            0,
            0,
            self._disp_w,
            _INSTR_BAR_H,
            fill="#1a1a1a",
            outline="",
        )

        # Instruction texts with drop-shadow for legibility
        for dx, dy in ((1, 1), (-1, -1), (1, -1), (-1, 1)):
            self._canvas.create_text(
                self._disp_w // 2 + dx,
                16 + dy,
                text=_INSTRUCTIONS_EN,
                fill="#000000",
                font=(_FONT_FAMILY, _FONT_SIZE, "bold"),
                anchor=tk.N,
            )
        self._canvas.create_text(
            self._disp_w // 2,
            16,
            text=_INSTRUCTIONS_EN,
            fill="#ffffff",
            font=(_FONT_FAMILY, _FONT_SIZE, "bold"),
            anchor=tk.N,
        )
        for dx, dy in ((1, 1), (-1, -1)):
            self._canvas.create_text(
                self._disp_w // 2 + dx,
                40 + dy,
                text=_INSTRUCTIONS_JA,
                fill="#000000",
                font=(_FONT_FAMILY, _FONT_SIZE),
                anchor=tk.N,
            )
        self._canvas.create_text(
            self._disp_w // 2,
            40,
            text=_INSTRUCTIONS_JA,
            fill="#cccccc",
            font=(_FONT_FAMILY, _FONT_SIZE),
            anchor=tk.N,
        )

        # Kindle screenshot below the instruction bar
        self._img_y0 = _INSTR_BAR_H
        self._canvas.create_image(0, self._img_y0, anchor=tk.NW, image=self._photo)

        # Event bindings (drag only within the image area)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._root.bind("<Return>", self._on_confirm)
        self._root.bind("<KP_Enter>", self._on_confirm)
        self._root.bind("<Escape>", self._on_cancel)
        self._root.protocol("WM_DELETE_WINDOW", lambda: self._on_cancel(None))

    # ------------------------------------------------------------------
    # Internal geometry helpers
    # ------------------------------------------------------------------

    def _img_clamp_x(self, x: int) -> int:
        return _clamp(x, 0, self._disp_w)

    def _img_clamp_y(self, y: int) -> int:
        """Clamp to image area (below instruction bar)."""
        return _clamp(y, self._img_y0, self._img_y0 + self._disp_h)

    def _redraw_overlay(self, left: int, top: int, right: int, bottom: int) -> None:
        """Redraw the four dark mask rectangles around the selection."""
        for mid in self._mask_ids:
            self._canvas.delete(mid)
        self._mask_ids = []

        iw, ih = self._disp_w, self._disp_h
        iy = self._img_y0

        def _mask(x1: int, y1: int, x2: int, y2: int) -> None:
            if x2 > x1 and y2 > y1:
                mid = self._canvas.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=_MASK_COLOUR,
                    outline="",
                    stipple=_MASK_STIPPLE,
                )
                self._mask_ids.append(mid)

        # Top strip (between instruction bar and selection)
        _mask(0, iy, iw, top)
        # Bottom strip
        _mask(0, bottom, iw, iy + ih)
        # Left strip (between top and bottom of selection)
        _mask(0, top, left, bottom)
        # Right strip
        _mask(right, top, iw, bottom)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_press(self, event: object) -> None:
        x = event.x  # type: ignore[attr-defined]
        y = self._img_clamp_y(event.y)  # type: ignore[attr-defined]
        self._x0 = self._img_clamp_x(x)
        self._y0 = y
        self._x1 = self._x0
        self._y1 = self._y0
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
            self._rect_id = None
        for mid in self._mask_ids:
            self._canvas.delete(mid)
        self._mask_ids = []

    def _on_drag(self, event: object) -> None:
        self._x1 = self._img_clamp_x(event.x)  # type: ignore[attr-defined]
        self._y1 = self._img_clamp_y(event.y)  # type: ignore[attr-defined]

        left, top, right, bottom = _normalise_rect(self._x0, self._y0, self._x1, self._y1)

        # Redraw dark mask outside selection
        self._redraw_overlay(left, top, right, bottom)

        # Redraw selection rectangle on top of mask
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
        self._rect_id = self._canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline=_RECT_COLOUR,
            width=_RECT_WIDTH,
        )

    def _on_confirm(self, _event: object) -> None:
        left, top, right, bottom = _normalise_rect(self._x0, self._y0, self._x1, self._y1)
        if right - left < 1 or bottom - top < 1:
            self._cancelled = True
            if hasattr(self, "_root"):
                self._root.quit()
            return
        # Convert display coordinates back to frame pixel coordinates
        iy = self._img_y0
        fx0 = round((left) / self._scale)
        fy0 = round((top - iy) / self._scale)
        fx1 = round((right) / self._scale)
        fy1 = round((bottom - iy) / self._scale)
        # Clamp to frame bounds
        fx0 = _clamp(fx0, 0, self._frame_w)
        fy0 = _clamp(fy0, 0, self._frame_h)
        fx1 = _clamp(fx1, 0, self._frame_w)
        fy1 = _clamp(fy1, 0, self._frame_h)
        self._result = ContentRegion(x=fx0, y=fy0, w=fx1 - fx0, h=fy1 - fy0)
        if hasattr(self, "_root"):
            self._root.quit()

    def _on_cancel(self, _event: object) -> None:
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
        The rectangle the user drew, in *frame* pixel coordinates
        (not display/scaled coordinates).

    Raises
    ------
    RegionSelectorCancelled
        If the user cancelled without confirming a selection.
    """
    return RegionSelector(frame).run()
