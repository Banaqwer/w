"""
core/coordinate_system.py

Canonical location for all index and derived-field computations stored in every
processed dataset.  No downstream module may recompute these fields from raw
data; all modules must read from the processed dataset produced here.

Assumptions
-----------
- Assumption 11: trading_day_index = cumulative count of non-null bars from row 0.
  For 24/7 BTC/USD daily data this is identical to bar_index unless gaps exist.
- Assumption 12: bar_index and calendar_day_index are zero-based, anchored to the
  first bar present in the dataset.
- Assumption 13: first atr_warmup_rows rows have NaN ATR values; they are kept in
  the dataset but flagged via the manifest.
- Assumption 14: get_angle_scale_basis uses median ATR (excluding warm-up rows).

References
----------
docs/handoff/jenkins_quant_python_blueprint.md — Section 8
ASSUMPTIONS.md — Assumptions 11–14
"""

from __future__ import annotations

import logging
import warnings
from typing import List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Public API ─────────────────────────────────────────────────────────────


def add_indices(df: pd.DataFrame) -> pd.DataFrame:
    """Add bar_index, calendar_day_index, and trading_day_index to *df*.

    Parameters
    ----------
    df:
        DataFrame with a UTC-normalised ``timestamp`` column or a DatetimeIndex.
        Rows must already be sorted ascending.

    Returns
    -------
    The same DataFrame with three new integer columns appended.  Modifications
    are applied in-place and the object is returned for chaining.

    Notes
    -----
    - ``bar_index``: 0-based row counter from the first bar in the dataset.
    - ``calendar_day_index``: elapsed UTC calendar days from the first bar's
      timestamp.  Gaps in the series produce non-consecutive values here.
    - ``trading_day_index``: cumulative count of observed (present) bars from
      row 0.  For 24/7 crypto daily data with no missing bars this equals
      ``bar_index``.  If gaps exist the sequence has no holes but the values
      diverge from ``calendar_day_index``.
    """
    ts = _get_timestamps(df)

    if ts is None or len(ts) == 0:
        raise ValueError(
            "DataFrame must have a 'timestamp' column or a DatetimeIndex "
            "with UTC-normalised datetime values."
        )

    epoch = ts.iloc[0] if hasattr(ts, "iloc") else ts[0]

    df["bar_index"] = np.arange(len(df), dtype=np.int64)
    df["calendar_day_index"] = ((ts - epoch).dt.total_seconds() / 86400).round().astype(np.int64)
    df["trading_day_index"] = np.arange(len(df), dtype=np.int64)

    return df


def add_derived_fields(df: pd.DataFrame, atr_windows: List[int]) -> pd.DataFrame:
    """Add log_close, hl_range, true_range, and atr_<n> for each window.

    Parameters
    ----------
    df:
        DataFrame with ``open``, ``high``, ``low``, ``close`` columns.
    atr_windows:
        List of integer ATR windows.  An ``atr_<n>`` column is added for each.

    Returns
    -------
    The same DataFrame with new float columns appended.

    Notes
    -----
    ``true_range`` for the first row is set to ``high - low`` because there is
    no previous close.  Subsequent rows use:
    ``max(high - low, |high - prev_close|, |low - prev_close|)``

    ATR values are computed with a simple rolling mean.  The first
    ``window - 1`` values will be NaN (warm-up period); see Assumption 13.
    """
    _require_ohlc(df)

    df["log_close"] = np.log(df["close"])
    df["hl_range"] = df["high"] - df["low"]

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
    df["true_range"] = tr

    for window in atr_windows:
        col = f"atr_{window}"
        df[col] = df["true_range"].rolling(window=window, min_periods=window).mean()

    return df


def build_coordinate_system(df: pd.DataFrame, atr_windows: List[int]) -> pd.DataFrame:
    """Convenience wrapper: run add_indices then add_derived_fields.

    Parameters
    ----------
    df:
        Raw OHLCV DataFrame sorted ascending with UTC timestamps.
    atr_windows:
        ATR windows to compute (e.g. ``[14]``).

    Returns
    -------
    Fully annotated DataFrame ready for processed-dataset storage.
    """
    df = add_indices(df)
    df = add_derived_fields(df, atr_windows)
    return df


def get_angle_scale_basis(df: pd.DataFrame, atr_warmup_rows: int = 14) -> dict:
    """Return the price-per-bar scale factor for adjusted-angle modules.

    The scale basis is the **median ATR-14** across all rows that are beyond
    the warm-up period.  This scalar normalises angular measurements so that
    angles are comparable across different volatility regimes (Assumption 14).

    Parameters
    ----------
    df:
        Processed DataFrame that already has an ``atr_14`` column.
    atr_warmup_rows:
        Number of leading rows to exclude (warm-up period).

    Returns
    -------
    ``dict`` with keys:
    - ``price_per_bar``: median ATR value (float)
    - ``atr_column_used``: name of the ATR column (str)
    - ``rows_excluded_warmup``: number of warm-up rows excluded (int)
    - ``rows_used``: number of rows included in the median (int)
    """
    atr_col = "atr_14"
    if atr_col not in df.columns:
        raise ValueError(
            f"Column '{atr_col}' not found.  Run build_coordinate_system first."
        )

    valid_rows = df.iloc[atr_warmup_rows:][atr_col].dropna()
    if valid_rows.empty:
        raise ValueError(
            "No valid ATR rows found after excluding warm-up rows. "
            "Dataset may be too short."
        )

    median_atr = float(valid_rows.median())
    logger.debug(
        "get_angle_scale_basis: median_atr=%.4f over %d rows (excluded %d warm-up)",
        median_atr,
        len(valid_rows),
        atr_warmup_rows,
    )

    return {
        "price_per_bar": median_atr,
        "atr_column_used": atr_col,
        "rows_excluded_warmup": atr_warmup_rows,
        "rows_used": len(valid_rows),
    }


# ── Private helpers ────────────────────────────────────────────────────────


def _get_timestamps(df: pd.DataFrame) -> pd.Series:
    """Return a Series of timestamps from the 'timestamp' column or index."""
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True)
        return ts.reset_index(drop=True)
    if isinstance(df.index, pd.DatetimeIndex):
        ts = df.index.to_series().reset_index(drop=True)
        if ts.dt.tz is None:
            warnings.warn(
                "DatetimeIndex is timezone-naive; assuming UTC.", stacklevel=3
            )
            ts = ts.dt.tz_localize("UTC")
        return ts
    raise ValueError(
        "DataFrame must have a 'timestamp' column or a DatetimeIndex."
    )


def _require_ohlc(df: pd.DataFrame) -> None:
    """Raise ValueError if required OHLC columns are missing."""
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required OHLC columns: {sorted(missing)}")
