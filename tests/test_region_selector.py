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

    def _init_selector(self, frame_w: int = 1200, frame_h: int = 900):
        """Create a RegionSelector via __new__ with all required attributes set.

        Uses scale=1.0 (no downscaling) and _img_y0=_INSTR_BAR_H so that
        display coords equal frame coords minus the instruction bar offset.
        """
        from unittest.mock import MagicMock

        from kindle_pdf_capture.region_selector import _INSTR_BAR_H, RegionSelector

        selector = RegionSelector.__new__(RegionSelector)
        selector._result = None
        selector._cancelled = False
        selector._x0 = selector._y0 = selector._x1 = selector._y1 = 0
        selector._rect_id = None
        selector._mask_ids = []
        selector._frame_w = frame_w
        selector._frame_h = frame_h
        # scale=1.0: display pixels == frame pixels
        selector._scale = 1.0
        selector._disp_w = frame_w
        selector._disp_h = frame_h
        selector._img_y0 = _INSTR_BAR_H
        selector._canvas = MagicMock()
        return selector

    def test_select_region_returns_content_region(self, monkeypatch):
        """Simulating a complete drag must return a ContentRegion."""
        from unittest.mock import MagicMock

        from kindle_pdf_capture.cropper import ContentRegion
        from kindle_pdf_capture.region_selector import _INSTR_BAR_H

        frame = self._make_frame()
        selector = self._init_selector(frame.shape[1], frame.shape[0])

        # Simulate mouse-press at display (100, _INSTR_BAR_H + 150)
        press_event = MagicMock()
        press_event.x = 100
        press_event.y = _INSTR_BAR_H + 150
        selector._on_press(press_event)

        # Simulate mouse-drag to display (400, _INSTR_BAR_H + 500)
        drag_event = MagicMock()
        drag_event.x = 400
        drag_event.y = _INSTR_BAR_H + 500
        selector._on_drag(drag_event)

        # Simulate Enter key to confirm
        selector._on_confirm(MagicMock())

        result = selector._result
        assert result is not None
        assert isinstance(result, ContentRegion)
        assert result.x == 100
        assert result.y == 150  # display y minus _INSTR_BAR_H, scale=1 → frame y
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
        """_on_drag must update x1/y1 within display bounds."""
        from kindle_pdf_capture.region_selector import _INSTR_BAR_H

        selector = self._init_selector(1200, 900)
        selector._x0 = 100
        selector._y0 = _INSTR_BAR_H + 100

        event = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        event.x = 500
        event.y = _INSTR_BAR_H + 600
        selector._on_drag(event)

        assert selector._x1 == 500
        assert selector._y1 == _INSTR_BAR_H + 600

    def test_drag_clamped_to_frame_bounds(self):
        """_on_drag must clamp coordinates to display dimensions."""
        from kindle_pdf_capture.region_selector import _INSTR_BAR_H

        selector = self._init_selector(1200, 900)

        event = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        event.x = 2000
        event.y = 9999
        selector._on_drag(event)

        # x clamped to disp_w=1200; y clamped to img_y0+disp_h
        assert selector._x1 == 1200
        assert selector._y1 == _INSTR_BAR_H + 900

    def test_confirm_without_drag_raises(self):
        """Confirming without drawing a rectangle must flag as cancelled."""
        from unittest.mock import MagicMock

        selector = self._init_selector(1200, 900)
        # x0==x1 and y0==y1 → zero-size rect
        selector._x0 = selector._x1 = 50
        selector._y0 = selector._y1 = 50

        selector._on_confirm(MagicMock())

        assert selector._cancelled is True
        assert selector._result is None
