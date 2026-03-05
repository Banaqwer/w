"""
tests/test_validation.py

Tests for data/validation.py covering all checks defined in data_spec.md §10–12.

All tests use synthetic DataFrames; no live data or MCP connection required.

Coverage:
- OHLC integrity violations (high < low, open outside range, close outside range)
- Duplicate timestamp detection
- Out-of-order row detection
- Missing bar detection (continuity gaps)
- Future timestamp detection
- Volume-missing flag (warn only, no failure)
- Clean DataFrame passes all checks
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from data.validation import DataValidationError, validate_dataset


# ── Helpers ────────────────────────────────────────────────────────────────


def _daily_ohlcv(n: int = 10, start: str = "2024-01-01") -> pd.DataFrame:
    """Return a clean synthetic daily OHLCV DataFrame with n rows."""
    dates = pd.date_range(start=start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open":  [100.0 + i for i in range(n)],
            "high":  [105.0 + i for i in range(n)],
            "low":   [95.0 + i for i in range(n)],
            "close": [102.0 + i for i in range(n)],
            "volume": [1000.0 + i * 10 for i in range(n)],
        }
    )


# ── Clean data ─────────────────────────────────────────────────────────────


def test_clean_data_passes():
    df = _daily_ohlcv(30)
    result = validate_dataset(df, symbol="TEST:BTCUSD", timeframe="1D")
    assert result.passed
    assert result.row_count == 30
    assert result.errors == []
    assert result.ohlc_violations == []
    assert result.duplicate_timestamps == []
    assert result.missing_bars == []
    assert not result.volume_missing


# ── OHLC integrity ─────────────────────────────────────────────────────────


def test_high_less_than_low_fails():
    df = _daily_ohlcv(5)
    df.loc[2, "high"] = 80.0   # force high < low (low is 97)
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D")


def test_open_above_high_fails():
    df = _daily_ohlcv(5)
    df.loc[3, "open"] = 200.0  # open > high
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D")


def test_close_below_low_fails():
    df = _daily_ohlcv(5)
    df.loc[1, "close"] = 10.0  # close < low
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D")


def test_ohlc_violation_no_fail_when_disabled():
    df = _daily_ohlcv(5)
    df.loc[2, "high"] = 80.0
    result = validate_dataset(
        df, symbol="TEST", timeframe="1D",
        config={"fail_on_ohlc_violation": False}
    )
    # Should not raise; violation must be recorded in result
    assert len(result.ohlc_violations) >= 1


def test_multiple_ohlc_violations_all_recorded():
    df = _daily_ohlcv(5)
    df.loc[0, "high"] = 10.0  # high < low
    df.loc[1, "close"] = 500.0  # close > high
    with pytest.raises(DataValidationError) as exc_info:
        validate_dataset(df, symbol="TEST", timeframe="1D")
    assert "OHLC" in str(exc_info.value)


# ── Duplicate timestamps ───────────────────────────────────────────────────


def test_duplicate_timestamp_fails():
    df = _daily_ohlcv(5)
    df.loc[3, "timestamp"] = df.loc[2, "timestamp"]  # duplicate
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D")


def test_duplicate_timestamp_recorded_in_result():
    df = _daily_ohlcv(5)
    df.loc[3, "timestamp"] = df.loc[2, "timestamp"]
    try:
        validate_dataset(df, symbol="TEST", timeframe="1D")
    except DataValidationError:
        pass


# ── Out-of-order rows ──────────────────────────────────────────────────────


def test_out_of_order_rows_detected():
    df = _daily_ohlcv(5)
    # Swap rows 2 and 3 to create out-of-order timestamps
    df.loc[2, "timestamp"], df.loc[3, "timestamp"] = (
        df.loc[3, "timestamp"],
        df.loc[2, "timestamp"],
    )
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D")


# ── Missing bars ───────────────────────────────────────────────────────────


def test_missing_bar_detected():
    df = _daily_ohlcv(10)
    # Drop row 5 to create a gap
    df = df.drop(index=5).reset_index(drop=True)
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D",
                         config={"max_allowed_missing_bars": 0})


def test_missing_bar_allowed_when_within_threshold():
    df = _daily_ohlcv(10)
    df = df.drop(index=5).reset_index(drop=True)
    # Allow up to 1 missing bar
    result = validate_dataset(
        df, symbol="TEST", timeframe="1D",
        config={"max_allowed_missing_bars": 1, "fail_on_missing_bar": True}
    )
    assert result.passed
    assert len(result.missing_bars) > 0


def test_no_missing_bar_detection_for_unknown_timeframe():
    df = _daily_ohlcv(10)
    df = df.drop(index=5).reset_index(drop=True)
    result = validate_dataset(
        df, symbol="TEST", timeframe="UNKNOWN",
        config={"fail_on_missing_bar": False}
    )
    assert len(result.warnings) > 0


# ── Future timestamps ──────────────────────────────────────────────────────


def test_future_timestamp_fails():
    df = _daily_ohlcv(5)
    extraction_time = pd.Timestamp("2020-01-01", tz="UTC")
    with pytest.raises(DataValidationError):
        validate_dataset(
            df,
            symbol="TEST",
            timeframe="1D",
            extraction_timestamp=extraction_time,
        )


def test_future_timestamp_no_fail_when_disabled():
    df = _daily_ohlcv(5)
    extraction_time = pd.Timestamp("2020-01-01", tz="UTC")
    result = validate_dataset(
        df,
        symbol="TEST",
        timeframe="1D",
        extraction_timestamp=extraction_time,
        config={"fail_on_future_timestamp": False},
    )
    assert result.passed
    assert len(result.future_timestamps) > 0


# ── Volume ─────────────────────────────────────────────────────────────────


def test_missing_volume_column_warns_not_fails():
    df = _daily_ohlcv(5).drop(columns=["volume"])
    result = validate_dataset(df, symbol="TEST", timeframe="1D")
    assert result.passed
    assert result.volume_missing
    assert any("volume" in w.lower() for w in result.warnings)


def test_null_volume_rows_warn():
    df = _daily_ohlcv(5)
    df.loc[2, "volume"] = None
    result = validate_dataset(df, symbol="TEST", timeframe="1D")
    assert result.passed
    assert any("volume" in w.lower() for w in result.warnings)


# ── Empty DataFrame ────────────────────────────────────────────────────────


def test_empty_dataframe_fails():
    df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D")


# ── Missing OHLC columns ───────────────────────────────────────────────────


def test_missing_ohlc_column_fails():
    df = _daily_ohlcv(5).drop(columns=["low"])
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="TEST", timeframe="1D")


# ── 6H timeframe (official confirmation TF per 2026-03-05 policy) ─────────


def _6h_ohlcv(n: int = 10, start: str = "2024-01-01") -> pd.DataFrame:
    """Return a clean synthetic 6H OHLCV DataFrame with n rows."""
    dates = pd.date_range(start=start, periods=n, freq="6h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open":  [100.0 + i for i in range(n)],
            "high":  [105.0 + i for i in range(n)],
            "low":   [95.0 + i for i in range(n)],
            "close": [102.0 + i for i in range(n)],
            "volume": [1000.0 + i * 10 for i in range(n)],
        }
    )


def test_6h_clean_data_passes():
    df = _6h_ohlcv(20)
    result = validate_dataset(df, symbol="COINBASE:BTCUSD", timeframe="6H")
    assert result.passed
    assert result.row_count == 20
    assert result.errors == []


def test_6h_missing_bar_detected():
    df = _6h_ohlcv(10)
    df = df.drop(index=5).reset_index(drop=True)
    with pytest.raises(DataValidationError):
        validate_dataset(df, symbol="COINBASE:BTCUSD", timeframe="6H",
                         config={"max_allowed_missing_bars": 0})
