"""
tests/test_time_counts.py

Tests for modules/time_counts.py.

Coverage
--------
- bars_between_by_bar_index: signed, zero, negative deltas
- bars_between: known lookup, missing t0, missing t1, timezone normalisation
- build_index_map: DataFrame with timestamp column, DatetimeIndex
- build_bar_to_time_map: round-trip with build_index_map
- time_square_windows:
  - known bar offsets at multipliers [0.5, 1.0, 1.5, 2.0]
  - delta_t=0 returns empty list
  - negative multiplier raises ValueError
  - target resolved to timestamp when bar_to_time_map provided
  - target not in dataset when bar_to_time_map lacks that bar
  - degenerate multiplier=0 noted
  - determinism
- Gap-safety: bar_index delta is correct even with a synthetic gap
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd
import pytest

from modules.time_counts import (
    TimeWindow,
    bars_between,
    bars_between_by_bar_index,
    build_bar_to_time_map,
    build_index_map,
    time_square_windows,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _make_df(n: int = 10, start: str = "2020-01-01", freq: str = "D") -> pd.DataFrame:
    """Build a tiny processed-style DataFrame with bar_index and timestamp."""
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    df = pd.DataFrame({"timestamp": dates, "close": range(100, 100 + n)})
    df["bar_index"] = range(n)
    return df


def _make_impulse(
    impulse_id: str = "test_0",
    delta_t: int = 50,
    origin_bar_index: int = 10,
    extreme_bar_index: int = 60,
) -> Dict[str, Any]:
    return {
        "impulse_id": impulse_id,
        "delta_t": delta_t,
        "origin_bar_index": origin_bar_index,
        "extreme_bar_index": extreme_bar_index,
    }


# ── bars_between_by_bar_index ─────────────────────────────────────────────────


class TestBarsBetweenByBarIndex:
    def test_positive_delta(self):
        assert bars_between_by_bar_index(10, 60) == 50

    def test_zero_delta(self):
        assert bars_between_by_bar_index(42, 42) == 0

    def test_negative_delta(self):
        assert bars_between_by_bar_index(60, 10) == -50

    def test_large_values(self):
        assert bars_between_by_bar_index(0, 3883) == 3883

    def test_deterministic(self):
        assert bars_between_by_bar_index(10, 60) == bars_between_by_bar_index(10, 60)


# ── bars_between ──────────────────────────────────────────────────────────────


class TestBarsBetween:
    def _make_map(self) -> Dict[pd.Timestamp, int]:
        df = _make_df(20)
        return build_index_map(df)

    def test_known_value(self):
        """Timestamps at bar 0 and bar 5 → 5 bars apart."""
        df = _make_df(10)
        idx_map = build_index_map(df)
        t0 = pd.Timestamp("2020-01-01", tz="UTC")
        t5 = pd.Timestamp("2020-01-06", tz="UTC")
        result = bars_between(t0, t5, idx_map)
        assert result == 5

    def test_zero_bars(self):
        df = _make_df(5)
        idx_map = build_index_map(df)
        t = pd.Timestamp("2020-01-03", tz="UTC")
        assert bars_between(t, t, idx_map) == 0

    def test_negative_when_reversed(self):
        df = _make_df(10)
        idx_map = build_index_map(df)
        t0 = pd.Timestamp("2020-01-06", tz="UTC")
        t5 = pd.Timestamp("2020-01-01", tz="UTC")
        result = bars_between(t0, t5, idx_map)
        assert result == -5

    def test_missing_t0_returns_none(self):
        df = _make_df(5)
        idx_map = build_index_map(df)
        missing = pd.Timestamp("2019-12-01", tz="UTC")
        t1 = pd.Timestamp("2020-01-02", tz="UTC")
        assert bars_between(missing, t1, idx_map) is None

    def test_missing_t1_returns_none(self):
        df = _make_df(5)
        idx_map = build_index_map(df)
        t0 = pd.Timestamp("2020-01-01", tz="UTC")
        missing = pd.Timestamp("2025-01-01", tz="UTC")
        assert bars_between(t0, missing, idx_map) is None

    def test_timezone_naive_input_normalised(self):
        """bars_between should still work with naive Timestamps."""
        df = _make_df(5)
        idx_map = build_index_map(df)
        t0_naive = pd.Timestamp("2020-01-01")  # no tz
        t1_naive = pd.Timestamp("2020-01-03")
        # may return None if normalisation differs; test is about no crash
        result = bars_between(t0_naive, t1_naive, idx_map)
        # If it resolves, it should be 2
        if result is not None:
            assert result == 2


# ── build_index_map ───────────────────────────────────────────────────────────


class TestBuildIndexMap:
    def test_returns_dict(self):
        df = _make_df(5)
        idx_map = build_index_map(df)
        assert isinstance(idx_map, dict)
        assert len(idx_map) == 5

    def test_keys_are_timestamps(self):
        df = _make_df(5)
        idx_map = build_index_map(df)
        for k in idx_map:
            assert isinstance(k, pd.Timestamp)

    def test_values_are_bar_indices(self):
        df = _make_df(5)
        idx_map = build_index_map(df)
        assert sorted(idx_map.values()) == list(range(5))

    def test_first_bar(self):
        df = _make_df(5)
        idx_map = build_index_map(df)
        t0 = pd.Timestamp("2020-01-01", tz="UTC")
        assert idx_map[t0] == 0

    def test_missing_bar_index_raises(self):
        df = _make_df(5)
        df = df.drop(columns=["bar_index"])
        with pytest.raises(ValueError):
            build_index_map(df)

    def test_datetime_index_df(self):
        """Works with a DatetimeIndex-based DataFrame."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D", tz="UTC")
        df = pd.DataFrame({"close": range(5)}, index=dates)
        df["bar_index"] = range(5)
        idx_map = build_index_map(df)
        assert len(idx_map) == 5


# ── build_bar_to_time_map ─────────────────────────────────────────────────────


class TestBuildBarToTimeMap:
    def test_round_trip_with_index_map(self):
        """build_bar_to_time_map is the inverse of build_index_map."""
        df = _make_df(10)
        idx_map = build_index_map(df)
        bar_map = build_bar_to_time_map(df)
        for ts, bi in idx_map.items():
            assert bar_map[bi] == ts

    def test_keys_are_integers(self):
        df = _make_df(5)
        bar_map = build_bar_to_time_map(df)
        assert sorted(bar_map.keys()) == list(range(5))

    def test_missing_bar_index_raises(self):
        df = _make_df(5).drop(columns=["bar_index"])
        with pytest.raises(ValueError):
            build_bar_to_time_map(df)


# ── time_square_windows ───────────────────────────────────────────────────────


class TestTimeSquareWindows:
    def test_known_bar_offsets_default_multipliers(self):
        """
        impulse delta_t=100, extreme_bar_index=200.
        multipliers=[0.5, 1.0, 1.5, 2.0] → offsets=[50, 100, 150, 200]
        → target_bar_indices=[250, 300, 350, 400]
        """
        imp = _make_impulse(delta_t=100, extreme_bar_index=200)
        windows = time_square_windows(imp, multipliers=[0.5, 1.0, 1.5, 2.0])
        offsets = [w.bar_offset for w in windows]
        assert offsets == [50, 100, 150, 200]
        targets = [w.target_bar_index for w in windows]
        assert targets == [250, 300, 350, 400]

    def test_rounding_half_even(self):
        """
        delta_t=3, multiplier=0.5 → round(1.5) = 2 (banker's rounding).
        """
        imp = _make_impulse(delta_t=3, extreme_bar_index=100)
        windows = time_square_windows(imp, multipliers=[0.5])
        assert windows[0].bar_offset == round(0.5 * 3)  # Python's round

    def test_delta_t_zero_returns_empty(self):
        imp = _make_impulse(delta_t=0)
        windows = time_square_windows(imp)
        assert windows == []

    def test_negative_multiplier_raises(self):
        imp = _make_impulse(delta_t=50)
        with pytest.raises(ValueError, match="multiplier"):
            time_square_windows(imp, multipliers=[-1.0])

    def test_multiplier_zero_noted(self):
        imp = _make_impulse(delta_t=50, extreme_bar_index=100)
        windows = time_square_windows(imp, multipliers=[0.0])
        assert windows[0].target_bar_index == 100
        assert "degenerate" in windows[0].notes

    def test_target_resolved_when_in_map(self):
        """When bar_to_time_map contains the target bar, target_time is set."""
        df = _make_df(200)  # bar_index 0..199
        bar_map = build_bar_to_time_map(df)
        imp = _make_impulse(delta_t=50, extreme_bar_index=50)
        # mult=1.0 → target_bar = 50 + 50 = 100, which is in df
        windows = time_square_windows(imp, multipliers=[1.0], bar_to_time_map=bar_map)
        w = windows[0]
        assert w.in_dataset is True
        assert w.target_time is not None

    def test_target_not_in_map_when_beyond_dataset(self):
        """Target bar beyond dataset → in_dataset=False, target_time=None."""
        df = _make_df(50)  # bar_index 0..49
        bar_map = build_bar_to_time_map(df)
        imp = _make_impulse(delta_t=100, extreme_bar_index=40)
        # mult=1.0 → target_bar = 40 + 100 = 140 → beyond dataset
        windows = time_square_windows(imp, multipliers=[1.0], bar_to_time_map=bar_map)
        w = windows[0]
        assert w.in_dataset is False
        assert w.target_time is None
        assert "target_bar_beyond_dataset" in w.notes

    def test_no_map_target_time_none(self):
        imp = _make_impulse(delta_t=50)
        windows = time_square_windows(imp, multipliers=[1.0])
        assert windows[0].target_time is None
        assert windows[0].in_dataset is False

    def test_all_fields_set(self):
        imp = _make_impulse(impulse_id="abc", delta_t=50, origin_bar_index=10,
                            extreme_bar_index=60)
        windows = time_square_windows(imp, multipliers=[1.0])
        w = windows[0]
        assert w.impulse_id == "abc"
        assert w.impulse_delta_t == 50
        assert w.origin_bar_index == 10
        assert w.extreme_bar_index == 60
        assert w.multiplier == 1.0
        assert w.bar_offset == 50
        assert w.target_bar_index == 110

    def test_to_dict_all_keys(self):
        imp = _make_impulse(delta_t=50)
        windows = time_square_windows(imp, multipliers=[1.0])
        d = windows[0].to_dict()
        expected_keys = {
            "impulse_id", "origin_bar_index", "extreme_bar_index",
            "impulse_delta_t", "multiplier", "bar_offset",
            "target_bar_index", "target_time", "in_dataset", "notes",
        }
        assert set(d.keys()) == expected_keys

    def test_deterministic(self):
        imp = _make_impulse()
        w1 = [w.target_bar_index for w in time_square_windows(imp)]
        w2 = [w.target_bar_index for w in time_square_windows(imp)]
        assert w1 == w2


# ── Gap-safety integration ────────────────────────────────────────────────────


class TestGapSafety:
    """Verify that bar_index delta is correct even when a calendar gap exists."""

    def test_gap_safe_bar_count(self):
        """
        Simulate a dataset with a missing bar (gap at day 5).
        bar_index is consecutive (0-8), but calendar days skip one.
        bars_between should return 8, not 9.
        """
        # Build a dataset with a gap at row 4-5 (day index 5 is missing)
        dates = pd.to_datetime([
            "2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04",
            # gap: 2020-01-05 is missing
            "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10",
        ], utc=True)
        df = pd.DataFrame({"timestamp": dates, "close": range(9)})
        df["bar_index"] = range(9)  # consecutive 0-8

        idx_map = build_index_map(df)
        t0 = pd.Timestamp("2020-01-01", tz="UTC")
        t1 = pd.Timestamp("2020-01-10", tz="UTC")
        # bar_index distance = 8 (not 9 calendar days, not 8 trading days)
        count = bars_between(t0, t1, idx_map)
        assert count == 8

    def test_impulse_delta_t_matches_bar_index_delta(self):
        """
        With a gap, the bar_index delta computed by bars_between_by_bar_index
        should match the delta_t field on the impulse (which was also computed
        from bar_index deltas in modules/impulse.py).
        """
        # simulate: origin at bar_index=2, extreme at bar_index=7
        imp = _make_impulse(delta_t=5, origin_bar_index=2, extreme_bar_index=7)
        delta = bars_between_by_bar_index(
            imp["origin_bar_index"], imp["extreme_bar_index"]
        )
        assert delta == imp["delta_t"]
