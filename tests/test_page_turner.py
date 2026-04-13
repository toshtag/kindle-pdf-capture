"""Tests for the page-turner module.

All Quartz and osascript calls are injected or mocked so tests run without
Accessibility permission on any platform.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kindle_pdf_capture.page_turner import (
    KEY_LEFT,
    KEY_RIGHT,
    AccessibilityError,
    _default_is_trusted,
    check_accessibility,
    focus_window,
    send_page_turn_key,
)
from kindle_pdf_capture.window_capture import KindleWindow


def _kindle_win() -> KindleWindow:
    return KindleWindow(pid=1234, window_id=10, x=0, y=0, width=1200, height=900)


# ---------------------------------------------------------------------------
# Key code constants
# ---------------------------------------------------------------------------


class TestKeyCodeConstants:
    def test_key_left_is_123(self) -> None:
        assert KEY_LEFT == 123

    def test_key_right_is_124(self) -> None:
        assert KEY_RIGHT == 124


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
# send_page_turn_key
# ---------------------------------------------------------------------------


class TestSendPageTurnKey:
    def test_calls_send_fn_with_key_code_and_pid(self) -> None:
        calls: list[tuple[int, int]] = []
        send_page_turn_key(1234, KEY_LEFT, send_fn=lambda kc, pid: calls.append((kc, pid)))
        assert calls == [(KEY_LEFT, 1234)]

    def test_left_key_code_passed_through(self) -> None:
        received: list[int] = []
        send_page_turn_key(1234, KEY_LEFT, send_fn=lambda kc, pid: received.append(kc))
        assert received == [KEY_LEFT]

    def test_right_key_code_passed_through(self) -> None:
        received: list[int] = []
        send_page_turn_key(1234, KEY_RIGHT, send_fn=lambda kc, pid: received.append(kc))
        assert received == [KEY_RIGHT]

    def test_pid_passed_through(self) -> None:
        pids: list[int] = []
        send_page_turn_key(9999, KEY_LEFT, send_fn=lambda kc, pid: pids.append(pid))
        assert pids == [9999]

    def test_does_not_raise_with_mock(self) -> None:
        send_page_turn_key(1234, KEY_LEFT, send_fn=lambda kc, pid: None)


# ---------------------------------------------------------------------------
# _default_send_key — uses CGEventPostToPid (Quartz), injectable for tests
# ---------------------------------------------------------------------------


class TestDefaultSendKey:
    def test_posts_key_down_and_up_to_pid(self) -> None:
        """CGEventPostToPid must be called twice (key-down then key-up)."""
        from kindle_pdf_capture.page_turner import _default_send_key

        mock_event = MagicMock()
        with (
            patch(
                "kindle_pdf_capture.page_turner.CGEventCreateKeyboardEvent", return_value=mock_event
            ),
            patch("kindle_pdf_capture.page_turner.CGEventPostToPid") as mock_post,
        ):
            _default_send_key(KEY_LEFT, 1234)

        assert mock_post.call_count == 2
        pids = [c.args[0] for c in mock_post.call_args_list]
        assert pids == [1234, 1234]

    def test_sends_correct_key_code(self) -> None:
        from kindle_pdf_capture.page_turner import _default_send_key

        with (
            patch("kindle_pdf_capture.page_turner.CGEventCreateKeyboardEvent") as mock_create,
            patch("kindle_pdf_capture.page_turner.CGEventPostToPid"),
        ):
            _default_send_key(KEY_LEFT, 1234)

        key_codes = [c.args[1] for c in mock_create.call_args_list]
        assert all(kc == KEY_LEFT for kc in key_codes)

    def test_first_event_is_key_down(self) -> None:
        from kindle_pdf_capture.page_turner import _default_send_key

        with (
            patch("kindle_pdf_capture.page_turner.CGEventCreateKeyboardEvent") as mock_create,
            patch("kindle_pdf_capture.page_turner.CGEventPostToPid"),
        ):
            _default_send_key(KEY_LEFT, 1234)

        # First call: key_down=True; second call: key_down=False
        assert mock_create.call_args_list[0].args[2] is True
        assert mock_create.call_args_list[1].args[2] is False

    def test_does_not_raise_on_quartz_failure(self) -> None:
        from kindle_pdf_capture.page_turner import _default_send_key

        with patch(
            "kindle_pdf_capture.page_turner.CGEventCreateKeyboardEvent",
            side_effect=Exception("no quartz"),
        ):
            _default_send_key(KEY_LEFT, 1234)  # must not raise


# ---------------------------------------------------------------------------
# _default_is_trusted (osascript-based)
# ---------------------------------------------------------------------------


class TestDefaultIsTrusted:
    def test_returns_true_when_osascript_succeeds(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            assert _default_is_trusted() is True

    def test_returns_false_when_osascript_fails(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            assert _default_is_trusted() is False

    def test_returns_false_on_exception(self) -> None:
        with patch("subprocess.run", side_effect=OSError):
            assert _default_is_trusted() is False
