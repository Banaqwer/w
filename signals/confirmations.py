"""
signals/confirmations.py

Phase 5 — Confirmation checks for SignalCandidate objects.

Provides pure functions that evaluate whether a SignalCandidate's required
confirmations are satisfied given a recent slice of 6H OHLCV data.

Design rules
------------
- No trading engine, no order management, no PnL accounting.
- All checks are deterministic: same inputs → same outputs.
- Functions return structured :class:`~signals.signal_types.ConfirmationResult`
  objects (pass/fail + reason), never raw booleans.
- When a dataset has ``missing_bar_count > 0``, stricter confirmations are
  applied (e.g. requiring agreement across multiple candles).
- An empty OHLCV slice always produces a ``passed=False`` result with an
  informative reason.

Available checks
----------------
- :func:`check_candle_direction` — most recent complete bar closes in the
  direction consistent with the signal's bias.
- :func:`check_zone_rejection` — price has visited the entry zone and closed
  back outside it (bullish/bearish rejection candle logic).
- :func:`check_strict_multi_candle` — requires N consecutive bars all closing
  in the bias direction; used when ``missing_bar_count > 0``.
- :func:`run_all_confirmations` — runs every check listed in
  ``signal.confirmations_required`` and returns all results.

Public API
----------
- :func:`check_candle_direction`
- :func:`check_zone_rejection`
- :func:`check_strict_multi_candle`
- :func:`run_all_confirmations`

References
----------
signals/signal_types.py — SignalCandidate, ConfirmationResult
CLAUDE.md — Phase 5 goal; Required deliverables C
PROJECT_STATUS.md — Phase 5 section
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from signals.signal_types import ConfirmationResult, SignalCandidate

logger = logging.getLogger(__name__)

# Default number of bars required for strict multi-candle confirmation
_DEFAULT_STRICT_N = 2

# Required OHLCV columns
_REQUIRED_COLS = {"open", "high", "low", "close"}


# ── Public API ────────────────────────────────────────────────────────────────


def check_candle_direction(
    signal: SignalCandidate,
    ohlcv_slice: pd.DataFrame,
    missing_bar_count: int = 0,
) -> ConfirmationResult:
    """Check if the most recent bar closes in the direction consistent with bias.

    For a *long* signal: the last bar must close above its open (bullish bar),
    OR close above the midpoint of the entry region.
    For a *short* signal: the last bar must close below its open (bearish bar),
    OR close below the midpoint of the entry region.
    For a *neutral* signal: always returns passed=False with reason "neutral
    bias; candle_direction not applicable."

    Parameters
    ----------
    signal:
        The :class:`~signals.signal_types.SignalCandidate` being evaluated.
    ohlcv_slice:
        DataFrame with at minimum columns ``open``, ``high``, ``low``,
        ``close``.  Must not be empty.  The most recent (last) row is used.
    missing_bar_count:
        Number of missing bars in the dataset manifest.  When > 0, a note is
        added to the result metadata.

    Returns
    -------
    :class:`~signals.signal_types.ConfirmationResult`
    """
    check_name = "candle_direction"
    meta: Dict[str, Any] = {"missing_bar_count": missing_bar_count}

    if ohlcv_slice.empty or not _has_required_cols(ohlcv_slice):
        return ConfirmationResult(
            signal_id=signal.signal_id,
            check_name=check_name,
            passed=False,
            reason="OHLCV slice is empty or missing required columns.",
            metadata=meta,
        )

    if signal.bias == "neutral":
        return ConfirmationResult(
            signal_id=signal.signal_id,
            check_name=check_name,
            passed=False,
            reason="Neutral bias; candle_direction check not applicable.",
            metadata=meta,
        )

    last = ohlcv_slice.iloc[-1]
    last_open = float(last["open"])
    last_close = float(last["close"])
    mid = signal.entry_region.mid_price()

    meta.update({
        "bar_open": last_open,
        "bar_close": last_close,
        "entry_mid": mid,
    })

    if missing_bar_count > 0:
        meta["gap_note"] = (
            f"Dataset has {missing_bar_count} missing bar(s); "
            "result is noted but strict_multi_candle is required separately."
        )

    if signal.bias == "long":
        bullish_body = last_close > last_open
        above_mid = last_close > mid
        passed = bullish_body or above_mid
        reason = (
            f"Last bar close={last_close:.2f} {'>' if bullish_body else '<='} "
            f"open={last_open:.2f} (bullish={bullish_body}), "
            f"close {'>' if above_mid else '<='} entry_mid={mid:.2f}."
        )
    else:  # short
        bearish_body = last_close < last_open
        below_mid = last_close < mid
        passed = bearish_body or below_mid
        reason = (
            f"Last bar close={last_close:.2f} {'<' if bearish_body else '>='} "
            f"open={last_open:.2f} (bearish={bearish_body}), "
            f"close {'<' if below_mid else '>='} entry_mid={mid:.2f}."
        )

    return ConfirmationResult(
        signal_id=signal.signal_id,
        check_name=check_name,
        passed=passed,
        reason=reason,
        metadata=meta,
    )


def check_zone_rejection(
    signal: SignalCandidate,
    ohlcv_slice: pd.DataFrame,
    missing_bar_count: int = 0,
) -> ConfirmationResult:
    """Check if price visited the entry zone and rejected back in the bias direction.

    For a *long* signal: any bar in the slice must have its low <= entry
    zone's high (price touched or entered the zone) AND its close must be
    above the entry zone's low (closed back above the zone low — rejection).
    For a *short* signal: any bar must have its high >= entry zone's low AND
    its close must be below the entry zone's high.
    For *neutral*: always returns passed=False.

    Parameters
    ----------
    signal:
        The :class:`~signals.signal_types.SignalCandidate` being evaluated.
    ohlcv_slice:
        DataFrame with columns ``open``, ``high``, ``low``, ``close``.
    missing_bar_count:
        Number of missing bars.  When > 0, added to metadata.

    Returns
    -------
    :class:`~signals.signal_types.ConfirmationResult`
    """
    check_name = "zone_rejection"
    meta: Dict[str, Any] = {"missing_bar_count": missing_bar_count}

    if ohlcv_slice.empty or not _has_required_cols(ohlcv_slice):
        return ConfirmationResult(
            signal_id=signal.signal_id,
            check_name=check_name,
            passed=False,
            reason="OHLCV slice is empty or missing required columns.",
            metadata=meta,
        )

    if signal.bias == "neutral":
        return ConfirmationResult(
            signal_id=signal.signal_id,
            check_name=check_name,
            passed=False,
            reason="Neutral bias; zone_rejection check not applicable.",
            metadata=meta,
        )

    zone_lo = signal.entry_region.price_low
    zone_hi = signal.entry_region.price_high

    if missing_bar_count > 0:
        meta["gap_note"] = (
            f"Dataset has {missing_bar_count} missing bar(s); "
            "zone_rejection result may be less reliable."
        )

    rejection_bars: List[dict] = []

    for _, row in ohlcv_slice.iterrows():
        bar_high = float(row["high"])
        bar_low = float(row["low"])
        bar_close = float(row["close"])

        if signal.bias == "long":
            touched = bar_low <= zone_hi
            rejected = bar_close > zone_lo
            if touched and rejected:
                rejection_bars.append({
                    "low": bar_low,
                    "close": bar_close,
                    "zone_lo": zone_lo,
                    "zone_hi": zone_hi,
                })
        else:  # short
            touched = bar_high >= zone_lo
            rejected = bar_close < zone_hi
            if touched and rejected:
                rejection_bars.append({
                    "high": bar_high,
                    "close": bar_close,
                    "zone_lo": zone_lo,
                    "zone_hi": zone_hi,
                })

    passed = len(rejection_bars) > 0
    meta["rejection_bars_found"] = len(rejection_bars)
    if rejection_bars:
        meta["first_rejection_bar"] = rejection_bars[0]

    if passed:
        reason = (
            f"Found {len(rejection_bars)} bar(s) touching zone "
            f"[{zone_lo:.2f}, {zone_hi:.2f}] with {signal.bias} rejection."
        )
    else:
        reason = (
            f"No bar in the slice touched zone [{zone_lo:.2f}, {zone_hi:.2f}] "
            f"with a {signal.bias} rejection close."
        )

    return ConfirmationResult(
        signal_id=signal.signal_id,
        check_name=check_name,
        passed=passed,
        reason=reason,
        metadata=meta,
    )


def check_strict_multi_candle(
    signal: SignalCandidate,
    ohlcv_slice: pd.DataFrame,
    missing_bar_count: int = 0,
    n_required: int = _DEFAULT_STRICT_N,
) -> ConfirmationResult:
    """Require N consecutive bars all closing in the bias direction.

    Used when ``missing_bar_count > 0`` to compensate for data gaps.
    The check inspects the last ``n_required`` bars of ``ohlcv_slice``.

    For *long*: all N bars must close above their open (consecutive bullish).
    For *short*: all N bars must close below their open (consecutive bearish).
    For *neutral*: always returns passed=False.

    Parameters
    ----------
    signal:
        The :class:`~signals.signal_types.SignalCandidate` being evaluated.
    ohlcv_slice:
        DataFrame with columns ``open``, ``high``, ``low``, ``close``.
        Must have at least ``n_required`` rows.
    missing_bar_count:
        Number of missing bars.  Recorded in metadata.
    n_required:
        Minimum number of consecutive bars required.  Default 2.

    Returns
    -------
    :class:`~signals.signal_types.ConfirmationResult`
    """
    check_name = "strict_multi_candle"
    meta: Dict[str, Any] = {
        "missing_bar_count": missing_bar_count,
        "n_required": n_required,
    }

    if ohlcv_slice.empty or not _has_required_cols(ohlcv_slice):
        return ConfirmationResult(
            signal_id=signal.signal_id,
            check_name=check_name,
            passed=False,
            reason="OHLCV slice is empty or missing required columns.",
            metadata=meta,
        )

    if signal.bias == "neutral":
        return ConfirmationResult(
            signal_id=signal.signal_id,
            check_name=check_name,
            passed=False,
            reason="Neutral bias; strict_multi_candle check not applicable.",
            metadata=meta,
        )

    last_n = ohlcv_slice.tail(n_required)
    if len(last_n) < n_required:
        return ConfirmationResult(
            signal_id=signal.signal_id,
            check_name=check_name,
            passed=False,
            reason=(
                f"Insufficient bars: need {n_required}, got {len(last_n)}."
            ),
            metadata=meta,
        )

    bar_results: List[dict] = []
    for _, row in last_n.iterrows():
        bar_open = float(row["open"])
        bar_close = float(row["close"])
        if signal.bias == "long":
            ok = bar_close > bar_open
        else:
            ok = bar_close < bar_open
        bar_results.append({"open": bar_open, "close": bar_close, "ok": ok})

    all_pass = all(r["ok"] for r in bar_results)
    n_pass = sum(1 for r in bar_results if r["ok"])
    meta["bar_results"] = bar_results

    reason = (
        f"{n_pass}/{n_required} bars confirm {signal.bias} direction "
        f"({'PASS' if all_pass else 'FAIL'})."
    )

    return ConfirmationResult(
        signal_id=signal.signal_id,
        check_name=check_name,
        passed=all_pass,
        reason=reason,
        metadata=meta,
    )


def run_all_confirmations(
    signal: SignalCandidate,
    ohlcv_slice: pd.DataFrame,
    missing_bar_count: int = 0,
    strict_n: int = _DEFAULT_STRICT_N,
) -> List[ConfirmationResult]:
    """Run every confirmation check listed in ``signal.confirmations_required``.

    Parameters
    ----------
    signal:
        The :class:`~signals.signal_types.SignalCandidate` being evaluated.
    ohlcv_slice:
        Recent 6H OHLCV DataFrame.
    missing_bar_count:
        Passed to each check function.
    strict_n:
        Number of consecutive bars for the strict_multi_candle check.

    Returns
    -------
    List of :class:`~signals.signal_types.ConfirmationResult`, one per check
    in ``signal.confirmations_required``.  Unknown check names produce a
    ``passed=False`` result with a descriptive reason.
    """
    results: List[ConfirmationResult] = []

    _dispatch = {
        "candle_direction": lambda s, sl: check_candle_direction(s, sl, missing_bar_count),
        "zone_rejection": lambda s, sl: check_zone_rejection(s, sl, missing_bar_count),
        "strict_multi_candle": lambda s, sl: check_strict_multi_candle(
            s, sl, missing_bar_count, n_required=strict_n
        ),
    }

    for check_name in signal.confirmations_required:
        fn = _dispatch.get(check_name)
        if fn is None:
            results.append(ConfirmationResult(
                signal_id=signal.signal_id,
                check_name=check_name,
                passed=False,
                reason=f"Unknown check name: {check_name!r}.",
            ))
        else:
            results.append(fn(signal, ohlcv_slice))

    return results


# ── Helpers ───────────────────────────────────────────────────────────────────


def _has_required_cols(df: pd.DataFrame) -> bool:
    """Return True if the DataFrame has all required OHLCV columns."""
    return _REQUIRED_COLS.issubset(df.columns)
