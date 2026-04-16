"""Tests for the manual crop region selector.

The tkinter UI cannot run in a headless test environment, so all tests
exercise the pure-logic helpers (coordinate clamping, rect normalisation,
ContentRegion conversion) in isolation.  The RegionSelector class itself
is integration-tested via a mock Tk root so no display is required.
"""

from __future__ import annotations

import numpy as np
import pytest
from kindle_pdf_capture.region_selector import (
    RegionSelectorCancelled,
    _clamp,
    _normalise_rect,
    _rect_to_content_region,
)

# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------


class TestClamp:
    def test_value_within_bounds(self):
        assert _clamp(50, 0, 100) == 50

    def test_value_below_min(self):
        assert _clamp(-5, 0, 100) == 0

    def test_value_above_max(self):
        assert _clamp(150, 0, 100) == 100

    def test_value_at_min(self):
        assert _clamp(0, 0, 100) == 0

    def test_value_at_max(self):
        assert _clamp(100, 0, 100) == 100


# ---------------------------------------------------------------------------
# _normalise_rect — ensure (x1,y1) is always top-left
# ---------------------------------------------------------------------------


class TestNormaliseRect:
    def test_already_normalised(self):
        assert _normalise_rect(10, 20, 110, 220) == (10, 20, 110, 220)

    def test_drag_right_to_left(self):
        """Dragging from right to left must swap x coordinates."""
        assert _normalise_rect(110, 20, 10, 220) == (10, 20, 110, 220)

    def test_drag_bottom_to_top(self):
        """Dragging from bottom to top must swap y coordinates."""
        assert _normalise_rect(10, 220, 110, 20) == (10, 20, 110, 220)

    def test_drag_diagonal_bottom_right_to_top_left(self):
        assert _normalise_rect(110, 220, 10, 20) == (10, 20, 110, 220)

    def test_zero_size_rect(self):
        assert _normalise_rect(50, 50, 50, 50) == (50, 50, 50, 50)


# ---------------------------------------------------------------------------
# _rect_to_content_region — pixel-space rect → ContentRegion
# ---------------------------------------------------------------------------


class TestRectToContentRegion:
    def test_basic_conversion(self):
        from kindle_pdf_capture.cropper import ContentRegion

        region = _rect_to_content_region(10, 20, 110, 220)
        assert isinstance(region, ContentRegion)
        assert region.x == 10
        assert region.y == 20
        assert region.w == 100  # 110 - 10
        assert region.h == 200  # 220 - 20

    def test_full_frame_conversion(self):

        region = _rect_to_content_region(0, 0, 1200, 900)
        assert region.x == 0
        assert region.y == 0
        assert region.w == 1200
        assert region.h == 900

    def test_minimum_size_rect(self):
        """A 1x1 rect must produce w=1, h=1 (not zero)."""
        region = _rect_to_content_region(50, 50, 51, 51)
        assert region.w == 1
        assert region.h == 1


# ---------------------------------------------------------------------------
# RegionSelectorCancelled exception
# ---------------------------------------------------------------------------


class TestRegionSelectorCancelled:
    def test_is_exception(self):
        with pytest.raises(RegionSelectorCancelled):
            raise RegionSelectorCancelled("user cancelled")

    def test_inherits_from_runtime_error(self):
        assert issubclass(RegionSelectorCancelled, RuntimeError)


# ---------------------------------------------------------------------------
# RegionSelector (mock Tk) — select_region logic
# ---------------------------------------------------------------------------


class TestRegionSelectorLogic:
    """Tests for RegionSelector using a mock Tk root.

    We bypass the actual Tk event loop by calling the internal event
    handler methods directly, so no display server is needed.
    """

    def _make_frame(self, w: int = 1200, h: int = 900) -> np.ndarray:
        frame = np.full((h, w, 3), 200, dtype=np.uint8)
        frame[100:200, 100:300] = 50
        return frame

    def test_select_region_returns_content_region(self, monkeypatch):
        """Simulating a complete drag must return a ContentRegion."""
        from unittest.mock import MagicMock, patch

        from kindle_pdf_capture.region_selector import RegionSelector

        from kindle_pdf_capture.cropper import ContentRegion

        frame = self._make_frame()

        with patch("kindle_pdf_capture.region_selector.tk") as mock_tk:
            # Set up mock Tk root and canvas
            mock_root = MagicMock()
            mock_canvas = MagicMock()
            mock_tk.Tk.return_value = mock_root
            mock_tk.Canvas.return_value = mock_canvas

            # Prevent actual mainloop from blocking
            selector = RegionSelector.__new__(RegionSelector)
            selector._result = None
            selector._cancelled = False
            selector._x0 = selector._y0 = selector._x1 = selector._y1 = 0
            selector._rect_id = None
            selector._frame_w = frame.shape[1]
            selector._frame_h = frame.shape[0]

            # Simulate mouse-press at (100, 150)
            press_event = MagicMock()
            press_event.x = 100
            press_event.y = 150
            selector._on_press(press_event)

            # Simulate mouse-drag to (400, 500)
            drag_event = MagicMock()
            drag_event.x = 400
            drag_event.y = 500
            selector._canvas = mock_canvas
            selector._on_drag(drag_event)

            # Simulate Enter key to confirm
            selector._on_confirm(MagicMock())

            result = selector._result
            assert result is not None
            assert isinstance(result, ContentRegion)
            assert result.x == 100
            assert result.y == 150
            assert result.w == 300  # 400 - 100
            assert result.h == 350  # 500 - 150

    def test_escape_sets_cancelled(self, monkeypatch):
        """Pressing Escape must set _cancelled=True."""
        from unittest.mock import MagicMock

        from kindle_pdf_capture.region_selector import RegionSelector

        selector = RegionSelector.__new__(RegionSelector)
        selector._cancelled = False
        selector._result = None

        selector._on_cancel(MagicMock())

        assert selector._cancelled is True
        assert selector._result is None

    def test_drag_updates_coordinates(self):
        """_on_drag must update x1/y1 and clamp to frame bounds."""
        from unittest.mock import MagicMock

        from kindle_pdf_capture.region_selector import RegionSelector

        selector = RegionSelector.__new__(RegionSelector)
        selector._x0 = 100
        selector._y0 = 100
        selector._x1 = 100
        selector._y1 = 100
        selector._frame_w = 1200
        selector._frame_h = 900
        selector._rect_id = None
        selector._canvas = MagicMock()

        # Drag within bounds
        event = MagicMock()
        event.x = 500
        event.y = 600
        selector._on_drag(event)

        assert selector._x1 == 500
        assert selector._y1 == 600

    def test_drag_clamped_to_frame_bounds(self):
        """_on_drag must clamp coordinates to frame dimensions."""
        from unittest.mock import MagicMock

        from kindle_pdf_capture.region_selector import RegionSelector

        selector = RegionSelector.__new__(RegionSelector)
        selector._x0 = 0
        selector._y0 = 0
        selector._x1 = 0
        selector._y1 = 0
        selector._frame_w = 1200
        selector._frame_h = 900
        selector._rect_id = None
        selector._canvas = MagicMock()

        # Drag beyond frame bounds
        event = MagicMock()
        event.x = 2000
        event.y = 1500
        selector._on_drag(event)

        assert selector._x1 == 1200
        assert selector._y1 == 900

    def test_confirm_without_drag_raises(self):
        """Confirming without drawing a rectangle must raise RegionSelectorCancelled."""
        from unittest.mock import MagicMock

        from kindle_pdf_capture.region_selector import RegionSelector

        selector = RegionSelector.__new__(RegionSelector)
        selector._x0 = 50
        selector._y0 = 50
        selector._x1 = 50  # same as x0 → zero-width
        selector._y1 = 50  # same as y0 → zero-height
        selector._cancelled = False
        selector._result = None

        selector._on_confirm(MagicMock())

        # Should flag as cancelled instead of setting result
        assert selector._cancelled is True
        assert selector._result is None
