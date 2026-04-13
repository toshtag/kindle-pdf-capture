"""Tests for the render-completion detection module."""

from __future__ import annotations

import time

import numpy as np
import pytest

from kindle_pdf_capture.render_wait import (
    WaitResult,
    WaitStatus,
    compute_diff_ratio,
    wait_for_render,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frame(fill: int, width: int = 400, height: int = 300) -> np.ndarray:
    return np.full((height, width, 3), fill, dtype=np.uint8)


def _make_capture_fn(frames: list[np.ndarray]):
    """Return a function that pops frames sequentially."""
    it = iter(frames)

    def capture() -> np.ndarray:
        try:
            return next(it)
        except StopIteration:
            return frames[-1]

    return capture


# ---------------------------------------------------------------------------
# compute_diff_ratio
# ---------------------------------------------------------------------------


class TestComputeDiffRatio:
    def test_identical_frames_return_zero(self) -> None:
        a = _frame(128)
        assert compute_diff_ratio(a, a) == pytest.approx(0.0)

    def test_completely_different_frames_return_one(self) -> None:
        a = _frame(0)
        b = _frame(255)
        ratio = compute_diff_ratio(a, b)
        assert ratio == pytest.approx(1.0, abs=0.01)

    def test_partial_change(self) -> None:
        a = _frame(0, 100, 100)
        b = a.copy()
        b[:, 50:] = 255  # right half changed
        ratio = compute_diff_ratio(a, b)
        assert 0.4 < ratio < 0.6

    def test_returns_float(self) -> None:
        a = _frame(100)
        b = _frame(200)
        assert isinstance(compute_diff_ratio(a, b), float)

    def test_different_regions_sampled(self) -> None:
        """The function should sample a region, not the full frame."""
        a = np.zeros((600, 800, 3), dtype=np.uint8)
        b = np.zeros((600, 800, 3), dtype=np.uint8)
        # Change only the very corner — if region is central, this is ignored
        b[0:10, 0:10] = 255
        ratio = compute_diff_ratio(a, b)
        assert ratio < 0.1


# ---------------------------------------------------------------------------
# wait_for_render: WaitStatus / WaitResult
# ---------------------------------------------------------------------------


class TestWaitResult:
    def test_fields(self) -> None:
        r = WaitResult(status=WaitStatus.CONVERGED, elapsed=0.5, iterations=3)
        assert r.status == WaitStatus.CONVERGED
        assert r.elapsed == pytest.approx(0.5)
        assert r.iterations == 3

    def test_converged_property(self) -> None:
        ok = WaitResult(status=WaitStatus.CONVERGED, elapsed=0.1, iterations=1)
        to = WaitResult(status=WaitStatus.TIMEOUT, elapsed=5.0, iterations=10)
        assert ok.converged is True
        assert to.converged is False


# ---------------------------------------------------------------------------
# wait_for_render: happy paths
# ---------------------------------------------------------------------------


class TestWaitForRender:
    def test_returns_converged_when_frames_stabilise(self) -> None:
        """Sequence: changing frame, then two identical frames -> converged."""
        stable = _frame(200)
        frames = [_frame(100), stable, stable]
        result = wait_for_render(
            capture_fn=_make_capture_fn(frames),
            threshold=0.02,
            timeout=5.0,
            poll_interval=0.0,
            stable_count=2,
        )
        assert result.status == WaitStatus.CONVERGED

    def test_returns_timeout_when_always_changing(self) -> None:
        """Frames keep changing -> timeout."""
        i = 0

        def ever_changing() -> np.ndarray:
            nonlocal i
            i += 1
            return _frame(i % 255)

        result = wait_for_render(
            capture_fn=ever_changing,
            threshold=0.001,
            timeout=0.3,
            poll_interval=0.0,
            stable_count=2,
        )
        assert result.status == WaitStatus.TIMEOUT

    def test_elapsed_time_is_recorded(self) -> None:
        stable = _frame(200)
        frames = [stable, stable]
        t0 = time.monotonic()
        result = wait_for_render(
            capture_fn=_make_capture_fn(frames),
            threshold=0.5,
            timeout=5.0,
            poll_interval=0.0,
            stable_count=2,
        )
        assert result.elapsed >= 0.0
        assert result.elapsed <= time.monotonic() - t0 + 0.1

    def test_iteration_count_increments(self) -> None:
        stable = _frame(200)
        frames = [_frame(10), _frame(20), stable, stable]
        result = wait_for_render(
            capture_fn=_make_capture_fn(frames),
            threshold=0.02,
            timeout=5.0,
            poll_interval=0.0,
            stable_count=2,
        )
        assert result.iterations >= 2

    def test_high_threshold_converges_immediately(self) -> None:
        """With threshold=1.0 any two frames are 'stable'."""
        frames = [_frame(0), _frame(255)]
        result = wait_for_render(
            capture_fn=_make_capture_fn(frames),
            threshold=1.0,
            timeout=5.0,
            poll_interval=0.0,
            stable_count=2,
        )
        assert result.status == WaitStatus.CONVERGED

    def test_accepts_callable_capture_fn(self) -> None:
        """capture_fn can be any callable returning a BGR ndarray."""
        call_count = 0
        frame = _frame(128)

        def my_capture() -> np.ndarray:
            nonlocal call_count
            call_count += 1
            return frame

        wait_for_render(
            capture_fn=my_capture,
            threshold=0.5,
            timeout=0.1,
            poll_interval=0.0,
            stable_count=2,
        )
        assert call_count >= 1
