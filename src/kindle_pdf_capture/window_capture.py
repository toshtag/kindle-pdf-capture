"""Kindle for Mac window detection and screen capture.

Detection priority (per spec):
  1. Locate the Kindle process by name to get its PID.
  2. Filter CGWindowList to that PID only.
  3. Among candidates, select layer=0, on-screen, largest area.
  4. Capture the window; verify it looks like a book reading page.

All Quartz calls are abstracted behind injectable callables so the module
is fully testable without macOS screen-recording permissions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Minimum window size to be considered the reading window
_MIN_WIDTH = 800
_MIN_HEIGHT = 600

# Content-page heuristics
_MIN_BRIGHTNESS_RATIO = 0.50  # at least 50% of pixels are bright (near-white)
_MIN_EDGE_DENSITY = 0.005  # at least 0.5% of pixels have edges (text strokes)

# Thresholds for degenerate captures
_ALL_BLACK_THRESHOLD = 10  # mean luminance below this → screen recording blocked
_ALL_WHITE_THRESHOLD = 250  # mean luminance above this → loading screen


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class KindleWindow:
    """Describes a located Kindle window."""

    pid: int
    window_id: int
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


class WindowCaptureError(RuntimeError):
    """Raised when the Kindle window cannot be located or validated."""


# ---------------------------------------------------------------------------
# Helpers (pure logic, injectable in tests)
# ---------------------------------------------------------------------------


def _pick_best_window(
    window_list: list[dict],
    *,
    kindle_pid: int,
) -> KindleWindow | None:
    """Select the best candidate from a raw CGWindowList result.

    Criteria (all must pass):
    - ``kCGWindowOwnerPID`` == kindle_pid
    - ``kCGWindowLayer`` == 0
    - ``kCGWindowIsOnscreen`` is truthy
    - Width >= _MIN_WIDTH and Height >= _MIN_HEIGHT

    Among passing candidates, returns the one with the largest area.
    Negative x/y coordinates are accepted (multi-monitor setups).
    """
    best: KindleWindow | None = None
    best_area = 0

    for info in window_list:
        if info.get("kCGWindowOwnerPID") != kindle_pid:
            continue
        if info.get("kCGWindowLayer") != 0:
            continue
        if not info.get("kCGWindowIsOnscreen"):
            continue

        bounds = info.get("kCGWindowBounds", {})
        w = int(bounds.get("Width", 0))
        h = int(bounds.get("Height", 0))
        if w < _MIN_WIDTH or h < _MIN_HEIGHT:
            continue

        x = int(bounds.get("X", 0))
        y = int(bounds.get("Y", 0))
        wid = int(info.get("kCGWindowNumber", 0))
        area = w * h

        if area > best_area:
            best_area = area
            best = KindleWindow(pid=kindle_pid, window_id=wid, x=x, y=y, width=w, height=h)

    return best


def _is_all_black(bgr: np.ndarray) -> bool:
    """Return True when the image is uniformly black (screen recording blocked)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) < _ALL_BLACK_THRESHOLD


def _is_all_white(bgr: np.ndarray) -> bool:
    """Return True when the image is uniformly white (Kindle loading screen)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()) > _ALL_WHITE_THRESHOLD


def _is_content_page(bgr: np.ndarray) -> bool:
    """Return True when *bgr* looks like a Kindle book-reading page.

    Heuristics:
    - At least ``_MIN_BRIGHTNESS_RATIO`` of pixels have luminance >= 200
      (white-ish background).
    - At least ``_MIN_EDGE_DENSITY`` of pixels are edge pixels (character
      strokes detected by Canny).

    Returns False for: blank-white loading screens, all-black screens,
    library/store icon grids.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    total = gray.size

    bright_ratio = float((gray >= 200).sum()) / total
    if bright_ratio < _MIN_BRIGHTNESS_RATIO:
        return False

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float((edges > 0).sum()) / total
    return edge_density >= _MIN_EDGE_DENSITY


# ---------------------------------------------------------------------------
# Window resize (Accessibility API)
# ---------------------------------------------------------------------------


def _default_ax_resize(pid: int, width: int, height: int) -> None:
    """Resize the frontmost window of *pid* via the macOS Accessibility API."""
    try:
        from ApplicationServices import (  # type: ignore[import]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            AXUIElementSetAttributeValue,
            kAXSizeAttribute,
            kAXWindowsAttribute,
        )
        from CoreFoundation import CGSizeMake  # type: ignore[import]

        app = AXUIElementCreateApplication(pid)
        err, windows = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, None)
        if err != 0 or not windows:
            logger.warning("AX resize: could not list windows for pid=%d (err=%d)", pid, err)
            return
        win = windows[0]
        new_size = CGSizeMake(width, height)
        err2 = AXUIElementSetAttributeValue(win, kAXSizeAttribute, new_size)
        if err2 != 0:
            logger.warning("AX resize: SetAttributeValue failed (err=%d)", err2)
    except Exception as exc:
        logger.warning("AX resize failed: %s", exc)


def resize_kindle_window(
    window: KindleWindow,
    *,
    target_width: int,
    target_height: int,
    resize_fn: Callable[[int, int, int], None] = _default_ax_resize,
) -> tuple[int, int]:
    """Resize the Kindle window to *target_width* x *target_height*.

    Returns the original (width, height) so the caller can restore it later.
    If the window is already the target size, *resize_fn* is not called.

    Args:
        window: The KindleWindow to resize.
        target_width: Desired window width in logical pixels.
        target_height: Desired window height in logical pixels.
        resize_fn: Injectable callable ``(pid, width, height) → None``
            (default: Accessibility API).

    Returns:
        ``(original_width, original_height)`` tuple.
    """
    orig_w, orig_h = window.width, window.height
    if orig_w != target_width or orig_h != target_height:
        resize_fn(window.pid, target_width, target_height)
        logger.debug("Window resized: %dx%d → %dx%d", orig_w, orig_h, target_width, target_height)
    return orig_w, orig_h


# ---------------------------------------------------------------------------
# Default Quartz implementations (macOS only)
# ---------------------------------------------------------------------------


def _default_get_pid(process_name: str) -> int | None:
    """Return the PID of *process_name* using Quartz / AppKit, or None."""
    try:
        from Quartz import CGWindowListCopyWindowInfo, kCGNullWindowID, kCGWindowListOptionAll

        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)
        for w in windows:
            if w.get("kCGWindowOwnerName") == process_name:
                return int(w["kCGWindowOwnerPID"])
    except Exception as exc:
        logger.debug("_default_get_pid failed: %s", exc)
    return None


def _default_list_windows() -> list[dict]:
    """Return raw CGWindowList data for all windows."""
    try:
        from Quartz import CGWindowListCopyWindowInfo, kCGNullWindowID, kCGWindowListOptionAll

        return list(CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID))
    except Exception as exc:
        logger.debug("_default_list_windows failed: %s", exc)
        return []


def _default_capture(window: KindleWindow) -> np.ndarray:
    """Capture *window* using CGWindowListCreateImage and return a BGR ndarray."""
    try:
        import Quartz
        from Quartz import (
            CGRectMake,
            CGWindowListCreateImage,
            kCGWindowImageBoundsIgnoreFraming,
            kCGWindowImageShouldBeOpaque,
            kCGWindowListOptionIncludingWindow,
        )

        rect = CGRectMake(0, 0, 0, 0)  # null rect = use window bounds
        cg_image = CGWindowListCreateImage(
            rect,
            kCGWindowListOptionIncludingWindow,
            window.window_id,
            kCGWindowImageBoundsIgnoreFraming | kCGWindowImageShouldBeOpaque,
        )
        if cg_image is None:
            raise WindowCaptureError(
                f"CGWindowListCreateImage returned None for wid={window.window_id}"
            )

        width = Quartz.CGImageGetWidth(cg_image)
        height = Quartz.CGImageGetHeight(cg_image)
        bpc = Quartz.CGImageGetBitsPerComponent(cg_image)
        bpp = Quartz.CGImageGetBitsPerPixel(cg_image)
        bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)

        from Quartz.CoreGraphics import CGDataProviderCopyData

        raw = CGDataProviderCopyData(Quartz.CGImageGetDataProvider(cg_image))
        # CGImage row data may include padding bytes for memory alignment.
        # Reshape using the actual bytes_per_row stride, then slice to true width.
        channels = bpp // bpc
        stride_pixels = bytes_per_row // channels
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((height, stride_pixels, channels))
        # Slice to true pixel width and drop alpha (CG returns BGRA → BGR)
        bgr = arr[:, :width, :3].copy()
        return bgr
    except WindowCaptureError:
        raise
    except Exception as exc:
        raise WindowCaptureError(f"Screen capture failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_kindle_window(
    *,
    get_pid_fn: Callable[[str], int | None] = _default_get_pid,
    list_windows_fn: Callable[[], list[dict]] = _default_list_windows,
    capture_fn: Callable[[KindleWindow], np.ndarray] = _default_capture,
    process_name: str = "Kindle",
) -> KindleWindow:
    """Locate the Kindle reading window with full validation.

    Steps:
    1. ``get_pid_fn(process_name)`` → PID (raises if not found).
    2. ``list_windows_fn()`` → filter by PID, layer, visibility, size.
    3. ``capture_fn(window)`` → screenshot.
    4. ``_is_content_page(screenshot)`` → verify it's a reading page.

    Args:
        get_pid_fn: Callable that returns the PID for a process name.
        list_windows_fn: Callable that returns raw window-info dicts.
        capture_fn: Callable that screenshots a KindleWindow.
        process_name: macOS process name for Kindle.

    Returns:
        Validated KindleWindow.

    Raises:
        WindowCaptureError: With a user-friendly message for each failure mode.
    """
    pid = get_pid_fn(process_name)
    if pid is None:
        raise WindowCaptureError(
            "Kindle is not running. Please open Kindle for Mac and navigate to a book page."
        )

    window_list = list_windows_fn()
    window = _pick_best_window(window_list, kindle_pid=pid)
    if window is None:
        raise WindowCaptureError(
            "Kindle is running but no suitable reading window was found. "
            "Please open a book and make the window at least 800x600."
        )

    logger.info(
        "Kindle window: pid=%d wid=%d size=%dx%d at (%d,%d)",
        window.pid,
        window.window_id,
        window.width,
        window.height,
        window.x,
        window.y,
    )

    screenshot = capture_fn(window)
    if _is_all_black(screenshot):
        raise WindowCaptureError(
            "The captured Kindle window is completely black. "
            "Please grant Screen Recording permission to your terminal application: "
            "System Settings → Privacy & Security → Screen Recording."
        )
    if _is_all_white(screenshot):
        raise WindowCaptureError(
            "The Kindle window appears to be loading. "
            "Please wait until a book page is visible and try again."
        )
    if not _is_content_page(screenshot):
        logger.warning(
            "The Kindle window does not look like a standard reading page "
            "(it may be showing a cover or image page). Continuing anyway."
        )

    return window


def capture_window(
    window: KindleWindow,
    *,
    capture_fn: Callable[[KindleWindow], np.ndarray] = _default_capture,
) -> np.ndarray:
    """Capture a single frame of *window* as a BGR ndarray.

    Args:
        window: Previously validated KindleWindow.
        capture_fn: Injectable capture backend (default: Quartz).

    Returns:
        uint8 BGR ndarray.
    """
    return capture_fn(window)
