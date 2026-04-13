"""Page-turn automation via Quartz CGEventPostToPid.

Sends a key event directly to the Kindle process by PID using
CGEventPostToPid, which works regardless of which application currently
has keyboard focus.  No window activation is needed before each key press.

Requires macOS Accessibility permission granted to Terminal (or whichever
application runs kpc).
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable

from kindle_pdf_capture.window_capture import KindleWindow

logger = logging.getLogger(__name__)

# macOS virtual key codes
KEY_LEFT: int = 123   # left-arrow  — next page in RTL (e.g. Japanese) books
KEY_RIGHT: int = 124  # right-arrow — next page in LTR (e.g. English) books


class AccessibilityError(PermissionError):
    """Raised when macOS Accessibility permission is not granted."""


# ---------------------------------------------------------------------------
# Accessibility probe (osascript)
# ---------------------------------------------------------------------------

_APPLESCRIPT_PROBE = 'tell application "System Events" to get name of first process'


def _default_is_trusted() -> bool:
    """Return True when the process has Accessibility permission.

    Uses a lightweight osascript probe so the check targets the terminal
    application rather than the Python interpreter binary.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT_PROBE],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Window activation (used for initial focus only, not per-keypress)
# ---------------------------------------------------------------------------


def _default_activate(pid: int) -> None:
    """Bring the process with *pid* to the foreground via AppKit."""
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.amazon.Kindle")
        if not apps:
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if app:
                app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        else:
            apps[0].activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception as exc:
        logger.warning("Could not activate Kindle window: %s", exc)


# ---------------------------------------------------------------------------
# Key-event delivery via CGEventPostToPid
# ---------------------------------------------------------------------------

# Import at module scope so tests can patch them without entering the function.
try:
    from Quartz import CGEventCreateKeyboardEvent, CGEventPostToPid
except Exception:  # pragma: no cover — unavailable outside macOS
    CGEventCreateKeyboardEvent = None  # type: ignore[assignment]
    CGEventPostToPid = None  # type: ignore[assignment]


def _default_send_key(key_code: int, pid: int) -> None:
    """Post a key-down + key-up event to *pid* via CGEventPostToPid.

    CGEventPostToPid delivers events directly to the target process without
    requiring it to be in the foreground.  This is the only reliable method
    for background key delivery on macOS.
    """
    try:
        ev_down = CGEventCreateKeyboardEvent(None, key_code, True)
        CGEventPostToPid(pid, ev_down)
        time.sleep(0.05)
        ev_up = CGEventCreateKeyboardEvent(None, key_code, False)
        CGEventPostToPid(pid, ev_up)
        logger.debug("Sent key code %d to pid %d", key_code, pid)
    except Exception as exc:
        logger.error("CGEventPostToPid failed (key=%d pid=%d): %s", key_code, pid, exc)


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
    """Bring *window* to the foreground (used once at startup).

    Args:
        window: The KindleWindow to focus.
        activate_fn: Injectable; receives the process PID.
    """
    logger.debug("Focusing Kindle window (pid=%d)", window.pid)
    activate_fn(window.pid)


def send_page_turn_key(
    pid: int,
    key_code: int,
    *,
    send_fn: Callable[[int, int], None] = _default_send_key,
) -> None:
    """Send a page-turn key event to the Kindle process.

    Uses CGEventPostToPid by default, which works even when Kindle is in the
    background.  No window focus change is needed.

    Args:
        pid: PID of the Kindle process.
        key_code: Key to send — use KEY_LEFT (123) for RTL books or
            KEY_RIGHT (124) for LTR books.
        send_fn: Injectable; receives (key_code, pid).  Replace in tests to
            avoid real Quartz calls.
    """
    send_fn(key_code, pid)
