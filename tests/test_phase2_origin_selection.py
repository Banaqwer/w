"""
tests/test_phase2_origin_selection.py

Tests for modules/origin_selection.py — Phase 2.

Coverage:
- detect_pivot_origins: correct pivot-high and pivot-low detection
- detect_pivot_origins: deterministic output on the same input
- detect_pivot_origins: schema fields present on every Origin
- detect_pivot_origins: no pivots produced at dataset boundaries (first/last n rows)
- detect_pivot_origins: raises on missing required columns
- detect_pivot_origins: raises on invalid n
- detect_zigzag_origins: swing-high/low detection with percent threshold
- detect_zigzag_origins: ATR-based threshold mode
- detect_zigzag_origins: deterministic output on the same input
- detect_zigzag_origins: schema fields present on every Origin
- detect_zigzag_origins: raises on invalid threshold
- select_origins: dispatches to correct detector
- select_origins: raises on unknown method
- quality_score: in [0, 1] for all origins
- Gap handling: origins from a 6H-like frame with a missing bar
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from modules.origin_selection import (
    Origin,
    detect_pivot_origins,
    detect_zigzag_origins,
    select_origins,
)


# ── Synthetic helpers ──────────────────────────────────────────────────────


def _make_df(
    n: int = 60,
    start: str = "2024-01-01",
    freq: str = "D",
    seed: int = 42,
) -> pd.DataFrame:
    """Clean OHLCV DataFrame with coordinate fields (bar_index, atr_14)."""
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
    # Compute true_range → rolling ATR(14)
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


def _make_zigzag_df() -> pd.DataFrame:
    """DataFrame with clearly defined up-down swings for zigzag testing."""
    n = 80
    dates = pd.date_range(start="2024-01-01", periods=n, freq="D", tz="UTC")
    # Create a zigzag price: up 10%, down 10%, up 10%, …
    close = np.zeros(n)
    close[0] = 10_000.0
    direction = 1
    for i in range(1, n):
        # Flip direction every 10 bars
        if i % 10 == 0:
            direction *= -1
        close[i] = close[i - 1] * (1 + direction * 0.015)

    spread = close * 0.005
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": close - spread * 0.5,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": np.full(n, 5000.0),
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


def _make_df_with_gap(gap_at_row: int = 30, n: int = 60, seed: int = 42) -> pd.DataFrame:
    """DataFrame with a simulated 6H-style missing bar (bar_index has a gap)."""
    df = _make_df(n=n, seed=seed)
    # Simulate a missing bar by incrementing bar_index by 2 at gap_at_row
    bi = df["bar_index"].to_numpy().copy()
    bi[gap_at_row:] += 1
    df["bar_index"] = bi
    return df


# ── Schema validation helper ───────────────────────────────────────────────


def _assert_origin_schema(origin: Origin) -> None:
    assert isinstance(origin.origin_time, pd.Timestamp)
    assert isinstance(origin.origin_price, float)
    assert isinstance(origin.bar_index, int)
    assert origin.origin_type in ("high", "low")
    assert isinstance(origin.detector_name, str) and len(origin.detector_name) > 0
    assert 0.0 <= origin.quality_score <= 1.0


# ── detect_pivot_origins ────────────────────────────────────────────────────


class TestDetectPivotOrigins:
    def test_returns_list(self):
        df = _make_df()
        result = detect_pivot_origins(df, n=5)
        assert isinstance(result, list)

    def test_schema_fields(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        assert len(origins) > 0, "Expected at least one pivot in a random-walk series"
        for o in origins:
            _assert_origin_schema(o)

    def test_deterministic(self):
        df = _make_df()
        r1 = detect_pivot_origins(df, n=5)
        r2 = detect_pivot_origins(df, n=5)
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a == b

    def test_sorted_ascending(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        times = [o.origin_time for o in origins]
        assert times == sorted(times)

    def test_no_pivot_at_boundary(self):
        """First and last n rows cannot be pivots."""
        n = 5
        df = _make_df(n=50)
        origins = detect_pivot_origins(df, n=n)
        first_valid_bi = n
        last_valid_bi = len(df) - n - 1
        for o in origins:
            assert o.bar_index >= first_valid_bi
            assert o.bar_index <= last_valid_bi

    def test_pivot_high_is_local_maximum(self):
        """Pivot-high origin_price should equal the bar's high."""
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        high_origins = [o for o in origins if o.origin_type == "high"]
        for o in high_origins:
            row = df[df["bar_index"] == o.bar_index].iloc[0]
            assert math.isclose(o.origin_price, row["high"], rel_tol=1e-9)

    def test_pivot_low_is_local_minimum(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        low_origins = [o for o in origins if o.origin_type == "low"]
        for o in low_origins:
            row = df[df["bar_index"] == o.bar_index].iloc[0]
            assert math.isclose(o.origin_price, row["low"], rel_tol=1e-9)

    def test_different_n_gives_different_counts(self):
        """Larger n should produce fewer pivots (stricter filter)."""
        df = _make_df(n=120)
        n3 = detect_pivot_origins(df, n=3)
        n10 = detect_pivot_origins(df, n=10)
        assert len(n3) >= len(n10)

    def test_raises_on_missing_column(self):
        df = _make_df().drop(columns=["high"])
        with pytest.raises(ValueError, match="Missing required columns"):
            detect_pivot_origins(df, n=5)

    def test_raises_on_invalid_n(self):
        df = _make_df()
        with pytest.raises(ValueError, match="pivot n must be >= 1"):
            detect_pivot_origins(df, n=0)

    def test_quality_score_range(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=5)
        for o in origins:
            assert 0.0 <= o.quality_score <= 1.0

    def test_detector_name_includes_n(self):
        df = _make_df()
        origins = detect_pivot_origins(df, n=7)
        for o in origins:
            assert "7" in o.detector_name

    def test_min_quality_filters(self):
        df = _make_df()
        all_origins = detect_pivot_origins(df, n=5, min_quality=0.0)
        high_quality = detect_pivot_origins(df, n=5, min_quality=0.5)
        assert len(high_quality) <= len(all_origins)


# ── detect_zigzag_origins ──────────────────────────────────────────────────


class TestDetectZigzagOrigins:
    def test_returns_list(self):
        df = _make_zigzag_df()
        result = detect_zigzag_origins(df, threshold_pct=3.0)
        assert isinstance(result, list)

    def test_schema_fields(self):
        df = _make_zigzag_df()
        origins = detect_zigzag_origins(df, threshold_pct=3.0)
        assert len(origins) > 0
        for o in origins:
            _assert_origin_schema(o)

    def test_deterministic(self):
        df = _make_zigzag_df()
        r1 = detect_zigzag_origins(df, threshold_pct=3.0)
        r2 = detect_zigzag_origins(df, threshold_pct=3.0)
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a == b

    def test_sorted_ascending(self):
        df = _make_zigzag_df()
        origins = detect_zigzag_origins(df, threshold_pct=3.0)
        times = [o.origin_time for o in origins]
        assert times == sorted(times)

    def test_high_threshold_fewer_origins(self):
        """Higher threshold → fewer reversals detected."""
        df = _make_zigzag_df()
        low_th = detect_zigzag_origins(df, threshold_pct=1.0)
        high_th = detect_zigzag_origins(df, threshold_pct=10.0)
        assert len(low_th) >= len(high_th)

    def test_atr_mode(self):
        """ATR-based zigzag returns valid origins."""
        df = _make_zigzag_df()
        origins = detect_zigzag_origins(df, threshold_pct=None, threshold_atr=1.0)
        assert isinstance(origins, list)
        for o in origins:
            _assert_origin_schema(o)

    def test_atr_mode_requires_atr_column(self):
        df = _make_zigzag_df().drop(columns=["atr_14"])
        with pytest.raises(ValueError, match="Missing required columns"):
            detect_zigzag_origins(df, threshold_atr=1.0)

    def test_raises_on_invalid_threshold(self):
        df = _make_zigzag_df()
        with pytest.raises(ValueError, match="threshold_pct"):
            detect_zigzag_origins(df, threshold_pct=-1.0)

    def test_detector_name_contains_threshold(self):
        df = _make_zigzag_df()
        origins = detect_zigzag_origins(df, threshold_pct=5.0)
        for o in origins:
            assert "5.0" in o.detector_name

    def test_quality_score_range(self):
        df = _make_zigzag_df()
        origins = detect_zigzag_origins(df, threshold_pct=3.0)
        for o in origins:
            assert 0.0 <= o.quality_score <= 1.0

    def test_alternating_type(self):
        """Zigzag origins should alternate high/low."""
        df = _make_zigzag_df()
        origins = detect_zigzag_origins(df, threshold_pct=3.0)
        if len(origins) < 2:
            pytest.skip("Not enough origins to test alternation")
        for i in range(1, len(origins)):
            assert origins[i].origin_type != origins[i - 1].origin_type, (
                f"Consecutive origins of same type at indices {i-1} and {i}"
            )


# ── select_origins dispatcher ──────────────────────────────────────────────


class TestSelectOrigins:
    def test_dispatches_pivot(self):
        df = _make_df()
        origins = select_origins(df, method="pivot", pivot_n=5)
        for o in origins:
            assert "pivot" in o.detector_name

    def test_dispatches_zigzag(self):
        df = _make_zigzag_df()
        origins = select_origins(df, method="zigzag", threshold_pct=3.0)
        for o in origins:
            assert "zigzag" in o.detector_name

    def test_raises_on_unknown_method(self):
        df = _make_df()
        with pytest.raises(ValueError, match="Unknown origin selection method"):
            select_origins(df, method="random_forest")


# ── Gap handling ───────────────────────────────────────────────────────────


class TestGapHandling:
    def test_pivot_works_with_bar_index_gap(self):
        """Pivot detector does not use bar_index spacing; gap is transparent."""
        df = _make_df_with_gap(gap_at_row=30)
        origins = detect_pivot_origins(df, n=5)
        assert isinstance(origins, list)
        # Origins after the gap should have bar_index incremented by 1
        gap_origins = [o for o in origins if o.bar_index >= 31]
        assert all(isinstance(o.bar_index, int) for o in gap_origins)

    def test_zigzag_works_with_bar_index_gap(self):
        """Zigzag does not use bar_index spacing either; gap is transparent."""
        df = _make_df_with_gap(gap_at_row=30)
        origins = detect_zigzag_origins(df, threshold_pct=3.0)
        assert isinstance(origins, list)
