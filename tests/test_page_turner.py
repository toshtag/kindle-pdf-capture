"""Tests for the page-turner module (Quartz key-event injection).

Quartz CGEvent calls are always injected so tests run without Accessibility
permission on any platform.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kindle_pdf_capture.page_turner import (
    AccessibilityError,
    check_accessibility,
    focus_window,
    send_right_arrow,
)
from kindle_pdf_capture.window_capture import KindleWindow


def _kindle_win() -> KindleWindow:
    return KindleWindow(pid=1234, window_id=10, x=0, y=0, width=1200, height=900)


# ---------------------------------------------------------------------------
# check_accessibility
# ---------------------------------------------------------------------------


class TestCheckAccessibility:
    def test_raises_when_not_trusted(self) -> None:
        with pytest.raises(AccessibilityError, match="Accessibility"):
            check_accessibility(is_trusted_fn=lambda: False)

    def test_does_not_raise_when_trusted(self) -> None:
        check_accessibility(is_trusted_fn=lambda: True)  # no exception

    def test_calls_is_trusted_fn(self) -> None:
        called = []

        def mock_trusted() -> bool:
            called.append(True)
            return True

        check_accessibility(is_trusted_fn=mock_trusted)
        assert called


# ---------------------------------------------------------------------------
# focus_window
# ---------------------------------------------------------------------------


class TestFocusWindow:
    def test_calls_activate_fn_with_pid(self) -> None:
        calls = []

        def mock_activate(pid: int) -> None:
            calls.append(pid)

        win = _kindle_win()
        focus_window(win, activate_fn=mock_activate)
        assert calls == [win.pid]

    def test_accepts_callable(self) -> None:
        mock_fn = MagicMock()
        focus_window(_kindle_win(), activate_fn=mock_fn)
        mock_fn.assert_called_once()


# ---------------------------------------------------------------------------
# send_right_arrow
# ---------------------------------------------------------------------------


class TestSendRightArrow:
    def test_calls_event_fn_twice(self) -> None:
        """A key press is key-down + key-up — two events."""
        events = []

        def mock_event_fn(event_type: int, key_code: int) -> None:
            events.append((event_type, key_code))

        send_right_arrow(event_fn=mock_event_fn)
        assert len(events) == 2

    def test_first_event_is_key_down(self) -> None:
        events = []

        def mock_event_fn(event_type: int, key_code: int) -> None:
            events.append(event_type)

        send_right_arrow(event_fn=mock_event_fn)
        # event_type values come from Quartz constants; we just check ordering
        # key-down event type must differ from key-up
        assert events[0] != events[1]

    def test_key_code_is_right_arrow(self) -> None:
        """macOS right-arrow key code is 124."""
        key_codes = []

        def mock_event_fn(event_type: int, key_code: int) -> None:
            key_codes.append(key_code)

        send_right_arrow(event_fn=mock_event_fn)
        assert all(kc == 124 for kc in key_codes)

    def test_does_not_raise_with_mock(self) -> None:
        send_right_arrow(event_fn=lambda et, kc: None)
