"""
backtest/gating.py

Phase 7 — In-bar confirmation gating.

Provides a pure function that evaluates whether a signal's confirmation checks
pass at a given decision bar, using only data available up to (and including)
that bar.

Timing convention
-----------------
At bar *i* (the "triggering bar"), the close enters the entry region.
Confirmation checks are evaluated using bars ``[max(0, i - lookback + 1) ... i]``.
If all required confirmations pass, a trade entry is allowed at the **next bar's
open** (bar *i+1*).  This is identical to the existing ``next_bar_open``
execution model in Phase 6, with the addition that the confirmation gate is now
evaluated at bar *i* rather than assumed to have passed at signal generation time.

No lookahead is introduced: the gate sees only bars up to and including *i*.

Design rules
------------
- Pure function: same inputs → same output.
- No side effects, no state.
- Wraps ``signals.confirmations.run_all_confirmations``.
- Returns a structured :class:`GatingResult` (not a bare bool) for auditability.

References
----------
signals/confirmations.py — run_all_confirmations
signals/signal_types.py — SignalCandidate, ConfirmationResult
ASSUMPTIONS.md — Assumption 36 (retired in Phase 7)
PROJECT_STATUS.md — Phase 7 section
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pandas as pd

from signals.confirmations import run_all_confirmations
from signals.signal_types import ConfirmationResult, SignalCandidate

logger = logging.getLogger(__name__)

# Default lookback window for confirmation evaluation (number of 6H bars)
_DEFAULT_CONFIRMATION_LOOKBACK = 10


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class GatingResult:
    """Result of a confirmation gate evaluation at a specific decision bar.

    Fields
    ------
    signal_id : str
        ID of the signal being evaluated.
    bar_time : pd.Timestamp
        Timestamp of the triggering bar (bar *i*) at which the gate is evaluated.
    passed : bool
        True if all required confirmation checks passed; trade entry is allowed.
    confirmation_results : list[ConfirmationResult]
        Per-check results from ``run_all_confirmations``.
    n_required : int
        Number of checks required.
    n_passed : int
        Number of checks that passed.
    metadata : dict
        Extra audit information (lookback used, missing_bar_count, etc.).
    """

    signal_id: str
    bar_time: pd.Timestamp
    passed: bool
    confirmation_results: List[ConfirmationResult] = field(default_factory=list)
    n_required: int = 0
    n_passed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "bar_time": str(self.bar_time),
            "passed": self.passed,
            "n_required": self.n_required,
            "n_passed": self.n_passed,
            "check_names": [r.check_name for r in self.confirmation_results],
            "check_passed": [r.passed for r in self.confirmation_results],
            "check_reasons": [r.reason for r in self.confirmation_results],
            "metadata": self.metadata,
        }


# ── Public API ────────────────────────────────────────────────────────────────


def evaluate_confirmation_gate(
    signal: SignalCandidate,
    df_6h_up_to_bar: pd.DataFrame,
    missing_bar_count: int = 0,
    lookback: int = _DEFAULT_CONFIRMATION_LOOKBACK,
    strict_n: int = 2,
) -> GatingResult:
    """Evaluate all confirmation checks for ``signal`` using bars up to the
    triggering bar.

    Only data in ``df_6h_up_to_bar`` is used — no future bars are accessed.
    The function slices the last ``lookback`` bars to form the confirmation
    window.

    Parameters
    ----------
    signal:
        The :class:`~signals.signal_types.SignalCandidate` being evaluated.
    df_6h_up_to_bar:
        6H OHLCV DataFrame containing rows up to and including the triggering
        bar (bar *i*).  Must be sorted by index ascending.  Only the last
        ``lookback`` rows are used.
    missing_bar_count:
        Passed through to confirmation checks (from dataset manifest).
    lookback:
        Number of recent 6H bars to include in the confirmation window.
        Default is 10 (≈ 2.5 days of 6H bars).
    strict_n:
        Consecutive bars required for the ``strict_multi_candle`` check.

    Returns
    -------
    :class:`GatingResult` — structured result showing pass/fail per check.
    """
    bar_time = df_6h_up_to_bar.index[-1] if not df_6h_up_to_bar.empty else pd.NaT

    if df_6h_up_to_bar.empty:
        return GatingResult(
            signal_id=signal.signal_id,
            bar_time=bar_time,
            passed=False,
            metadata={"reason": "Empty OHLCV slice passed to gate."},
        )

    # Slice to the lookback window
    ohlcv_slice = df_6h_up_to_bar.iloc[-lookback:]

    confirmation_results = run_all_confirmations(
        signal=signal,
        ohlcv_slice=ohlcv_slice,
        missing_bar_count=missing_bar_count,
        strict_n=strict_n,
    )

    n_required = len(signal.confirmations_required)
    n_passed = sum(1 for r in confirmation_results if r.passed)
    all_passed = (n_required == 0) or (n_passed == n_required)

    meta: Dict[str, Any] = {
        "lookback": lookback,
        "missing_bar_count": missing_bar_count,
        "n_bars_in_slice": len(ohlcv_slice),
        "confirmations_required": list(signal.confirmations_required),
    }

    logger.debug(
        "Gate [%s] at %s: %d/%d checks passed → %s",
        signal.signal_id,
        bar_time,
        n_passed,
        n_required,
        "PASS" if all_passed else "FAIL",
    )

    return GatingResult(
        signal_id=signal.signal_id,
        bar_time=bar_time,
        passed=all_passed,
        confirmation_results=confirmation_results,
        n_required=n_required,
        n_passed=n_passed,
        metadata=meta,
    )
