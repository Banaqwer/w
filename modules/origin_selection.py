"""
modules/origin_selection.py

Origin selection module — Phase 2.

Identifies structurally important origin highs and lows from a processed OHLCV
DataFrame.  An origin is a candidate anchor for impulse detection; it is a pivot
point that a later module will pair with an extreme to form an Impulse.

Two detectors are provided and are both configurable:

1. **N-bar pivot** (``"pivot"``)
   A bar is a pivot-high if its ``high`` is strictly greater than the ``high``
   of every bar within ``n`` bars before and after it (configurable by
   ``pivot_n``).  A pivot-low uses ``low`` with the same rule.

2. **Percent-threshold zigzag** (``"zigzag"``)
   Traverses the bar series and records a swing reversal when price moves at
   least ``threshold_pct`` percent (or ``threshold_atr`` ATR multiples when
   ATR-based mode is selected) away from the last recorded extreme.

Both detectors return a list of :class:`Origin` objects sorted ascending by
``origin_time``.

Assumptions recorded in ASSUMPTIONS.md (Phase 2, Assumptions 19–23).

References
----------
CLAUDE.md — Rule 4 (no silent simplifications), Rule 6 (reproducibility)
docs/handoff/jenkins_quant_python_blueprint.md — Section 3 (pivot engine)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Data contract ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Origin:
    """A structurally important pivot candidate.

    Fields
    ------
    origin_time : pd.Timestamp
        UTC timestamp of the bar that constitutes this origin.
    origin_price : float
        Canonical price for this origin.  For a pivot-high this is ``high``; for
        a pivot-low this is ``low``; for a zigzag this is the close of the
        extreme bar (configurable via ``zigzag_price_field``).
    bar_index : int
        ``bar_index`` value from the processed dataset (0-based).
    origin_type : str
        ``"high"`` or ``"low"``.
    detector_name : str
        Name of the detector that produced this origin, e.g. ``"pivot_n5"`` or
        ``"zigzag_pct3.0"``.
    quality_score : float
        A [0, 1] structural-importance score.  For the pivot detector this is
        the normalised prominence (bar-range vs. ATR); for the zigzag detector
        it is the swing magnitude divided by the median ATR.  The score is
        informational; it does not gate origin acceptance.
    """

    origin_time: pd.Timestamp
    origin_price: float
    bar_index: int
    origin_type: str  # "high" | "low"
    detector_name: str
    quality_score: float


# ── Public API ─────────────────────────────────────────────────────────────


def detect_pivot_origins(
    df: pd.DataFrame,
    n: int = 5,
    atr_warmup_rows: int = 14,
    min_quality: float = 0.0,
) -> List[Origin]:
    """Detect pivot-high and pivot-low origins using the N-bar rule.

    A bar at index *i* is a **pivot-high** if:
        ``high[i] > high[j]`` for all *j* in ``[i-n, i-1]`` ∪ ``[i+1, i+n]``

    An analogous rule applies for **pivot-low** using ``low``.  Bars within the
    first/last ``n`` rows of the dataset cannot be pivots (insufficient context)
    and are silently skipped.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame.  Must include columns: ``timestamp``,
        ``high``, ``low``, ``bar_index``.  An ``atr_14`` column is used to
        compute ``quality_score`` when present; if absent, quality is 0.
    n:
        Look-back and look-forward window size in bars (must be ≥ 1).
    atr_warmup_rows:
        Number of leading rows with unreliable ATR values (excluded from the
        quality-score median calculation).
    min_quality:
        Discard origins whose ``quality_score`` is strictly below this value.
        Default 0.0 keeps all origins.

    Returns
    -------
    List of :class:`Origin` objects sorted ascending by ``origin_time``.

    Notes
    -----
    - Assumption 19: For the pivot detector, bars exactly tied in high/low with
      the pivot bar are treated as non-pivot (strict greater-than comparison).
      This preserves determinism on flat-top / flat-bottom structures.
    - Assumption 20: Quality score is clipped to [0, 1].
    """
    _require_columns(df, ["timestamp", "high", "low", "bar_index"])
    if n < 1:
        raise ValueError(f"pivot n must be >= 1, got {n}")

    detector_name = f"pivot_n{n}"
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    timestamps = pd.to_datetime(df["timestamp"].values, utc=True)
    bar_indices = df["bar_index"].to_numpy()

    median_atr = _get_median_atr(df, atr_warmup_rows)

    origins: List[Origin] = []

    for i in range(n, len(df) - n):
        window_before = slice(i - n, i)
        window_after = slice(i + 1, i + n + 1)

        # Pivot high
        if highs[i] > highs[window_before].max() and highs[i] > highs[window_after].max():
            prominence = highs[i] - max(highs[window_before].max(), highs[window_after].max())
            quality = _quality_from_prominence(prominence, median_atr)
            if quality >= min_quality:
                origins.append(
                    Origin(
                        origin_time=timestamps[i],
                        origin_price=float(highs[i]),
                        bar_index=int(bar_indices[i]),
                        origin_type="high",
                        detector_name=detector_name,
                        quality_score=quality,
                    )
                )

        # Pivot low
        if lows[i] < lows[window_before].min() and lows[i] < lows[window_after].min():
            prominence = min(lows[window_before].min(), lows[window_after].min()) - lows[i]
            quality = _quality_from_prominence(prominence, median_atr)
            if quality >= min_quality:
                origins.append(
                    Origin(
                        origin_time=timestamps[i],
                        origin_price=float(lows[i]),
                        bar_index=int(bar_indices[i]),
                        origin_type="low",
                        detector_name=detector_name,
                        quality_score=quality,
                    )
                )

    origins.sort(key=lambda o: o.origin_time)
    logger.info(
        "detect_pivot_origins: detector=%s  n=%d  found=%d origins",
        detector_name,
        n,
        len(origins),
    )
    return origins


def detect_zigzag_origins(
    df: pd.DataFrame,
    threshold_pct: Optional[float] = 3.0,
    threshold_atr: Optional[float] = None,
    atr_warmup_rows: int = 14,
    zigzag_price_field: str = "close",
) -> List[Origin]:
    """Detect zigzag swing-high and swing-low origins.

    Traverses the bar series and records a reversal when price moves at least
    ``threshold_pct`` percent (or ``threshold_atr`` ATR multiples) from the
    last confirmed extreme.  Exactly one of ``threshold_pct`` or
    ``threshold_atr`` must be supplied; if both are supplied,
    ``threshold_atr`` takes precedence.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame.  Must include columns: ``timestamp``,
        ``high``, ``low``, ``close``, ``bar_index``.
    threshold_pct:
        Minimum reversal magnitude as a percentage of the last extreme price.
        Ignored when ``threshold_atr`` is provided.
    threshold_atr:
        Minimum reversal magnitude as a multiple of the current bar's ATR.
        Requires ``atr_14`` column in ``df``.  When provided, this takes
        precedence over ``threshold_pct``.
    atr_warmup_rows:
        Number of leading rows to skip (unreliable ATR during warm-up).
    zigzag_price_field:
        Column used to identify the extreme price at the pivot bar.  Defaults
        to ``"close"``; ``"high"``/``"low"`` are also valid.

    Returns
    -------
    List of :class:`Origin` objects sorted ascending by ``origin_time``.

    Notes
    -----
    - Assumption 21: The zigzag uses ``high`` for the running peak and ``low``
      for the running trough to detect reversals, regardless of
      ``zigzag_price_field``.  The field only governs the stored
      ``origin_price``.
    - Assumption 22: The first bar is used as the initial anchor.  If ATR mode
      is selected, bars within ``atr_warmup_rows`` cannot trigger a reversal
      (insufficient ATR data) and are skipped.
    - Assumption 23: When ATR threshold is used, the ATR value of the reversal
      bar itself is used as the threshold reference; NaN ATR causes the bar to
      be skipped silently.
    """
    _require_columns(df, ["timestamp", "high", "low", "close", "bar_index"])

    use_atr_mode = threshold_atr is not None
    if use_atr_mode:
        _require_columns(df, ["atr_14"])
        detector_name = f"zigzag_atr{threshold_atr}"
    else:
        if threshold_pct is None or threshold_pct <= 0:
            raise ValueError("threshold_pct must be a positive number when threshold_atr is None")
        detector_name = f"zigzag_pct{threshold_pct}"

    price_col = zigzag_price_field
    if price_col not in df.columns:
        raise ValueError(f"zigzag_price_field='{price_col}' not found in DataFrame columns")

    timestamps = pd.to_datetime(df["timestamp"].values, utc=True)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    prices = df[price_col].to_numpy(dtype=float)
    bar_indices = df["bar_index"].to_numpy()
    if use_atr_mode:
        atrs = df["atr_14"].to_numpy(dtype=float)
    else:
        atrs = np.full(len(df), np.nan)

    median_atr = _get_median_atr(df, atr_warmup_rows)
    start_row = atr_warmup_rows if use_atr_mode else 0

    if len(df) < start_row + 2:
        logger.warning("detect_zigzag_origins: not enough bars after warm-up; returning empty list")
        return []

    # ── Zigzag state machine ────────────────────────────────────────────
    # direction: +1 = currently searching for a higher high (last confirmed was a low)
    #            -1 = currently searching for a lower low  (last confirmed was a high)
    # We start by checking both directions from bar start_row.
    raw_pivots: List[tuple] = []  # (bar_row, origin_type)

    anchor_row = start_row
    anchor_high = highs[anchor_row]
    anchor_low = lows[anchor_row]
    # Determine initial direction from first two bars
    direction = 1 if highs[start_row + 1] > highs[start_row] else -1

    running_extreme_row = anchor_row
    running_extreme_val = anchor_high if direction == -1 else anchor_low

    for i in range(start_row + 1, len(df)):
        if use_atr_mode:
            atr_val = atrs[i]
            if np.isnan(atr_val):
                continue
            threshold_val = threshold_atr * atr_val
        else:
            threshold_val = abs(running_extreme_val) * (threshold_pct / 100.0)

        if direction == 1:
            # Searching for a higher high
            if highs[i] > running_extreme_val:
                running_extreme_row = i
                running_extreme_val = highs[i]
            elif running_extreme_val - lows[i] >= threshold_val:
                # Reversal confirmed — record the prior high
                raw_pivots.append((running_extreme_row, "high"))
                direction = -1
                running_extreme_row = i
                running_extreme_val = lows[i]
        else:
            # Searching for a lower low
            if lows[i] < running_extreme_val:
                running_extreme_row = i
                running_extreme_val = lows[i]
            elif highs[i] - running_extreme_val >= threshold_val:
                # Reversal confirmed — record the prior low
                raw_pivots.append((running_extreme_row, "low"))
                direction = 1
                running_extreme_row = i
                running_extreme_val = highs[i]

    # Record the final unconfirmed extreme as a tentative origin
    # (it has no confirming reversal yet, so quality_score is penalised)
    last_recorded_row = raw_pivots[-1][0] if raw_pivots else -1
    if running_extreme_row != last_recorded_row:
        raw_pivots.append((running_extreme_row, "high" if direction == 1 else "low"))

    origins: List[Origin] = []
    for pivot_idx, (row_idx, otype) in enumerate(raw_pivots):
        origin_price = float(prices[row_idx])
        if pivot_idx > 0:
            prior_price = float(prices[raw_pivots[pivot_idx - 1][0]])
        else:
            prior_price = origin_price
        swing_magnitude = abs(origin_price - prior_price)
        quality = _quality_from_prominence(swing_magnitude, median_atr)
        origins.append(
            Origin(
                origin_time=timestamps[row_idx],
                origin_price=origin_price,
                bar_index=int(bar_indices[row_idx]),
                origin_type=otype,
                detector_name=detector_name,
                quality_score=quality,
            )
        )

    origins.sort(key=lambda o: o.origin_time)
    logger.info(
        "detect_zigzag_origins: detector=%s  found=%d origins",
        detector_name,
        len(origins),
    )
    return origins


def select_origins(
    df: pd.DataFrame,
    method: str = "pivot",
    pivot_n: int = 5,
    threshold_pct: float = 3.0,
    threshold_atr: Optional[float] = None,
    atr_warmup_rows: int = 14,
    min_quality: float = 0.0,
    zigzag_price_field: str = "close",
) -> List[Origin]:
    """Unified entry-point: dispatch to the requested detector.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame.
    method:
        ``"pivot"`` or ``"zigzag"``.
    pivot_n:
        Pivot look-back/look-forward window (used only when method=``"pivot"``).
    threshold_pct:
        Zigzag percent threshold (used only when method=``"zigzag"`` and
        ``threshold_atr`` is None).
    threshold_atr:
        Zigzag ATR-multiple threshold (used only when method=``"zigzag"``).
        When provided, overrides ``threshold_pct``.
    atr_warmup_rows:
        Leading rows to skip.
    min_quality:
        Discard origins below this quality score.
    zigzag_price_field:
        Price field for zigzag origin_price storage.

    Returns
    -------
    List of :class:`Origin` objects sorted ascending by ``origin_time``.

    Raises
    ------
    ValueError
        If ``method`` is not ``"pivot"`` or ``"zigzag"``.
    """
    if method == "pivot":
        return detect_pivot_origins(
            df,
            n=pivot_n,
            atr_warmup_rows=atr_warmup_rows,
            min_quality=min_quality,
        )
    if method == "zigzag":
        return detect_zigzag_origins(
            df,
            threshold_pct=threshold_pct,
            threshold_atr=threshold_atr,
            atr_warmup_rows=atr_warmup_rows,
            zigzag_price_field=zigzag_price_field,
        )
    raise ValueError(f"Unknown origin selection method: '{method}'. Use 'pivot' or 'zigzag'.")


# ── Private helpers ────────────────────────────────────────────────────────


def _require_columns(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _get_median_atr(df: pd.DataFrame, atr_warmup_rows: int) -> float:
    """Return median ATR from valid rows, or NaN if column absent."""
    if "atr_14" not in df.columns:
        return float("nan")
    valid = df["atr_14"].iloc[atr_warmup_rows:].dropna()
    if valid.empty:
        return float("nan")
    return float(valid.median())


def _quality_from_prominence(prominence: float, median_atr: float) -> float:
    """Convert a price prominence to a [0, 1] quality score.

    Quality is ``prominence / (3 * median_atr)`` clipped to [0, 1].
    A prominence equal to 3× the median ATR receives a quality of 1.0.
    If ATR is not available (NaN), quality is 0.5 as a neutral placeholder.
    """
    if np.isnan(median_atr) or median_atr <= 0:
        return 0.5
    raw = prominence / (3.0 * median_atr)
    return float(np.clip(raw, 0.0, 1.0))
