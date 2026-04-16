"""Manual crop region selector using tkinter.

Displays a Kindle window screenshot scaled to fit the screen and lets
the user drag a rectangle to define the capture area.  Pressing Enter
confirms the selection; Escape cancels.

Coordinate system
-----------------
tkinter operates in *logical points* (not physical pixels).  On Retina
Macs one point = 2 physical pixels (backing_scale = 2.0).

capture_window() returns a frame in *physical pixels*.

So the pipeline is:
  frame (physical px)
    → PIL.resize to (disp_pts_w, disp_pts_h)   [logical points]
    → displayed on Canvas (width=disp_pts_w pts)
  drag events arrive in logical points
    → multiply by pts_per_frame_px to get frame pixels

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
  _rect_to_content_region(...)     -- pixel rect -> ContentRegion
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
# Screen geometry helper
# ---------------------------------------------------------------------------


def _get_screen_pts() -> tuple[int, int]:
    """Return (width, height) of the main screen in logical points.

    Tries NSScreen first (reliable on macOS).  Falls back to a fixed
    safe value so tests on non-macOS still work.
    """
    try:
        from AppKit import NSScreen  # type: ignore[import]

        f = NSScreen.mainScreen().frame()
        return int(f.size.width), int(f.size.height)
    except Exception:
        return 1280, 800


# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------

_RECT_COLOUR = "#00d4ff"  # bright cyan selection box
_RECT_WIDTH = 3
_MASK_COLOUR = "#000000"  # dark overlay outside selection
_MASK_STIPPLE = "gray50"  # ~50% opacity via tkinter stipple
_FONT_FAMILY = "Helvetica"
_FONT_SIZE = 15
_INSTRUCTIONS_EN = "Drag to select the book area  |  Enter: confirm  |  Esc: cancel"
_INSTRUCTIONS_JA = "本のページ領域をドラッグ選択  |  Enter で確定  |  Esc でキャンセル"
_INSTR_BAR_H = 60  # logical points reserved for instruction bar at top


class RegionSelector:
    """tkinter drag-to-select UI.

    All internal geometry (canvas size, event coordinates, clamping) is in
    *logical points*.  Coordinate conversion to frame pixels happens only in
    _on_confirm, using self._pts_to_px (points -> frame pixel ratio).

    Parameters
    ----------
    frame : np.ndarray
        BGR screenshot of the Kindle window (capture_window output).
    title : str
        Window title bar text.
    """

    def __init__(self, frame: np.ndarray, title: str = "Select capture region") -> None:
        self._frame_h, self._frame_w = frame.shape[:2]
        self._x0 = self._y0 = self._x1 = self._y1 = 0
        self._rect_id: int | None = None
        self._mask_ids: list[int] = []
        self._result: ContentRegion | None = None
        self._cancelled = False

        # --- Tk root ---
        self._root = tk.Tk()
        self._root.title(title)
        self._root.resizable(False, False)

        # --- Compute display size in logical points ---
        screen_w, screen_h = _get_screen_pts()
        # Reserve macOS menu bar (~25 pts) + instruction bar
        usable_w = screen_w
        usable_h = screen_h - 25 - _INSTR_BAR_H
        # Fit the frame inside usable area (no upscaling)
        scale = min(usable_w / self._frame_w, usable_h / self._frame_h, 1.0)
        # Display dimensions in logical points (tkinter unit)
        self._disp_w = max(1, int(self._frame_w * scale))
        self._disp_h = max(1, int(self._frame_h * scale))
        # pts_to_px: multiply logical-point drag coords by this to get frame px
        self._pts_to_px = self._frame_w / self._disp_w  # == 1/scale

        # --- Resize image to display size (in logical points) ---
        from PIL import Image, ImageTk

        rgb = frame[:, :, ::-1].copy()
        pil_img = Image.fromarray(rgb)
        pil_img = pil_img.resize((self._disp_w, self._disp_h), Image.LANCZOS)  # type: ignore[attr-defined]
        self._photo = ImageTk.PhotoImage(pil_img)

        # Canvas height = instruction bar + image
        total_h = _INSTR_BAR_H + self._disp_h
        self._img_y0 = _INSTR_BAR_H  # y offset of image top edge in canvas points

        # --- Size and position the window ---
        self._root.geometry(f"{self._disp_w}x{total_h}+0+0")
        self._root.attributes("-topmost", True)
        self._root.lift()
        self._root.focus_force()

        # --- Canvas ---
        self._canvas = tk.Canvas(
            self._root,
            width=self._disp_w,
            height=total_h,
            cursor="crosshair",
            highlightthickness=0,
            bg="#1a1a1a",
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Instruction bar background
        self._canvas.create_rectangle(
            0,
            0,
            self._disp_w,
            _INSTR_BAR_H,
            fill="#1a1a1a",
            outline="",
        )

        # Instruction text with drop-shadow
        cx = self._disp_w // 2
        for dx, dy in ((1, 1), (-1, -1), (1, -1), (-1, 1)):
            self._canvas.create_text(
                cx + dx,
                16 + dy,
                text=_INSTRUCTIONS_EN,
                fill="#000000",
                font=(_FONT_FAMILY, _FONT_SIZE, "bold"),
                anchor=tk.N,
            )
        self._canvas.create_text(
            cx,
            16,
            text=_INSTRUCTIONS_EN,
            fill="#ffffff",
            font=(_FONT_FAMILY, _FONT_SIZE, "bold"),
            anchor=tk.N,
        )
        for dx, dy in ((1, 1), (-1, -1)):
            self._canvas.create_text(
                cx + dx,
                40 + dy,
                text=_INSTRUCTIONS_JA,
                fill="#000000",
                font=(_FONT_FAMILY, _FONT_SIZE),
                anchor=tk.N,
            )
        self._canvas.create_text(
            cx,
            40,
            text=_INSTRUCTIONS_JA,
            fill="#cccccc",
            font=(_FONT_FAMILY, _FONT_SIZE),
            anchor=tk.N,
        )

        # Kindle screenshot below instruction bar
        self._canvas.create_image(0, self._img_y0, anchor=tk.NW, image=self._photo)

        # Bindings
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._root.bind("<Return>", self._on_confirm)
        self._root.bind("<KP_Enter>", self._on_confirm)
        self._root.bind("<Escape>", self._on_cancel)
        self._root.protocol("WM_DELETE_WINDOW", lambda: self._on_cancel(None))

    # ------------------------------------------------------------------
    # Clamping helpers (all in logical points)
    # ------------------------------------------------------------------

    def _cx(self, x: int) -> int:
        return _clamp(x, 0, self._disp_w)

    def _cy(self, y: int) -> int:
        return _clamp(y, self._img_y0, self._img_y0 + self._disp_h)

    # ------------------------------------------------------------------
    # Overlay (dark mask outside selection)
    # ------------------------------------------------------------------

    def _redraw_overlay(self, left: int, top: int, right: int, bottom: int) -> None:
        for mid in self._mask_ids:
            self._canvas.delete(mid)
        self._mask_ids = []

        iw = self._disp_w
        iy = self._img_y0
        ih = self._disp_h

        def _mask(x1: int, y1: int, x2: int, y2: int) -> None:
            if x2 > x1 and y2 > y1:
                self._mask_ids.append(
                    self._canvas.create_rectangle(
                        x1,
                        y1,
                        x2,
                        y2,
                        fill=_MASK_COLOUR,
                        outline="",
                        stipple=_MASK_STIPPLE,
                    )
                )

        _mask(0, iy, iw, top)  # above selection
        _mask(0, bottom, iw, iy + ih)  # below selection
        _mask(0, top, left, bottom)  # left of selection
        _mask(right, top, iw, bottom)  # right of selection

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_press(self, event: object) -> None:
        self._x0 = self._cx(event.x)  # type: ignore[attr-defined]
        self._y0 = self._cy(event.y)  # type: ignore[attr-defined]
        self._x1 = self._x0
        self._y1 = self._y0
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
            self._rect_id = None
        for mid in self._mask_ids:
            self._canvas.delete(mid)
        self._mask_ids = []

    def _on_drag(self, event: object) -> None:
        self._x1 = self._cx(event.x)  # type: ignore[attr-defined]
        self._y1 = self._cy(event.y)  # type: ignore[attr-defined]
        left, top, right, bottom = _normalise_rect(self._x0, self._y0, self._x1, self._y1)
        self._redraw_overlay(left, top, right, bottom)
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
        # Convert logical-point drag coords to frame pixel coords.
        # pts_to_px = frame_w / disp_w  (how many frame pixels per display point)
        p = self._pts_to_px
        iy = self._img_y0
        fx0 = _clamp(round(left * p), 0, self._frame_w)
        fy0 = _clamp(round((top - iy) * p), 0, self._frame_h)
        fx1 = _clamp(round(right * p), 0, self._frame_w)
        fy1 = _clamp(round((bottom - iy) * p), 0, self._frame_h)
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
        BGR image (physical pixels) from capture_window.

    Returns
    -------
    ContentRegion
        Selected rectangle in *frame* pixel coordinates.

    Raises
    ------
    RegionSelectorCancelled
        If the user cancelled without confirming a selection.
    """
    return RegionSelector(frame).run()
