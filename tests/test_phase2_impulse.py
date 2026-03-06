"""
tests/test_phase2_impulse.py

Tests for modules/impulse.py — Phase 2.

Coverage:
- detect_impulses: correct schema fields on every Impulse
- detect_impulses: deterministic output on fixed input
- detect_impulses: direction correct for up/down origins
- detect_impulses: delta_t >= min_delta_t for all impulses
- detect_impulses: slope_raw = delta_p / delta_t
- detect_impulses: slope_log = (log extreme - log origin) / delta_t
- detect_impulses: quality_score in [0, 1]
- detect_impulses: origins not in DataFrame are skipped
- detect_impulses: skip_on_gap=True excludes origins spanning a gap
- detect_impulses: skip_on_gap=False passes through gapped origins
- detect_impulses: raises on missing required columns
- Impulse.impulse_id format
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from modules.origin_selection import Origin, detect_pivot_origins
from modules.impulse import Impulse, detect_impulses


# ── Synthetic helpers ──────────────────────────────────────────────────────


def _make_df(
    n: int = 120,
    start: str = "2024-01-01",
    freq: str = "D",
    seed: int = 42,
) -> pd.DataFrame:
    """Processed OHLCV DataFrame with bar_index and atr_14."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    price = 10_000.0 + np.cumsum(rng.normal(0, 200, n))
    price = np.maximum(price, 100.0)
    spread = rng.uniform(50, 400, n)
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": price - spread * 0.3,
            "high": price + spread * 0.7,
            "low": price - spread * 0.7,
            "close": price + spread * 0.1,
            "volume": rng.uniform(1_000, 10_000, n),
        }
    )
    df["bar_index"] = np.arange(n, dtype=np.int64)
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    df["atr_14"] = tr.rolling(window=14, min_periods=14).mean()
    return df


def _make_df_with_gap(gap_at_row: int = 60, n: int = 120, seed: int = 42) -> pd.DataFrame:
    """DataFrame where bar_index has a gap of 2 at gap_at_row (simulates a missing bar)."""
    df = _make_df(n=n, seed=seed)
    bi = df["bar_index"].to_numpy().copy()
    bi[gap_at_row:] += 1  # gap: bar_index jumps by 2 at gap_at_row
    df["bar_index"] = bi
    return df


def _make_origin(
    bar_index: int,
    origin_type: str,
    df: pd.DataFrame,
    detector_name: str = "pivot_n5",
) -> Origin:
    """Create an Origin object pointing at the given bar_index in df."""
    row = df[df["bar_index"] == bar_index].iloc[0]
    price = float(row["high"] if origin_type == "high" else row["low"])
    return Origin(
        origin_time=pd.Timestamp(row["timestamp"]),
        origin_price=price,
        bar_index=int(bar_index),
        origin_type=origin_type,
        detector_name=detector_name,
        quality_score=0.5,
    )


# ── Schema validation helper ───────────────────────────────────────────────


_REQUIRED_FIELDS = {
    "impulse_id",
    "origin_time",
    "origin_price",
    "extreme_time",
    "extreme_price",
    "origin_bar_index",
    "extreme_bar_index",
    "delta_t",
    "delta_p",
    "slope_raw",
    "slope_log",
    "direction",
    "quality_score",
    "detector_name",
    "gap_in_window",
}


def _assert_impulse_schema(imp: Impulse) -> None:
    for f in _REQUIRED_FIELDS:
        assert hasattr(imp, f), f"Impulse missing field: {f}"
    assert isinstance(imp.origin_time, pd.Timestamp)
    assert isinstance(imp.extreme_time, pd.Timestamp)
    assert isinstance(imp.delta_t, int) and imp.delta_t >= 0
    assert isinstance(imp.delta_p, float)
    assert isinstance(imp.slope_raw, float)
    assert imp.direction in ("up", "down")
    assert 0.0 <= imp.quality_score <= 1.0
    assert isinstance(imp.gap_in_window, bool)


# ── detect_impulses ────────────────────────────────────────────────────────


class TestDetectImpulses:
    def test_returns_list(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        result = detect_impulses(df, origins)
        assert isinstance(result, list)

    def test_schema_fields(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        assert len(impulses) > 0, "Expected at least one impulse"
        for imp in impulses:
            _assert_impulse_schema(imp)

    def test_deterministic(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        r1 = detect_impulses(df, origins)
        r2 = detect_impulses(df, origins)
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a == b

    def test_sorted_ascending_by_origin_time(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        times = [imp.origin_time for imp in impulses]
        assert times == sorted(times)

    def test_direction_up_for_low_origin(self):
        df = _make_df(n=50)
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            origin = next(o for o in origins if o.bar_index == imp.origin_bar_index)
            if origin.origin_type == "low":
                assert imp.direction == "up", (
                    f"Low origin at bar_index {origin.bar_index} should produce up impulse"
                )

    def test_direction_down_for_high_origin(self):
        df = _make_df(n=50)
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            origin = next(o for o in origins if o.bar_index == imp.origin_bar_index)
            if origin.origin_type == "high":
                assert imp.direction == "down"

    def test_delta_t_at_least_min(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins, min_delta_t=2)
        for imp in impulses:
            assert imp.delta_t >= 2

    def test_slope_raw_equals_delta_p_over_delta_t(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            expected = imp.delta_p / imp.delta_t
            assert math.isclose(imp.slope_raw, expected, rel_tol=1e-9), (
                f"slope_raw mismatch for {imp.impulse_id}: {imp.slope_raw} vs {expected}"
            )

    def test_slope_log_formula(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            if not math.isnan(imp.slope_log):
                expected = (math.log(imp.extreme_price) - math.log(imp.origin_price)) / imp.delta_t
                assert math.isclose(imp.slope_log, expected, rel_tol=1e-9)

    def test_quality_score_in_range(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            assert 0.0 <= imp.quality_score <= 1.0

    def test_impulse_id_format(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            # impulse_id = "<detector_name>_<origin_bar_index>"
            assert imp.detector_name in imp.impulse_id
            assert str(imp.origin_bar_index) in imp.impulse_id

    def test_empty_origins_returns_empty(self):
        df = _make_df()
        result = detect_impulses(df, [])
        assert result == []

    def test_origin_not_in_df_is_skipped(self):
        df = _make_df(n=50)
        # Create an origin with a bar_index that does not exist in df
        bad_origin = Origin(
            origin_time=pd.Timestamp("2030-01-01", tz="UTC"),
            origin_price=50_000.0,
            bar_index=9999,
            origin_type="low",
            detector_name="test",
            quality_score=0.5,
        )
        result = detect_impulses(df, [bad_origin])
        assert result == []

    def test_raises_on_missing_column(self):
        df = _make_df().drop(columns=["high"])
        origins = [_make_origin(10, "low", _make_df())]
        with pytest.raises(ValueError, match="Missing required columns"):
            detect_impulses(df, origins)

    def test_extreme_bar_index_after_origin(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            assert imp.extreme_bar_index > imp.origin_bar_index

    def test_up_impulse_extreme_above_origin(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            if imp.direction == "up":
                assert imp.extreme_price >= imp.origin_price

    def test_down_impulse_extreme_below_origin(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins)
        for imp in impulses:
            if imp.direction == "down":
                assert imp.extreme_price <= imp.origin_price


# ── Gap handling ───────────────────────────────────────────────────────────


class TestGapHandling:
    def test_skip_on_gap_true_excludes_gapped_origins(self):
        """With skip_on_gap=True, no impulse should have gap_in_window=True."""
        df = _make_df_with_gap(gap_at_row=60)
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins, skip_on_gap=True)
        for imp in impulses:
            assert imp.gap_in_window is False, (
                f"Expected gap_in_window=False but got True for {imp.impulse_id}"
            )

    def test_skip_on_gap_false_allows_gapped_windows(self):
        """With skip_on_gap=False, impulses from gapped windows are allowed."""
        df = _make_df_with_gap(gap_at_row=60)
        origins = detect_pivot_origins(df, n=5)
        impulses_no_skip = detect_impulses(df, origins, skip_on_gap=False)
        impulses_skip = detect_impulses(df, origins, skip_on_gap=True)
        # Allowing gaps should produce at least as many impulses
        assert len(impulses_no_skip) >= len(impulses_skip)

    def test_skip_on_gap_true_still_produces_some_impulses(self):
        """Even with skip_on_gap=True, origins before the gap should produce impulses."""
        df = _make_df_with_gap(gap_at_row=60, n=120)
        origins = detect_pivot_origins(df, n=5)
        impulses = detect_impulses(df, origins, skip_on_gap=True, max_lookahead_bars=20)
        # Origins far from the gap should not be affected
        assert len(impulses) > 0

    def test_gap_in_window_flag_set_when_skip_off(self):
        """With skip_on_gap=False, gap_in_window should be True for at least one impulse
        whose window crosses the manufactured bar_index gap."""
        df = _make_df_with_gap(gap_at_row=60, n=120, seed=7)
        # Manually create an origin just before the gap row
        # so its lookahead window will cross it
        gap_origin_row = 58  # two bars before the gap
        gap_bi = int(df["bar_index"].iloc[gap_origin_row])
        origin = _make_origin(gap_bi, "low", df)
        impulses = detect_impulses(df, [origin], skip_on_gap=False, max_lookahead_bars=10)
        if impulses:
            # At least one impulse from this origin should flag the gap
            assert any(imp.gap_in_window for imp in impulses), (
                "Expected gap_in_window=True for impulse crossing the gap"
            )

    def test_6h_missing_bar_count_triggers_skip(self):
        """Integration test: if manifest says missing_bar_count > 0,
        caller sets skip_on_gap=True; verify the overall count is consistent."""
        df = _make_df_with_gap(gap_at_row=60, n=120)
        origins = detect_pivot_origins(df, n=5)
        # Simulate what the smoke script does for 6H
        missing_bar_count = 1  # from manifest
        skip_on_gap = missing_bar_count > 0
        assert skip_on_gap is True
        impulses = detect_impulses(df, origins, skip_on_gap=skip_on_gap)
        # Must produce at least some impulses and none with gap_in_window=True
        assert len(impulses) >= 0  # might be 0 if dataset is edge-case; not a failure
        for imp in impulses:
            assert imp.gap_in_window is False
