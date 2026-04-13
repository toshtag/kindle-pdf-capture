"""Page-turn automation via Quartz Event Services.

Sends a right-arrow key event to the frontmost Kindle window.
All Quartz calls are abstracted behind injectable callables.

Requires macOS Accessibility permission (System Preferences →
Privacy & Security → Accessibility → grant Terminal / your app).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from kindle_pdf_capture.window_capture import KindleWindow

logger = logging.getLogger(__name__)

# macOS virtual key code for the right-arrow key
_KEY_RIGHT = 124


class AccessibilityError(PermissionError):
    """Raised when macOS Accessibility permission is not granted."""


# ---------------------------------------------------------------------------
# Default Quartz implementations
# ---------------------------------------------------------------------------


def _default_is_trusted() -> bool:
    """Return True when the process has Accessibility permission."""
    try:
        from Quartz import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def _default_activate(pid: int) -> None:
    """Bring the process with *pid* to the foreground via AppKit."""
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.amazon.Kindle")
        if not apps:
            # Fallback: find by pid
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if app:
                app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        else:
            apps[0].activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception as exc:
        logger.warning("Could not activate Kindle window: %s", exc)


def _default_event_fn(event_type: int, key_code: int) -> None:
    """Post a CGEvent keyboard event."""
    try:
        from Quartz import (
            CGEventCreateKeyboardEvent,
            CGEventPost,
            kCGEventKeyDown,
            kCGHIDEventTap,
        )

        is_down = event_type == kCGEventKeyDown
        event = CGEventCreateKeyboardEvent(None, key_code, is_down)
        CGEventPost(kCGHIDEventTap, event)
    except Exception as exc:
        logger.error("Failed to post key event: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_accessibility(*, is_trusted_fn: Callable[[], bool] = _default_is_trusted) -> None:
    """Verify that the process has macOS Accessibility permission.

    Args:
        is_trusted_fn: Injectable; returns True when permission is granted.

    Raises:
        AccessibilityError: With instructions to enable the permission.
    """
    if not is_trusted_fn():
        raise AccessibilityError(
            "Accessibility permission is required to send key events to Kindle.\n"
            "Go to System Settings → Privacy & Security → Accessibility\n"
            "and enable the checkbox for Terminal (or your application)."
        )


def focus_window(
    window: KindleWindow,
    *,
    activate_fn: Callable[[int], None] = _default_activate,
) -> None:
    """Bring *window* to the foreground so it receives key events.

    Args:
        window: The KindleWindow to focus.
        activate_fn: Injectable; receives the process PID.
    """
    logger.debug("Focusing Kindle window (pid=%d)", window.pid)
    activate_fn(window.pid)


def send_right_arrow(
    *,
    event_fn: Callable[[int, int], None] = _default_event_fn,
    inter_event_delay: float = 0.05,
) -> None:
    """Send a right-arrow key-down + key-up event pair.

    Args:
        event_fn: Injectable; receives (event_type_int, key_code).
            The integer values follow Quartz kCGEventKeyDown / kCGEventKeyUp.
        inter_event_delay: Seconds between key-down and key-up (default 50ms).
    """
    # Use literal integers that match Quartz constants to avoid importing
    # Quartz here (keeps the function testable without macOS libs).
    KEY_DOWN = 10  # kCGEventKeyDown
    KEY_UP = 11  # kCGEventKeyUp

    event_fn(KEY_DOWN, _KEY_RIGHT)
    if inter_event_delay > 0:
        time.sleep(inter_event_delay)
    event_fn(KEY_UP, _KEY_RIGHT)
    logger.debug("Sent right-arrow key event")
