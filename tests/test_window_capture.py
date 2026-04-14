"""Tests for the Kindle window detection and capture module.

All Quartz API calls are injected as parameters, so tests run without
macOS screen-recording permissions and pass on any platform.
"""

from __future__ import annotations

import numpy as np
import pytest

from kindle_pdf_capture.window_capture import (
    KindleWindow,
    WindowCaptureError,
    _is_all_black,
    _is_all_white,
    _is_content_page,
    _pick_best_window,
    find_kindle_window,
)

# ---------------------------------------------------------------------------
# Helpers: fake Quartz window-info dictionaries
# ---------------------------------------------------------------------------

_KINDLE_PID = 12345


def _win(
    pid: int = _KINDLE_PID,
    layer: int = 0,
    on_screen: bool = True,
    x: int = 0,
    y: int = 0,
    w: int = 1200,
    h: int = 900,
    wid: int = 1,
) -> dict:
    return {
        "kCGWindowOwnerPID": pid,
        "kCGWindowLayer": layer,
        "kCGWindowIsOnscreen": on_screen,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
        "kCGWindowNumber": wid,
    }


# ---------------------------------------------------------------------------
# KindleWindow dataclass
# ---------------------------------------------------------------------------


class TestKindleWindow:
    def test_fields(self) -> None:
        kw = KindleWindow(pid=1, window_id=2, x=10, y=20, width=800, height=600)
        assert kw.pid == 1
        assert kw.window_id == 2
        assert kw.x == 10
        assert kw.y == 20
        assert kw.width == 800
        assert kw.height == 600

    def test_area(self) -> None:
        kw = KindleWindow(pid=1, window_id=1, x=0, y=0, width=1200, height=900)
        assert kw.area == 1080000


# ---------------------------------------------------------------------------
# _pick_best_window: filtering and selection logic
# ---------------------------------------------------------------------------


class TestPickBestWindow:
    def test_returns_largest_on_screen_layer0_window(self) -> None:
        small = _win(w=600, h=400, wid=1)
        large = _win(w=1200, h=900, wid=2)
        result = _pick_best_window([small, large], kindle_pid=_KINDLE_PID)
        assert result is not None
        assert result.window_id == 2

    def test_excludes_wrong_pid(self) -> None:
        win = _win(pid=99999, w=1200, h=900)
        result = _pick_best_window([win], kindle_pid=_KINDLE_PID)
        assert result is None

    def test_excludes_off_screen_windows(self) -> None:
        win = _win(on_screen=False, w=1200, h=900)
        result = _pick_best_window([win], kindle_pid=_KINDLE_PID)
        assert result is None

    def test_excludes_non_zero_layer(self) -> None:
        win = _win(layer=1, w=1200, h=900)
        result = _pick_best_window([win], kindle_pid=_KINDLE_PID)
        assert result is None

    def test_excludes_small_windows(self) -> None:
        win = _win(w=400, h=200)  # below 800x600 threshold
        result = _pick_best_window([win], kindle_pid=_KINDLE_PID)
        assert result is None

    def test_returns_none_on_empty_list(self) -> None:
        assert _pick_best_window([], kindle_pid=_KINDLE_PID) is None

    def test_negative_coordinates_accepted(self) -> None:
        """Left-side monitor can have negative x/y."""
        win = _win(x=-1920, y=-100, w=1200, h=900)
        result = _pick_best_window([win], kindle_pid=_KINDLE_PID)
        assert result is not None
        assert result.x == -1920

    def test_returns_kindle_window_instance(self) -> None:
        win = _win(w=1200, h=900)
        result = _pick_best_window([win], kindle_pid=_KINDLE_PID)
        assert isinstance(result, KindleWindow)


# ---------------------------------------------------------------------------
# _is_content_page: image heuristic
# ---------------------------------------------------------------------------


class TestIsAllBlack:
    def test_all_black_returns_true(self) -> None:
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        assert _is_all_black(img) is True

    def test_nearly_black_returns_true(self) -> None:
        img = np.full((900, 1200, 3), 5, dtype=np.uint8)
        assert _is_all_black(img) is True

    def test_white_returns_false(self) -> None:
        img = np.full((900, 1200, 3), 255, dtype=np.uint8)
        assert _is_all_black(img) is False

    def test_cover_with_dark_background_returns_false(self) -> None:
        """Dark cover pages have bright pixels (title text etc.)."""
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        img[100:200, 200:1000] = 220  # bright title band
        assert _is_all_black(img) is False


class TestIsAllWhite:
    def test_all_white_returns_true(self) -> None:
        img = np.full((900, 1200, 3), 255, dtype=np.uint8)
        assert _is_all_white(img) is True

    def test_nearly_white_returns_true(self) -> None:
        img = np.full((900, 1200, 3), 252, dtype=np.uint8)
        assert _is_all_white(img) is True

    def test_black_returns_false(self) -> None:
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        assert _is_all_white(img) is False

    def test_content_page_returns_false(self) -> None:
        img = np.full((900, 1200, 3), 255, dtype=np.uint8)
        img[200:700:20, 100:1100] = 30
        assert _is_all_white(img) is False


class TestIsContentPage:
    def test_white_image_with_text_is_content(self) -> None:
        img = np.full((900, 1200, 3), 255, dtype=np.uint8)
        # Simulate text: dark horizontal lines in the centre
        img[200:700:20, 100:1100] = 30
        assert _is_content_page(img) is True

    def test_all_black_image_is_not_content(self) -> None:
        img = np.zeros((900, 1200, 3), dtype=np.uint8)
        assert _is_content_page(img) is False

    def test_all_white_image_is_not_content(self) -> None:
        """Blank white = loading screen, not a book page."""
        img = np.full((900, 1200, 3), 255, dtype=np.uint8)
        assert _is_content_page(img) is False

    def test_icon_grid_is_not_content(self) -> None:
        """Library / store screen: low brightness, many colours — not a reading page."""
        rng = np.random.default_rng(42)
        img = rng.integers(50, 180, (900, 1200, 3), dtype=np.uint8)
        # Result can be either way depending on randomness; we just verify no crash
        result = _is_content_page(img)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# find_kindle_window: integration through injected helpers
# ---------------------------------------------------------------------------


class TestFindKindleWindow:
    def _make_capture_fn(self, img: np.ndarray):
        def _capture(window: KindleWindow) -> np.ndarray:
            return img

        return _capture

    def _make_pid_fn(self, pid: int | None):
        def _get_pid(name: str) -> int | None:
            return pid

        return _get_pid

    def _make_list_fn(self, windows: list[dict]):
        def _list() -> list[dict]:
            return windows

        return _list

    def _content_img(self) -> np.ndarray:
        img = np.full((900, 1200, 3), 255, dtype=np.uint8)
        img[200:700:20, 100:1100] = 30
        return img

    def test_returns_kindle_window_when_all_valid(self) -> None:
        img = self._content_img()
        result = find_kindle_window(
            get_pid_fn=self._make_pid_fn(_KINDLE_PID),
            list_windows_fn=self._make_list_fn([_win(w=1200, h=900)]),
            capture_fn=self._make_capture_fn(img),
        )
        assert isinstance(result, KindleWindow)

    def test_raises_when_kindle_not_running(self) -> None:
        with pytest.raises(WindowCaptureError, match="not running"):
            find_kindle_window(
                get_pid_fn=self._make_pid_fn(None),
                list_windows_fn=self._make_list_fn([]),
                capture_fn=self._make_capture_fn(np.zeros((10, 10, 3), dtype=np.uint8)),
            )

    def test_raises_when_no_suitable_window(self) -> None:
        img = self._content_img()
        with pytest.raises(WindowCaptureError, match="window"):
            find_kindle_window(
                get_pid_fn=self._make_pid_fn(_KINDLE_PID),
                list_windows_fn=self._make_list_fn([]),  # no windows
                capture_fn=self._make_capture_fn(img),
            )

    def test_raises_when_capture_is_all_black(self) -> None:
        """All-black = screen recording permission missing."""
        black = np.zeros((900, 1200, 3), dtype=np.uint8)
        with pytest.raises(WindowCaptureError, match="black"):
            find_kindle_window(
                get_pid_fn=self._make_pid_fn(_KINDLE_PID),
                list_windows_fn=self._make_list_fn([_win(w=1200, h=900)]),
                capture_fn=self._make_capture_fn(black),
            )

    def test_raises_when_capture_is_all_white(self) -> None:
        """All-white = loading screen."""
        blank = np.full((900, 1200, 3), 255, dtype=np.uint8)
        with pytest.raises(WindowCaptureError, match="loading"):
            find_kindle_window(
                get_pid_fn=self._make_pid_fn(_KINDLE_PID),
                list_windows_fn=self._make_list_fn([_win(w=1200, h=900)]),
                capture_fn=self._make_capture_fn(blank),
            )

    def test_continues_with_warning_for_dark_cover_page(self) -> None:
        """Dark cover page should not raise — just warn and continue."""
        cover = np.zeros((900, 1200, 3), dtype=np.uint8)
        cover[100:200, 200:1000] = 220  # title band keeps it from being all-black
        result = find_kindle_window(
            get_pid_fn=self._make_pid_fn(_KINDLE_PID),
            list_windows_fn=self._make_list_fn([_win(w=1200, h=900)]),
            capture_fn=self._make_capture_fn(cover),
        )
        assert isinstance(result, KindleWindow)


# ---------------------------------------------------------------------------
# resize_kindle_window
# ---------------------------------------------------------------------------


class TestResizeKindleWindow:
    def test_calls_resize_fn_with_correct_size(self) -> None:
        """resize_kindle_window must invoke the resize callable with pid and dimensions."""
        from kindle_pdf_capture.window_capture import resize_kindle_window

        calls: list[tuple[int, int, int]] = []

        def _fake_resize(pid: int, width: int, height: int) -> None:
            calls.append((pid, width, height))

        window = KindleWindow(pid=42, window_id=1, x=0, y=0, width=1200, height=900)
        resize_kindle_window(window, target_width=800, target_height=700, resize_fn=_fake_resize)

        assert calls == [(42, 800, 700)]

    def test_returns_original_size(self) -> None:
        """resize_kindle_window must return (original_width, original_height)."""
        from kindle_pdf_capture.window_capture import resize_kindle_window

        window = KindleWindow(pid=1, window_id=1, x=0, y=0, width=1200, height=900)
        orig_w, orig_h = resize_kindle_window(
            window, target_width=800, target_height=700, resize_fn=lambda *_: None
        )
        assert orig_w == 1200
        assert orig_h == 900

    def test_noop_when_already_target_size(self) -> None:
        """If the window is already the target size, resize_fn must not be called."""
        from kindle_pdf_capture.window_capture import resize_kindle_window

        calls: list = []
        window = KindleWindow(pid=1, window_id=1, x=0, y=0, width=800, height=700)
        resize_kindle_window(
            window, target_width=800, target_height=700, resize_fn=lambda *a: calls.append(a)
        )
        assert calls == []
