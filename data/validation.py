"""
data/validation.py

OHLC integrity checks and timestamp-continuity validation for raw and
processed datasets, implementing the rules in data_spec.md §10–12.

All checks are fail-fast by default.  The caller controls behaviour via the
``config`` dict (or keyword overrides).  If a check fails, a
``DataValidationError`` is raised; every failure is also written to the
optional ``failure_log`` list so callers can capture details without catching
exceptions mid-loop.

References
----------
docs/data/data_spec.md — §10 (missing-bar policy), §11 (OHLC integrity),
                          §12 (resampling rules)
DECISIONS.md — max_allowed_missing_bars
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Exceptions ─────────────────────────────────────────────────────────────


class DataValidationError(Exception):
    """Raised when a dataset fails a mandatory validation check."""


# ── Result object ──────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Holds the outcome of a full validation run."""

    passed: bool = True
    symbol: str = ""
    timeframe: str = ""
    row_count: int = 0
    duplicate_timestamps: List[str] = field(default_factory=list)
    out_of_order_rows: List[int] = field(default_factory=list)
    missing_bars: List[str] = field(default_factory=list)
    ohlc_violations: List[Dict] = field(default_factory=list)
    future_timestamps: List[str] = field(default_factory=list)
    volume_missing: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.passed = False
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


# ── Public entry point ─────────────────────────────────────────────────────


def validate_dataset(
    df: pd.DataFrame,
    symbol: str = "",
    timeframe: str = "1D",
    extraction_timestamp: Optional[pd.Timestamp] = None,
    config: Optional[dict] = None,
) -> ValidationResult:
    """Run all validation checks against *df* and return a :class:`ValidationResult`.

    Parameters
    ----------
    df:
        Raw OHLCV DataFrame.  Must have at minimum ``timestamp``, ``open``,
        ``high``, ``low``, ``close`` columns.  ``volume`` is optional but
        flagged if absent.
    symbol:
        TradingView symbol string for logging (e.g. ``"COINBASE:BTCUSD"``).
    timeframe:
        Timeframe string for logging and bar-gap computation
        (e.g. ``"1D"``, ``"4H"``).
    extraction_timestamp:
        UTC datetime of when the raw data was pulled.  Used to check for
        future timestamps.  If ``None``, future-timestamp check is skipped.
    config:
        Optional dict of validation settings mirroring ``configs/default.yaml``
        ``validation`` section.  Keys::

            fail_on_ohlc_violation      (bool, default True)
            fail_on_duplicate_timestamp (bool, default True)
            fail_on_missing_bar         (bool, default True)
            max_allowed_missing_bars    (int,  default 0)
            fail_on_future_timestamp    (bool, default True)
            require_volume              (bool, default False)

    Returns
    -------
    :class:`ValidationResult` — callers should check ``.passed`` and may
    raise :class:`DataValidationError` themselves if needed.

    Raises
    ------
    DataValidationError
        If any *fail_on_* setting is True and the corresponding check finds
        violations beyond the allowed threshold.
    """
    cfg = _merge_config(config)
    result = ValidationResult(symbol=symbol, timeframe=timeframe)

    if df is None or df.empty:
        result.fail("DataFrame is empty or None.")
        _maybe_raise(result, cfg)
        return result

    result.row_count = len(df)

    # Normalise timestamps early so all subsequent checks use a consistent Series
    ts = _normalise_timestamps(df, result)

    _check_out_of_order(ts, result)
    _check_duplicates(ts, result, cfg)
    _check_missing_bars(ts, timeframe, result, cfg)
    _check_ohlc_integrity(df, result, cfg)
    _check_future_timestamps(ts, extraction_timestamp, result, cfg)
    _check_volume(df, result, cfg)

    _maybe_raise(result, cfg)
    return result


# ── Individual checks ──────────────────────────────────────────────────────


def _normalise_timestamps(df: pd.DataFrame, result: ValidationResult) -> pd.Series:
    if "timestamp" not in df.columns:
        result.fail("Missing required 'timestamp' column.")
        return pd.Series(dtype="datetime64[ns, UTC]")
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    n_invalid = ts.isna().sum()
    if n_invalid:
        result.fail(f"{n_invalid} row(s) have unparseable timestamps.")
    return ts


def _check_out_of_order(ts: pd.Series, result: ValidationResult) -> None:
    if ts.empty:
        return
    diffs = ts.diff().iloc[1:]
    bad = diffs[diffs < pd.Timedelta(0)]
    if not bad.empty:
        result.out_of_order_rows = bad.index.tolist()
        result.fail(
            f"{len(bad)} out-of-order timestamp(s) found at row indices "
            f"{bad.index.tolist()[:5]}{'...' if len(bad) > 5 else ''}."
        )


def _check_duplicates(
    ts: pd.Series, result: ValidationResult, cfg: dict
) -> None:
    dupes = ts[ts.duplicated(keep=False)]
    if not dupes.empty:
        result.duplicate_timestamps = dupes.astype(str).unique().tolist()
        msg = (
            f"{len(dupes)} duplicate timestamp(s): "
            f"{result.duplicate_timestamps[:3]}{'...' if len(result.duplicate_timestamps) > 3 else ''}"
        )
        if cfg["fail_on_duplicate_timestamp"]:
            result.fail(msg)
        else:
            result.warn(msg)


def _check_missing_bars(
    ts: pd.Series, timeframe: str, result: ValidationResult, cfg: dict
) -> None:
    if ts.empty or len(ts) < 2:
        return

    expected_delta = _timeframe_to_timedelta(timeframe)
    if expected_delta is None:
        result.warn(
            f"Cannot check missing bars: unknown timeframe '{timeframe}'. "
            "Skipping continuity check."
        )
        return

    diffs = ts.diff().iloc[1:]
    gaps = diffs[diffs > expected_delta * 1.5]
    missing: List[str] = []
    for idx, gap in gaps.items():
        n_missed = int(round(gap / expected_delta)) - 1
        prev_ts = ts.iloc[idx - 1] if idx > 0 else ts.iloc[0]  # type: ignore[index]
        missing.append(
            f"~{n_missed} missing bar(s) after {prev_ts.isoformat()} "
            f"(gap={gap})"
        )

    if missing:
        result.missing_bars = missing
        total_missing = sum(
            int(m.split("~")[1].split(" ")[0]) for m in missing
        )
        msg = (
            f"{total_missing} missing bar(s) across {len(missing)} gap(s): "
            f"{missing[:3]}{'...' if len(missing) > 3 else ''}"
        )
        if cfg["fail_on_missing_bar"] and total_missing > cfg["max_allowed_missing_bars"]:
            result.fail(msg)
        else:
            result.warn(msg)


def _check_ohlc_integrity(
    df: pd.DataFrame, result: ValidationResult, cfg: dict
) -> None:
    required = ["open", "high", "low", "close"]
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        result.fail(f"Missing OHLC columns: {missing_cols}")
        return

    violations: List[Dict] = []

    mask_high_low = df["high"] < df["low"]
    mask_open_range = (df["open"] < df["low"]) | (df["open"] > df["high"])
    mask_close_range = (df["close"] < df["low"]) | (df["close"] > df["high"])

    for mask, rule in (
        (mask_high_low, "high < low"),
        (mask_open_range, "open outside [low, high]"),
        (mask_close_range, "close outside [low, high]"),
    ):
        bad_rows = df[mask]
        for row_idx, row in bad_rows.iterrows():
            violations.append(
                {
                    "row_index": row_idx,
                    "rule": rule,
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "timestamp": str(row.get("timestamp", row_idx)),
                }
            )

    if violations:
        result.ohlc_violations = violations
        msg = (
            f"{len(violations)} OHLC integrity violation(s): "
            f"{[v['rule'] for v in violations[:3]]}{'...' if len(violations) > 3 else ''}"
        )
        if cfg["fail_on_ohlc_violation"]:
            result.fail(msg)
        else:
            result.warn(msg)


def _check_future_timestamps(
    ts: pd.Series,
    extraction_timestamp: Optional[pd.Timestamp],
    result: ValidationResult,
    cfg: dict,
) -> None:
    if extraction_timestamp is None or ts.empty:
        return
    if extraction_timestamp.tzinfo is None:
        extraction_timestamp = extraction_timestamp.tz_localize("UTC")

    future = ts[ts > extraction_timestamp]
    if not future.empty:
        result.future_timestamps = future.astype(str).tolist()
        msg = (
            f"{len(future)} future timestamp(s) relative to extraction time "
            f"{extraction_timestamp.isoformat()}: "
            f"{result.future_timestamps[:3]}{'...' if len(future) > 3 else ''}"
        )
        if cfg["fail_on_future_timestamp"]:
            result.fail(msg)
        else:
            result.warn(msg)


def _check_volume(
    df: pd.DataFrame, result: ValidationResult, cfg: dict
) -> None:
    if "volume" not in df.columns:
        result.volume_missing = True
        result.warn("'volume' column is absent in this dataset.")
        return

    n_null = df["volume"].isna().sum()
    if n_null:
        result.warn(f"{n_null} row(s) have null volume.")


# ── Helpers ────────────────────────────────────────────────────────────────


_TIMEFRAME_DELTAS: Dict[str, pd.Timedelta] = {
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4H": pd.Timedelta(hours=4),
    "4h": pd.Timedelta(hours=4),
    "6H": pd.Timedelta(hours=6),
    "6h": pd.Timedelta(hours=6),
    "1D": pd.Timedelta(days=1),
    "1d": pd.Timedelta(days=1),
    "1W": pd.Timedelta(weeks=1),
    "1w": pd.Timedelta(weeks=1),
    "1M": pd.Timedelta(days=30),
}


def _timeframe_to_timedelta(timeframe: str) -> Optional[pd.Timedelta]:
    return _TIMEFRAME_DELTAS.get(timeframe)


def _merge_config(config: Optional[dict]) -> dict:
    defaults = {
        "fail_on_ohlc_violation": True,
        "fail_on_duplicate_timestamp": True,
        "fail_on_missing_bar": True,
        "max_allowed_missing_bars": 0,
        "fail_on_future_timestamp": True,
        "require_volume": False,
    }
    if config:
        defaults.update(config)
    return defaults


def _maybe_raise(result: ValidationResult, cfg: dict) -> None:
    if not result.passed:
        raise DataValidationError(
            f"Dataset validation failed for '{result.symbol}' "
            f"[{result.timeframe}]. Errors: {result.errors}"
        )
