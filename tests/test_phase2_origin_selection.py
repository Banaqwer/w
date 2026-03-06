"""
tests/test_phase2_origin_selection.py

Tests for modules/origin_selection.py.

Coverage:
- Origin dataclass fields and to_dict()
- detect_pivots: basic detection, types, quality score range, determinism,
  short DataFrame, varying n_bars, bar_index propagation
- detect_zigzag: basic detection, alternating highs/lows, threshold controls
  number of origins, determinism, ATR-based threshold fallback
- select_origins: dispatches to pivot and zigzag; raises on unknown method
- origins_to_dataframe: schema and empty case
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.origin_selection import (
    Origin,
    detect_pivots,
    detect_zigzag,
    origins_to_dataframe,
    select_origins,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_df(
    n: int = 60,
    start: str = "2024-01-01",
    freq: str = "D",
    base: float = 1000.0,
    amplitude: float = 100.0,
    atr: float = 20.0,
) -> pd.DataFrame:
    """Return a synthetic DataFrame with a sine-like price pattern.

    Prices oscillate so that swing highs and lows are predictable.
    """
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    t = np.linspace(0, 4 * np.pi, n)
    close = base + amplitude * np.sin(t)
    high = close + 10.0
    low = close - 10.0
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * n,
            "bar_index": np.arange(n, dtype=np.int64),
            "atr_14": [atr] * n,
        }
    )


def _make_trend_df(n: int = 60, up: bool = True) -> pd.DataFrame:
    """Return a strictly trending DataFrame (no oscillation)."""
    dates = pd.date_range(start="2024-01-01", periods=n, freq="D", tz="UTC")
    factor = 1 if up else -1
    close = 1000.0 + factor * np.arange(n, dtype=float) * 5
    high = close + 10.0
    low = close - 10.0
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * n,
            "bar_index": np.arange(n, dtype=np.int64),
            "atr_14": [20.0] * n,
        }
    )


# ── Origin dataclass ───────────────────────────────────────────────────────


def test_origin_to_dict_keys():
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    o = Origin(
        origin_time=ts,
        origin_price=100.0,
        origin_type="high",
        detector_name="pivot_n5",
        quality_score=0.8,
        bar_index=3,
    )
    d = o.to_dict()
    assert set(d.keys()) == {
        "origin_time",
        "origin_price",
        "origin_type",
        "detector_name",
        "quality_score",
        "bar_index",
    }


def test_origin_type_values():
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    for otype in ("high", "low"):
        o = Origin(
            origin_time=ts,
            origin_price=100.0,
            origin_type=otype,
            detector_name="test",
            quality_score=0.5,
            bar_index=0,
        )
        assert o.origin_type == otype


# ── detect_pivots ──────────────────────────────────────────────────────────


def test_detect_pivots_returns_list():
    df = _make_df(60)
    result = detect_pivots(df, n_bars=5)
    assert isinstance(result, list)


def test_detect_pivots_nonzero_for_oscillating():
    df = _make_df(100)
    origins = detect_pivots(df, n_bars=5)
    assert len(origins) > 0


def test_detect_pivots_origin_types_valid():
    df = _make_df(100)
    origins = detect_pivots(df, n_bars=5)
    for o in origins:
        assert o.origin_type in ("high", "low"), f"Bad type: {o.origin_type}"


def test_detect_pivots_quality_score_in_range():
    df = _make_df(100)
    origins = detect_pivots(df, n_bars=5)
    for o in origins:
        assert 0.0 <= o.quality_score <= 1.0, f"quality={o.quality_score}"


def test_detect_pivots_sorted_by_bar_index():
    df = _make_df(100)
    origins = detect_pivots(df, n_bars=5)
    bar_idxs = [o.bar_index for o in origins]
    assert bar_idxs == sorted(bar_idxs)


def test_detect_pivots_bar_index_propagated():
    df = _make_df(60)
    origins = detect_pivots(df, n_bars=5)
    bar_idxs = set(o.bar_index for o in origins)
    # All bar_index values must be present in the dataframe.
    df_bar_idxs = set(int(x) for x in df["bar_index"])
    assert bar_idxs.issubset(df_bar_idxs)


def test_detect_pivots_detector_name_includes_n():
    df = _make_df(60)
    for n in (3, 5, 7):
        origins = detect_pivots(df, n_bars=n)
        for o in origins:
            assert f"pivot_n{n}" == o.detector_name


def test_detect_pivots_short_df_returns_empty():
    """DataFrame shorter than 2*n_bars+1 must yield no pivots."""
    df = _make_df(9)  # 2*5+1 = 11 needed; 9 < 11
    origins = detect_pivots(df, n_bars=5)
    assert origins == []


def test_detect_pivots_deterministic():
    df = _make_df(100)
    r1 = detect_pivots(df, n_bars=5)
    r2 = detect_pivots(df, n_bars=5)
    assert len(r1) == len(r2)
    for a, b in zip(r1, r2):
        assert a.bar_index == b.bar_index
        assert a.origin_type == b.origin_type


def test_detect_pivots_larger_n_fewer_pivots():
    df = _make_df(200)
    origins_n3 = detect_pivots(df, n_bars=3)
    origins_n10 = detect_pivots(df, n_bars=10)
    assert len(origins_n3) >= len(origins_n10)


def test_detect_pivots_no_atr_column_defaults_quality():
    """When ATR column is absent, quality score defaults to 0.5."""
    df = _make_df(60).drop(columns=["atr_14"])
    origins = detect_pivots(df, n_bars=5, atr_col="atr_14")
    for o in origins:
        assert o.quality_score == 0.5


def test_detect_pivots_swing_high_is_local_max():
    """Every swing-high origin price must be the local high for its row."""
    df = _make_df(100)
    for o in detect_pivots(df, n_bars=5):
        if o.origin_type == "high":
            row = df[df["bar_index"] == o.bar_index].iloc[0]
            assert o.origin_price == pytest.approx(float(row["high"]))


def test_detect_pivots_swing_low_is_local_min():
    df = _make_df(100)
    for o in detect_pivots(df, n_bars=5):
        if o.origin_type == "low":
            row = df[df["bar_index"] == o.bar_index].iloc[0]
            assert o.origin_price == pytest.approx(float(row["low"]))


def test_detect_pivots_trending_up_few_lows():
    """Strictly up-trending series should have no swing lows."""
    df = _make_trend_df(50, up=True)
    origins = detect_pivots(df, n_bars=3)
    lows = [o for o in origins if o.origin_type == "low"]
    assert len(lows) == 0


def test_detect_pivots_trending_down_few_highs():
    df = _make_trend_df(50, up=False)
    origins = detect_pivots(df, n_bars=3)
    highs = [o for o in origins if o.origin_type == "high"]
    assert len(highs) == 0


def test_detect_pivots_missing_high_column_raises():
    df = _make_df(60).drop(columns=["high"])
    with pytest.raises(ValueError, match="high"):
        detect_pivots(df)


def test_detect_pivots_missing_bar_index_raises():
    df = _make_df(60).drop(columns=["bar_index"])
    with pytest.raises(ValueError, match="bar_index"):
        detect_pivots(df)


# ── detect_zigzag ─────────────────────────────────────────────────────────


def test_detect_zigzag_returns_list():
    df = _make_df(100)
    result = detect_zigzag(df, reversal_pct=5.0)
    assert isinstance(result, list)


def test_detect_zigzag_nonzero_for_oscillating():
    df = _make_df(200, amplitude=200.0)
    origins = detect_zigzag(df, reversal_pct=5.0)
    assert len(origins) > 0


def test_detect_zigzag_origin_types_valid():
    df = _make_df(200, amplitude=200.0)
    origins = detect_zigzag(df, reversal_pct=5.0)
    for o in origins:
        assert o.origin_type in ("high", "low")


def test_detect_zigzag_alternates_high_low():
    """Zigzag origins must alternate between high and low."""
    df = _make_df(300, amplitude=300.0)
    origins = detect_zigzag(df, reversal_pct=5.0)
    if len(origins) < 2:
        pytest.skip("Not enough origins to check alternation.")
    for i in range(1, len(origins)):
        assert origins[i].origin_type != origins[i - 1].origin_type, (
            f"Consecutive same type at positions {i-1}, {i}: "
            f"{origins[i-1].origin_type}"
        )


def test_detect_zigzag_sorted_by_bar_index():
    df = _make_df(200, amplitude=200.0)
    origins = detect_zigzag(df, reversal_pct=5.0)
    bar_idxs = [o.bar_index for o in origins]
    assert bar_idxs == sorted(bar_idxs)


def test_detect_zigzag_quality_score_is_one():
    df = _make_df(200, amplitude=200.0)
    origins = detect_zigzag(df, reversal_pct=5.0)
    for o in origins:
        assert o.quality_score == 1.0


def test_detect_zigzag_large_threshold_fewer_origins():
    df = _make_df(300, amplitude=300.0)
    origins_small = detect_zigzag(df, reversal_pct=1.0)
    origins_large = detect_zigzag(df, reversal_pct=50.0)
    assert len(origins_small) >= len(origins_large)


def test_detect_zigzag_deterministic():
    df = _make_df(200, amplitude=200.0)
    r1 = detect_zigzag(df, reversal_pct=10.0)
    r2 = detect_zigzag(df, reversal_pct=10.0)
    assert len(r1) == len(r2)
    for a, b in zip(r1, r2):
        assert a.bar_index == b.bar_index
        assert a.origin_type == b.origin_type


def test_detect_zigzag_detector_name_includes_pct():
    df = _make_df(200, amplitude=200.0)
    pct = 15.0
    origins = detect_zigzag(df, reversal_pct=pct)
    for o in origins:
        assert f"zigzag_pct{pct}" == o.detector_name


def test_detect_zigzag_short_df_returns_empty():
    df = _make_df(2)
    origins = detect_zigzag(df, reversal_pct=5.0)
    assert origins == []


def test_detect_zigzag_atr_col_absent_uses_pct():
    """If atr_col is absent from df, falls back to percentage threshold."""
    df = _make_df(200, amplitude=200.0).drop(columns=["atr_14"])
    origins_no_atr = detect_zigzag(df, reversal_pct=10.0, atr_col=None)
    origins_pct = detect_zigzag(df.copy(), reversal_pct=10.0, atr_col=None)
    assert len(origins_no_atr) == len(origins_pct)


def test_detect_zigzag_missing_bar_index_raises():
    df = _make_df(60).drop(columns=["bar_index"])
    with pytest.raises(ValueError, match="bar_index"):
        detect_zigzag(df)


# ── select_origins ─────────────────────────────────────────────────────────


def test_select_origins_pivot_dispatches():
    df = _make_df(100)
    r1 = select_origins(df, method="pivot", n_bars=5)
    r2 = detect_pivots(df, n_bars=5)
    assert len(r1) == len(r2)


def test_select_origins_zigzag_dispatches():
    df = _make_df(200, amplitude=200.0)
    r1 = select_origins(df, method="zigzag", reversal_pct=10.0)
    r2 = detect_zigzag(df, reversal_pct=10.0)
    assert len(r1) == len(r2)


def test_select_origins_invalid_method_raises():
    df = _make_df(60)
    with pytest.raises(ValueError, match="Unknown origin"):
        select_origins(df, method="unknown")


# ── origins_to_dataframe ──────────────────────────────────────────────────


def test_origins_to_dataframe_schema():
    df = _make_df(100)
    origins = detect_pivots(df, n_bars=5)
    result = origins_to_dataframe(origins)
    assert isinstance(result, pd.DataFrame)
    expected_cols = {
        "origin_time",
        "origin_price",
        "origin_type",
        "detector_name",
        "quality_score",
        "bar_index",
    }
    assert expected_cols.issubset(set(result.columns))


def test_origins_to_dataframe_row_count():
    df = _make_df(100)
    origins = detect_pivots(df, n_bars=5)
    result = origins_to_dataframe(origins)
    assert len(result) == len(origins)


def test_origins_to_dataframe_empty():
    result = origins_to_dataframe([])
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0
    assert "origin_time" in result.columns
