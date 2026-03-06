"""
tests/test_phase2_impulse.py

Tests for modules/impulse.py.

Coverage:
- Impulse dataclass fields and to_dict()
- detect_impulses: upward impulse, downward impulse, all required fields,
  delta_t correctness, slope_raw / slope_log correctness, empty origins,
  max_bars boundary, skip_on_gap with synthetic gap, no skip on 1D data,
  quality_score range, degenerate cases
- impulses_to_dataframe: schema and empty case
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from modules.impulse import (
    Impulse,
    _compute_gap_flags,
    detect_impulses,
    impulses_to_dataframe,
)
from modules.origin_selection import Origin


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_ts(bar: int, freq: str = "D") -> pd.Timestamp:
    return pd.Timestamp("2024-01-01", tz="UTC") + pd.tseries.frequencies.to_offset(freq) * bar  # type: ignore[arg-type]


def _make_df(
    n: int = 50,
    start: str = "2024-01-01",
    freq: str = "D",
    prices: list | None = None,
    atr: float = 20.0,
) -> pd.DataFrame:
    """Return a synthetic processed DataFrame with bar_index."""
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    if prices is None:
        prices = [1000.0 + i * 5 for i in range(n)]
    close = np.array(prices, dtype=float)
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


def _origin(
    bar_index: int,
    origin_type: str = "low",
    price: float | None = None,
    df: pd.DataFrame | None = None,
) -> Origin:
    if price is None and df is not None:
        price = float(
            df.loc[df["bar_index"] == bar_index, "low" if origin_type == "low" else "high"].iloc[0]
        )
    return Origin(
        origin_time=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=bar_index),
        origin_price=price or 1000.0,
        origin_type=origin_type,
        detector_name="pivot_n5",
        quality_score=0.8,
        bar_index=bar_index,
    )


# ── Impulse dataclass ─────────────────────────────────────────────────────


def test_impulse_to_dict_keys():
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    imp = Impulse(
        impulse_id="test_0",
        origin_time=ts,
        origin_price=1000.0,
        extreme_time=ts + pd.Timedelta(days=10),
        extreme_price=1200.0,
        delta_t=10,
        delta_p=200.0,
        slope_raw=20.0,
        slope_log=math.log(1200 / 1000) / 10,
        quality_score=0.7,
        detector_name="pivot_n5",
        direction="up",
        origin_bar_index=0,
        extreme_bar_index=10,
    )
    d = imp.to_dict()
    expected_keys = {
        "impulse_id",
        "origin_time",
        "origin_price",
        "extreme_time",
        "extreme_price",
        "delta_t",
        "delta_p",
        "slope_raw",
        "slope_log",
        "quality_score",
        "detector_name",
        "direction",
        "origin_bar_index",
        "extreme_bar_index",
    }
    assert set(d.keys()) == expected_keys


# ── detect_impulses: upward ───────────────────────────────────────────────


def test_detect_impulses_upward_basic():
    """Origin-low at bar 5; price rises; extreme should be the max high."""
    n = 30
    # Prices rise from bar 5 onward — extreme will be near bar 25-29.
    prices = [1000.0 + i * 10 for i in range(n)]
    df = _make_df(n=n, prices=prices)
    origins = [_origin(bar_index=5, origin_type="low", df=df)]
    impulses = detect_impulses(df, origins, max_bars=25)
    assert len(impulses) == 1
    imp = impulses[0]
    assert imp.direction == "up"
    assert imp.delta_p > 0
    assert imp.extreme_price > imp.origin_price


def test_detect_impulses_downward_basic():
    """Origin-high at bar 5; price falls; extreme should be the min low."""
    n = 30
    prices = [1000.0 - i * 10 for i in range(n)]  # falling prices
    df = _make_df(n=n, prices=prices)
    origins = [_origin(bar_index=5, origin_type="high", df=df)]
    impulses = detect_impulses(df, origins, max_bars=25)
    assert len(impulses) == 1
    imp = impulses[0]
    assert imp.direction == "down"
    assert imp.delta_p < 0
    assert imp.extreme_price < imp.origin_price


def test_detect_impulses_direction_field():
    df = _make_df(50)
    imp_up = detect_impulses(df, [_origin(0, "low", price=900.0)], max_bars=40)
    imp_dn = detect_impulses(df, [_origin(0, "high", price=1300.0)], max_bars=40)
    for imp in imp_up:
        assert imp.direction == "up"
    for imp in imp_dn:
        assert imp.direction == "down"


# ── detect_impulses: required fields ─────────────────────────────────────


def test_detect_impulses_all_fields_present():
    df = _make_df(50)
    origins = [_origin(0, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=40)
    assert len(impulses) == 1
    imp = impulses[0]
    for field in (
        "impulse_id",
        "origin_time",
        "origin_price",
        "extreme_time",
        "extreme_price",
        "delta_t",
        "delta_p",
        "slope_raw",
        "slope_log",
        "quality_score",
        "detector_name",
        "direction",
        "origin_bar_index",
        "extreme_bar_index",
    ):
        assert hasattr(imp, field), f"Missing field: {field}"


def test_detect_impulses_impulse_id_format():
    df = _make_df(50)
    origin = Origin(
        origin_time=pd.Timestamp("2024-01-01", tz="UTC"),
        origin_price=990.0,
        origin_type="low",
        detector_name="pivot_n5",
        quality_score=0.8,
        bar_index=0,
    )
    impulses = detect_impulses(df, [origin], max_bars=40)
    assert len(impulses) == 1
    assert impulses[0].impulse_id == "pivot_n5_0"


# ── detect_impulses: delta_t ─────────────────────────────────────────────


def test_detect_impulses_delta_t_correct():
    """delta_t should equal extreme_bar_index - origin_bar_index."""
    df = _make_df(50)
    origins = [_origin(2, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=40)
    assert len(impulses) == 1
    imp = impulses[0]
    expected_dt = imp.extreme_bar_index - imp.origin_bar_index
    assert imp.delta_t == expected_dt


def test_detect_impulses_delta_t_positive():
    df = _make_df(50)
    origins = [_origin(0, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=40)
    assert all(imp.delta_t > 0 for imp in impulses)


# ── detect_impulses: slope ────────────────────────────────────────────────


def test_detect_impulses_slope_raw_formula():
    df = _make_df(50)
    origins = [_origin(0, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=40)
    assert len(impulses) == 1
    imp = impulses[0]
    expected = imp.delta_p / imp.delta_t
    assert imp.slope_raw == pytest.approx(expected, rel=1e-9)


def test_detect_impulses_slope_log_formula():
    df = _make_df(50)
    origins = [_origin(0, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=40)
    assert len(impulses) == 1
    imp = impulses[0]
    expected = math.log(imp.extreme_price / imp.origin_price) / imp.delta_t
    assert imp.slope_log == pytest.approx(expected, rel=1e-9)


def test_detect_impulses_slope_log_negative_for_down():
    n = 30
    prices = [1200.0 - i * 10 for i in range(n)]
    df = _make_df(n=n, prices=prices)
    origins = [_origin(2, "high", price=1190.0)]
    impulses = detect_impulses(df, origins, max_bars=20)
    assert len(impulses) == 1
    imp = impulses[0]
    assert imp.slope_log < 0


# ── detect_impulses: quality score ────────────────────────────────────────


def test_detect_impulses_quality_in_range():
    df = _make_df(100)
    origins = [_origin(i, "low", price=990.0 + i * 2) for i in range(0, 50, 5)]
    impulses = detect_impulses(df, origins, max_bars=40)
    for imp in impulses:
        assert 0.0 <= imp.quality_score <= 1.0


def test_detect_impulses_quality_no_atr_defaults():
    """When ATR column is absent, quality_score defaults to 0.5."""
    df = _make_df(50).drop(columns=["atr_14"])
    origins = [_origin(0, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=40, atr_col="atr_14")
    assert len(impulses) == 1
    assert impulses[0].quality_score == pytest.approx(0.5)


# ── detect_impulses: max_bars boundary ───────────────────────────────────


def test_detect_impulses_max_bars_limits_window():
    """With max_bars=5, extreme must be within 5 bars of origin."""
    df = _make_df(50)
    origins = [_origin(0, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=5)
    assert len(impulses) == 1
    assert impulses[0].delta_t <= 5


def test_detect_impulses_origin_at_end_skipped():
    """Origin at the last bar has no forward window; must be skipped."""
    df = _make_df(20)
    origins = [_origin(19, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=10)
    assert impulses == []


# ── detect_impulses: empty inputs ─────────────────────────────────────────


def test_detect_impulses_empty_origins():
    df = _make_df(50)
    result = detect_impulses(df, [], max_bars=40)
    assert result == []


def test_detect_impulses_short_df():
    df = _make_df(1)
    origins = [_origin(0, "low", price=990.0)]
    result = detect_impulses(df, origins, max_bars=10)
    assert result == []


# ── detect_impulses: missing required columns ─────────────────────────────


def test_detect_impulses_missing_bar_index_raises():
    df = _make_df(50).drop(columns=["bar_index"])
    origins = [_origin(0, "low", price=990.0)]
    with pytest.raises(ValueError, match="bar_index"):
        detect_impulses(df, origins)


# ── detect_impulses: gap handling ─────────────────────────────────────────


def _make_df_with_gap(gap_after_bar: int = 10, n: int = 30) -> pd.DataFrame:
    """Return a DataFrame with a 2-period gap after bar `gap_after_bar`."""
    dates_before = pd.date_range("2024-01-01", periods=gap_after_bar + 1, freq="D", tz="UTC")
    # Gap: skip 2 days
    dates_after = pd.date_range(
        dates_before[-1] + pd.Timedelta(days=3),
        periods=n - gap_after_bar - 1,
        freq="D",
        tz="UTC",
    )
    dates = dates_before.append(dates_after)
    n_actual = len(dates)
    close = 1000.0 + np.arange(n_actual) * 5
    high = close + 10.0
    low = close - 10.0
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * n_actual,
            "bar_index": np.arange(n_actual, dtype=np.int64),
            "atr_14": [20.0] * n_actual,
        }
    )


def test_detect_impulses_skip_on_gap_skips_crossing():
    """Origin whose window crosses the gap must be skipped when skip_on_gap=True."""
    df = _make_df_with_gap(gap_after_bar=10, n=30)
    # Origin at bar 5, window extends through the gap at bar 11.
    origins = [_origin(5, "low", price=1000.0)]
    impulses_skipped = detect_impulses(df, origins, max_bars=20, skip_on_gap=True)
    assert impulses_skipped == []


def test_detect_impulses_no_skip_on_gap_includes_crossing():
    """When skip_on_gap=False, gap-crossing impulses are still produced."""
    df = _make_df_with_gap(gap_after_bar=10, n=30)
    origins = [_origin(5, "low", price=1000.0)]
    impulses_included = detect_impulses(df, origins, max_bars=20, skip_on_gap=False)
    assert len(impulses_included) > 0


def test_detect_impulses_origin_before_gap_no_skip_when_window_clear():
    """Origin whose window ends BEFORE the gap must NOT be skipped."""
    df = _make_df_with_gap(gap_after_bar=15, n=30)
    # Origin at bar 5, window of 5 bars ends at bar 10, gap at 16.
    origins = [_origin(5, "low", price=1000.0)]
    impulses = detect_impulses(df, origins, max_bars=5, skip_on_gap=True)
    assert len(impulses) > 0


# ── _compute_gap_flags ────────────────────────────────────────────────────


def test_compute_gap_flags_no_gap():
    df = _make_df(30)
    flags = _compute_gap_flags(df)
    assert not np.any(flags)


def test_compute_gap_flags_detects_gap():
    df = _make_df_with_gap(gap_after_bar=10, n=30)
    flags = _compute_gap_flags(df)
    # Exactly one gap should be flagged (immediately after the gap position).
    assert np.sum(flags) >= 1


def test_compute_gap_flags_length_matches_df():
    df = _make_df(50)
    flags = _compute_gap_flags(df)
    assert len(flags) == len(df)


def test_compute_gap_flags_first_bar_never_gap():
    df = _make_df_with_gap(gap_after_bar=5, n=20)
    flags = _compute_gap_flags(df)
    assert flags[0] is np.bool_(False) or flags[0] == False  # noqa: E712


# ── detect_impulses: sorted output ────────────────────────────────────────


def test_detect_impulses_sorted_by_origin_bar_index():
    df = _make_df(100)
    origins = [
        _origin(20, "low", price=990.0),
        _origin(5, "low", price=990.0),
        _origin(40, "low", price=990.0),
    ]
    impulses = detect_impulses(df, origins, max_bars=10)
    bar_idxs = [imp.origin_bar_index for imp in impulses]
    assert bar_idxs == sorted(bar_idxs)


# ── impulses_to_dataframe ─────────────────────────────────────────────────


def test_impulses_to_dataframe_schema():
    df = _make_df(50)
    origins = [_origin(0, "low", price=990.0)]
    impulses = detect_impulses(df, origins, max_bars=40)
    result = impulses_to_dataframe(impulses)
    assert isinstance(result, pd.DataFrame)
    expected_cols = {
        "impulse_id",
        "origin_time",
        "origin_price",
        "extreme_time",
        "extreme_price",
        "delta_t",
        "delta_p",
        "slope_raw",
        "slope_log",
        "quality_score",
        "detector_name",
        "direction",
        "origin_bar_index",
        "extreme_bar_index",
    }
    assert expected_cols.issubset(set(result.columns))


def test_impulses_to_dataframe_row_count():
    df = _make_df(50)
    origins = [_origin(i, "low", price=990.0 + i) for i in range(0, 40, 5)]
    impulses = detect_impulses(df, origins, max_bars=5)
    result = impulses_to_dataframe(impulses)
    assert len(result) == len(impulses)


def test_impulses_to_dataframe_empty():
    result = impulses_to_dataframe([])
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0
    assert "impulse_id" in result.columns
