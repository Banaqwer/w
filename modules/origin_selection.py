"""
modules/origin_selection.py

Origin selection: identifies structurally important swing highs and swing lows
that serve as candidate impulse origins for Phase 2 impulse detection.

Two detector methods are provided:

  1. ``"pivot"`` — N-bar fractal pivot: a bar ``i`` is a swing high (low) if
     its high (low) is **strictly** greater (less) than all other highs (lows)
     in the symmetric window ``[i - n_bars, i + n_bars]``.

  2. ``"zigzag"`` — Threshold reversal: price must reverse by at least
     ``reversal_pct`` percent (or ``atr_mult`` × ATR) from the running extreme
     before that extreme is confirmed as an origin.

Both methods are deterministic and reproducible from any fixed processed dataset.

Outputs a list of :class:`Origin` objects.  The caller converts to DataFrame
via :func:`origins_to_dataframe` for CSV export.

References
----------
CLAUDE.md — Phase 2 goal, Required deliverables A
docs/handoff/jenkins_quant_prd.md — §Origin selection
ASSUMPTIONS.md — Assumption 18 (6H gap handling)
DECISIONS.md — 2026-03-06 Phase 2 gap policy
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Literal, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Data model ───────────────────────────────────────────────────────────────


@dataclass
class Origin:
    """A structurally significant price origin (swing high or swing low).

    Fields
    ------
    origin_time : pd.Timestamp
        UTC timestamp of the origin bar.
    origin_price : float
        Price at the origin.  High for swing-high origins; low for swing-low.
    origin_type : str
        ``"high"`` or ``"low"``.
    detector_name : str
        Name of the method that produced this origin.
    quality_score : float
        Normalised score in [0.0, 1.0] representing structural significance.
        For pivot: ATR-normalised pivot amplitude.
        For zigzag: fixed 1.0 (threshold itself defines minimum significance).
    bar_index : int
        Zero-based bar index from the processed dataset ``bar_index`` column.
        Used by downstream impulse detection and gap-crossing checks.
    """

    origin_time: pd.Timestamp
    origin_price: float
    origin_type: str        # "high" or "low"
    detector_name: str
    quality_score: float
    bar_index: int

    def to_dict(self) -> dict:
        return {
            "origin_time": self.origin_time,
            "origin_price": self.origin_price,
            "origin_type": self.origin_type,
            "detector_name": self.detector_name,
            "quality_score": self.quality_score,
            "bar_index": self.bar_index,
        }


# ── Pivot detector ───────────────────────────────────────────────────────────


def detect_pivots(
    df: pd.DataFrame,
    n_bars: int = 5,
    atr_col: str = "atr_14",
) -> List[Origin]:
    """Detect swing-high and swing-low pivots using an N-bar fractal rule.

    A bar ``i`` is a **swing high** if ``high[i]`` is strictly greater than
    every other high in the symmetric window ``[i - n_bars, i + n_bars]``.
    A bar ``i`` is a **swing low** if ``low[i]`` is strictly less than every
    other low in the same window.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame with ``bar_index``, ``high``, ``low``, and
        optionally an ATR column used for quality scoring.
    n_bars:
        Half-window size.  A window of ``2 * n_bars`` surrounding bars is
        checked.  Default is 5 (10 surrounding bars).
    atr_col:
        ATR column name for quality scoring.  If the column is absent or the
        ATR value is NaN at a pivot bar, quality defaults to 0.5.

    Returns
    -------
    List of :class:`Origin` objects sorted by ``bar_index`` ascending.

    Notes
    -----
    - The first and last ``n_bars`` rows are excluded (insufficient lookback /
      lookahead); they cannot be confirmed pivots.
    - A quality score of 1.0 is assigned when the pivot amplitude (distance
      from pivot price to opposite window extreme) is ≥ 3 × ATR; 0.0 when it
      is ≤ 0.5 × ATR.  Linear interpolation between these bounds.
    - Ties (two bars with identical high or low in the window) are resolved by
      requiring strict inequality: only the bar whose value exceeds *all*
      neighbours is a pivot.  Both bars in a tie are skipped.
    """
    _require_ohlc(df)
    _require_bar_index(df)

    n = len(df)
    if n < 2 * n_bars + 1:
        logger.warning(
            "detect_pivots: DataFrame has %d rows, fewer than 2*n_bars+1=%d. "
            "No pivots can be detected.",
            n,
            2 * n_bars + 1,
        )
        return []

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    bar_indices = df["bar_index"].to_numpy(dtype=np.int64)
    ts = _get_timestamps(df)

    has_atr = atr_col in df.columns
    atr_values = df[atr_col].to_numpy(dtype=float) if has_atr else None

    origins: List[Origin] = []

    for i in range(n_bars, n - n_bars):
        # Exclude bar i itself when computing the comparison window.
        surrounding_highs = np.concatenate(
            [highs[i - n_bars : i], highs[i + 1 : i + n_bars + 1]]
        )
        surrounding_lows = np.concatenate(
            [lows[i - n_bars : i], lows[i + 1 : i + n_bars + 1]]
        )

        # Swing high: strictly greater than all surrounding highs.
        if highs[i] > np.max(surrounding_highs):
            price = float(highs[i])
            qs = _pivot_quality(
                price, surrounding_lows, atr_values, i, kind="high"
            )
            origins.append(
                Origin(
                    origin_time=ts[i],
                    origin_price=price,
                    origin_type="high",
                    detector_name=f"pivot_n{n_bars}",
                    quality_score=qs,
                    bar_index=int(bar_indices[i]),
                )
            )

        # Swing low: strictly less than all surrounding lows.
        if lows[i] < np.min(surrounding_lows):
            price = float(lows[i])
            qs = _pivot_quality(
                price, surrounding_highs, atr_values, i, kind="low"
            )
            origins.append(
                Origin(
                    origin_time=ts[i],
                    origin_price=price,
                    origin_type="low",
                    detector_name=f"pivot_n{n_bars}",
                    quality_score=qs,
                    bar_index=int(bar_indices[i]),
                )
            )

    origins.sort(key=lambda o: o.bar_index)
    logger.info(
        "detect_pivots: found %d origins (n_bars=%d)", len(origins), n_bars
    )
    return origins


# ── ZigZag detector ──────────────────────────────────────────────────────────


def detect_zigzag(
    df: pd.DataFrame,
    reversal_pct: float = 20.0,
    atr_col: Optional[str] = None,
    atr_mult: float = 3.0,
) -> List[Origin]:
    """Detect swing highs and lows using a threshold reversal (zigzag) rule.

    The algorithm tracks price in one direction (up or down) until a reversal
    of at least ``reversal_pct`` percent occurs relative to the running extreme.
    When the reversal is confirmed, the previous extreme is recorded as an
    :class:`Origin` and tracking switches direction.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame with ``bar_index``, ``high``, and ``low``.
    reversal_pct:
        Minimum percentage reversal to confirm a new direction.
        **This is a percentage value (e.g. ``20.0`` means 20 %), not a fraction.**
        Default is 20.0 %.
    atr_col:
        If provided and present in *df*, the ATR-based threshold
        ``atr_mult * atr / extreme_price`` replaces the fixed-percentage
        threshold when the ATR value is non-NaN.
    atr_mult:
        Multiplier applied to ATR when *atr_col* is set.

    Returns
    -------
    List of :class:`Origin` objects sorted by ``bar_index`` ascending.

    Notes
    -----
    - Initialization: the algorithm starts in the ``"up"`` direction with the
      first bar's high as the initial extreme.  This means the first confirmed
      origin will be either: (a) the initial high, once price falls by
      ``reversal_pct`` from it; or (b) a new high produced when price first
      reverses upward after falling.  The very first bar's low is only
      recorded as an origin if the initial high at bar 0 triggers the first
      reversal.  This is a documented approximation (ASSUMPTIONS.md).
    - All zigzag origins receive ``quality_score = 1.0``.  The threshold
      parameter itself defines the minimum significance level.
    - When *atr_col* is given and a bar's ATR is NaN (warm-up rows), the
      percentage-based threshold is used as fallback.
    """
    _require_ohlc(df)
    _require_bar_index(df)

    n = len(df)
    if n < 3:
        return []

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    bar_indices = df["bar_index"].to_numpy(dtype=np.int64)
    ts = _get_timestamps(df)

    use_atr = atr_col is not None and atr_col in df.columns
    atr_arr = df[atr_col].to_numpy(dtype=float) if use_atr else None

    origins: List[Origin] = []

    # Start in "up" direction, tracking the high from bar 0.
    direction = 1          # 1=up (tracking running max high), -1=down (running min low)
    extreme_price = float(highs[0])
    extreme_idx = 0

    for i in range(1, n):
        if direction == 1:
            if highs[i] >= extreme_price:
                # New high: extend the current upswing.
                extreme_price = float(highs[i])
                extreme_idx = i
            else:
                # Check for downward reversal from the running high.
                threshold = _zigzag_threshold(
                    extreme_price, reversal_pct, use_atr, atr_arr, i, atr_mult
                )
                if extreme_price > 0 and (extreme_price - lows[i]) / extreme_price >= threshold:
                    origins.append(
                        Origin(
                            origin_time=ts[extreme_idx],
                            origin_price=extreme_price,
                            origin_type="high",
                            detector_name=f"zigzag_pct{reversal_pct}",
                            quality_score=1.0,
                            bar_index=int(bar_indices[extreme_idx]),
                        )
                    )
                    direction = -1
                    extreme_price = float(lows[i])
                    extreme_idx = i
        else:  # direction == -1
            if lows[i] <= extreme_price:
                # New low: extend the current downswing.
                extreme_price = float(lows[i])
                extreme_idx = i
            else:
                # Check for upward reversal from the running low.
                threshold = _zigzag_threshold(
                    extreme_price, reversal_pct, use_atr, atr_arr, i, atr_mult
                )
                if extreme_price > 0 and (highs[i] - extreme_price) / extreme_price >= threshold:
                    origins.append(
                        Origin(
                            origin_time=ts[extreme_idx],
                            origin_price=extreme_price,
                            origin_type="low",
                            detector_name=f"zigzag_pct{reversal_pct}",
                            quality_score=1.0,
                            bar_index=int(bar_indices[extreme_idx]),
                        )
                    )
                    direction = 1
                    extreme_price = float(highs[i])
                    extreme_idx = i

    origins.sort(key=lambda o: o.bar_index)
    logger.info(
        "detect_zigzag: found %d origins (reversal_pct=%.1f%%)",
        len(origins),
        reversal_pct,
    )
    return origins


# ── Public unified API ───────────────────────────────────────────────────────


def select_origins(
    df: pd.DataFrame,
    method: Literal["pivot", "zigzag"] = "pivot",
    **kwargs,
) -> List[Origin]:
    """Select structurally important origins from a processed OHLCV DataFrame.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame.
    method:
        ``"pivot"`` (N-bar fractal) or ``"zigzag"`` (threshold reversal).
    **kwargs:
        Passed through to the selected detector.

    Returns
    -------
    List of :class:`Origin` objects sorted by ``bar_index`` ascending.

    Raises
    ------
    ValueError
        If *method* is not ``"pivot"`` or ``"zigzag"``.
    """
    if method == "pivot":
        return detect_pivots(df, **kwargs)
    if method == "zigzag":
        return detect_zigzag(df, **kwargs)
    raise ValueError(
        f"Unknown origin selection method: '{method}'. Use 'pivot' or 'zigzag'."
    )


def origins_to_dataframe(origins: List[Origin]) -> pd.DataFrame:
    """Convert a list of Origins to a DataFrame for export or inspection."""
    if not origins:
        return pd.DataFrame(
            columns=[
                "origin_time",
                "origin_price",
                "origin_type",
                "detector_name",
                "quality_score",
                "bar_index",
            ]
        )
    return pd.DataFrame([o.to_dict() for o in origins])


# ── Private helpers ──────────────────────────────────────────────────────────


def _require_ohlc(df: pd.DataFrame) -> None:
    required = {"high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")


def _require_bar_index(df: pd.DataFrame) -> None:
    if "bar_index" not in df.columns:
        raise ValueError(
            "DataFrame must have a 'bar_index' column. "
            "Run core.coordinate_system.build_coordinate_system first."
        )


def _get_timestamps(df: pd.DataFrame) -> list:
    """Return a list of UTC-aware Timestamps from the DataFrame."""
    if "timestamp" in df.columns:
        return list(pd.to_datetime(df["timestamp"], utc=True))
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        return list(idx)
    raise ValueError(
        "DataFrame must have a 'timestamp' column or a DatetimeIndex."
    )


def _pivot_quality(
    price: float,
    surrounding_opposing: np.ndarray,
    atr_values: Optional[np.ndarray],
    idx: int,
    kind: str,
) -> float:
    """Compute a quality score in [0.0, 1.0] for a pivot.

    The score is the ratio of the pivot's amplitude (distance from the pivot
    price to the most extreme opposing value in the window) to 3 × ATR.
    Scores below 0.5 × ATR → 0.0; above 3 × ATR → 1.0; linear between.
    """
    if atr_values is None:
        return 0.5

    atr = float(atr_values[idx])
    if np.isnan(atr) or atr <= 0:
        return 0.5

    if kind == "high":
        opposing_extreme = float(np.min(surrounding_opposing))
    else:
        opposing_extreme = float(np.max(surrounding_opposing))

    amplitude = abs(price - opposing_extreme)

    low_thresh = 0.5 * atr
    high_thresh = 3.0 * atr

    if amplitude <= low_thresh:
        return 0.0
    if amplitude >= high_thresh:
        return 1.0
    return (amplitude - low_thresh) / (high_thresh - low_thresh)


def _zigzag_threshold(
    current_extreme: float,
    reversal_pct: float,
    use_atr: bool,
    atr_arr: Optional[np.ndarray],
    idx: int,
    atr_mult: float,
) -> float:
    """Return the fractional reversal threshold for zigzag detection."""
    if use_atr and atr_arr is not None and idx < len(atr_arr):
        atr = float(atr_arr[idx])
        if not np.isnan(atr) and atr > 0 and current_extreme > 0:
            return atr_mult * atr / current_extreme
    return reversal_pct / 100.0
