"""
tests/test_coordinate_system.py

Tests for core/coordinate_system.py.

All tests use synthetic DataFrames; no live data required.

Coverage:
- bar_index: zero-based, increments by 1, length matches DataFrame
- calendar_day_index: elapsed UTC days from row 0
- trading_day_index: equals bar_index for daily data with no gaps
- log_close: ln(close) correctness
- hl_range: high - low
- true_range: max of three components; first row uses H-L
- atr_<n>: NaN for first n-1 rows, non-NaN thereafter
- get_angle_scale_basis: returns median ATR, excludes warmup rows
- build_coordinate_system: all fields present after one call
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core.coordinate_system import (
    add_derived_fields,
    add_indices,
    build_coordinate_system,
    get_angle_scale_basis,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _daily_df(n: int = 30, start: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open":  [100.0 + i for i in range(n)],
            "high":  [105.0 + i for i in range(n)],
            "low":   [95.0 + i for i in range(n)],
            "close": [102.0 + i for i in range(n)],
            "volume": [1000.0] * n,
        }
    )


# ── add_indices ────────────────────────────────────────────────────────────


def test_bar_index_starts_at_zero():
    df = add_indices(_daily_df(10))
    assert df["bar_index"].iloc[0] == 0


def test_bar_index_increments_by_one():
    df = add_indices(_daily_df(10))
    diffs = df["bar_index"].diff().iloc[1:]
    assert (diffs == 1).all()


def test_bar_index_length_matches():
    n = 15
    df = add_indices(_daily_df(n))
    assert len(df["bar_index"]) == n
    assert df["bar_index"].iloc[-1] == n - 1


def test_calendar_day_index_starts_at_zero():
    df = add_indices(_daily_df(10))
    assert df["calendar_day_index"].iloc[0] == 0


def test_calendar_day_index_daily_increments_by_one():
    df = add_indices(_daily_df(10))
    diffs = df["calendar_day_index"].diff().iloc[1:]
    assert (diffs == 1).all()


def test_calendar_day_index_with_gap():
    """If a bar is missing, calendar_day_index skips the gap."""
    df = _daily_df(10)
    df = df.drop(index=5).reset_index(drop=True)
    df = add_indices(df)
    # Row 4 → day 4, row 5 (originally row 6) → day 6: gap of 2
    assert df["calendar_day_index"].iloc[4] == 4
    assert df["calendar_day_index"].iloc[5] == 6


def test_trading_day_index_no_gap_equals_bar_index():
    df = add_indices(_daily_df(20))
    assert (df["trading_day_index"] == df["bar_index"]).all()


def test_add_indices_with_datetime_index():
    """add_indices should work when the DataFrame has a DatetimeIndex."""
    df = _daily_df(5)
    df = df.set_index("timestamp")
    df = add_indices(df)
    assert "bar_index" in df.columns
    assert df["bar_index"].iloc[0] == 0


def test_add_indices_raises_without_timestamp():
    df = pd.DataFrame({"open": [1, 2], "close": [2, 3]})
    with pytest.raises(ValueError, match="timestamp"):
        add_indices(df)


# ── add_derived_fields ─────────────────────────────────────────────────────


def test_log_close_correctness():
    df = _daily_df(5)
    df = add_derived_fields(df, atr_windows=[14])
    for i, row in df.iterrows():
        assert math.isclose(row["log_close"], math.log(row["close"]), rel_tol=1e-9)


def test_hl_range_correctness():
    df = _daily_df(5)
    df = add_derived_fields(df, atr_windows=[14])
    for i, row in df.iterrows():
        assert math.isclose(row["hl_range"], row["high"] - row["low"], rel_tol=1e-9)


def test_true_range_first_row_is_hl():
    df = _daily_df(5)
    df = add_derived_fields(df, atr_windows=[14])
    expected_tr0 = df["high"].iloc[0] - df["low"].iloc[0]
    assert math.isclose(df["true_range"].iloc[0], expected_tr0, rel_tol=1e-9)


def test_true_range_subsequent_rows():
    df = _daily_df(5)
    df = add_derived_fields(df, atr_windows=[14])
    for i in range(1, len(df)):
        h, l, c_prev = df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i - 1]
        expected = max(h - l, abs(h - c_prev), abs(l - c_prev))
        assert math.isclose(df["true_range"].iloc[i], expected, rel_tol=1e-9)


def test_atr_warmup_is_nan():
    df = _daily_df(30)
    df = add_derived_fields(df, atr_windows=[14])
    # First 13 rows should be NaN (rolling window not yet filled)
    assert df["atr_14"].iloc[:13].isna().all()


def test_atr_non_nan_after_warmup():
    df = _daily_df(30)
    df = add_derived_fields(df, atr_windows=[14])
    assert df["atr_14"].iloc[13:].notna().all()


def test_multiple_atr_windows():
    df = _daily_df(50)
    df = add_derived_fields(df, atr_windows=[5, 14, 21])
    assert "atr_5" in df.columns
    assert "atr_14" in df.columns
    assert "atr_21" in df.columns


def test_add_derived_fields_raises_missing_column():
    df = pd.DataFrame({"open": [1, 2], "high": [2, 3], "close": [1.5, 2.5]})
    with pytest.raises(ValueError, match="low"):
        add_derived_fields(df, atr_windows=[14])


# ── build_coordinate_system ────────────────────────────────────────────────


def test_build_coordinate_system_all_fields_present():
    df = build_coordinate_system(_daily_df(30), atr_windows=[14])
    required = [
        "bar_index", "calendar_day_index", "trading_day_index",
        "log_close", "hl_range", "true_range", "atr_14",
    ]
    for col in required:
        assert col in df.columns, f"Missing column: {col}"


# ── get_angle_scale_basis ──────────────────────────────────────────────────


def test_get_angle_scale_basis_returns_dict():
    df = build_coordinate_system(_daily_df(30), atr_windows=[14])
    result = get_angle_scale_basis(df)
    assert isinstance(result, dict)
    assert "price_per_bar" in result


def test_get_angle_scale_basis_excludes_warmup():
    df = build_coordinate_system(_daily_df(30), atr_windows=[14])
    result = get_angle_scale_basis(df, atr_warmup_rows=14)
    assert result["rows_excluded_warmup"] == 14
    assert result["rows_used"] == 30 - 14


def test_get_angle_scale_basis_price_per_bar_positive():
    df = build_coordinate_system(_daily_df(30), atr_windows=[14])
    result = get_angle_scale_basis(df)
    assert result["price_per_bar"] > 0


def test_get_angle_scale_basis_raises_without_atr():
    df = _daily_df(30)
    with pytest.raises(ValueError, match="atr_14"):
        get_angle_scale_basis(df)


def test_get_angle_scale_basis_too_short_raises():
    df = build_coordinate_system(_daily_df(10), atr_windows=[14])
    # Only 10 rows but warmup is 14 — no valid ATR rows
    with pytest.raises(ValueError, match="too short"):
        get_angle_scale_basis(df, atr_warmup_rows=14)
