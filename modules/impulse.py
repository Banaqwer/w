"""
modules/impulse.py

Impulse detection module — Phase 2.

An impulse is a directed price-time move from an origin (a structurally
important pivot) to its subsequent extreme (the highest high or lowest low
reached before the market reverses significantly or the dataset ends).

This module accepts a processed OHLCV DataFrame and a list of
:class:`~modules.origin_selection.Origin` objects.  For each origin it searches
forward for the extreme that defines the impulse endpoint, then packages the
result as an :class:`Impulse` object.

Gap handling for 6H data
------------------------
The 6H processed dataset may contain 1 or more missing bars (see
``DECISIONS.md`` 2026-03-06 and ``ASSUMPTIONS.md`` Assumption 18).  The module
handles this by checking the bar_index gap within each search window:

  * If ``skip_on_gap=True`` (default): any search window that crosses a gap
    (i.e. a ``bar_index`` increment > 1 between consecutive rows in the window)
    is excluded.  The impulse is not produced for that origin.
  * If ``skip_on_gap=False``: gaps are ignored; the window is treated as
    continuous.  This is valid for 1D data where ``missing_bar_count == 0``.

Downstream callers should read the manifest's ``missing_bar_count`` field and
pass ``skip_on_gap=True`` whenever it is > 0.

Slope fields
------------
``slope_raw`` is the raw price-per-bar slope: ``delta_p / delta_t``.
``slope_log`` is the log-price slope: ``(log_extreme - log_origin) / delta_t``.
Both are computed using bar-count (not calendar days) as the time unit, per the
coordinate system contract in ``core/coordinate_system.py``.

Angle-basis scaling is deferred to Phase 3 (``adjusted_angles`` module).
The slope fields here are raw; no ATR normalisation is applied at this stage.

References
----------
CLAUDE.md — Required objects spec (Impulse fields)
core/coordinate_system.py — coordinate system contract
modules/origin_selection.py — Origin dataclass
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from modules.origin_selection import Origin

logger = logging.getLogger(__name__)

# ── Data contract ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Impulse:
    """A directional structural impulse from origin to extreme.

    Fields match the Phase 0 specification in CLAUDE.md §Required objects.

    Fields
    ------
    impulse_id : str
        Unique identifier: ``"<detector_name>_<origin_bar_index>"``.
    origin_time : pd.Timestamp
        UTC timestamp of the origin bar.
    origin_price : float
        Price at the origin (high for a bearish impulse, low for a bullish one).
    extreme_time : pd.Timestamp
        UTC timestamp of the bar where the extreme was reached.
    extreme_price : float
        Price at the extreme (highest high for a bullish impulse, lowest low
        for a bearish one).
    origin_bar_index : int
        ``bar_index`` of the origin bar in the processed dataset.
    extreme_bar_index : int
        ``bar_index`` of the extreme bar in the processed dataset.
    delta_t : int
        Number of bars from origin to extreme (positive).
    delta_p : float
        Price change from origin to extreme (positive = upward impulse).
    slope_raw : float
        ``delta_p / delta_t`` — raw price-per-bar slope.
    slope_log : float
        ``(log(extreme_price) - log(origin_price)) / delta_t`` — log-price
        slope.  Undefined (NaN) if either price is ≤ 0.
    direction : str
        ``"up"`` or ``"down"``.
    quality_score : float
        Structural importance score in [0, 1].  Derived from the origin's
        quality score and the impulse magnitude vs. median ATR.
    detector_name : str
        Detector that produced the origin (e.g. ``"pivot_n5"``).
    gap_in_window : bool
        ``True`` if the search window contained a bar_index gap.  Only set
        when ``skip_on_gap=False``; always ``False`` when ``skip_on_gap=True``.
    """

    impulse_id: str
    origin_time: pd.Timestamp
    origin_price: float
    extreme_time: pd.Timestamp
    extreme_price: float
    origin_bar_index: int
    extreme_bar_index: int
    delta_t: int
    delta_p: float
    slope_raw: float
    slope_log: float
    direction: str
    quality_score: float
    detector_name: str
    gap_in_window: bool


# ── Public API ─────────────────────────────────────────────────────────────


def detect_impulses(
    df: pd.DataFrame,
    origins: List[Origin],
    max_lookahead_bars: int = 200,
    reversal_pct: float = 20.0,
    skip_on_gap: bool = True,
    atr_warmup_rows: int = 14,
    min_delta_t: int = 2,
    min_delta_p_pct: float = 0.5,
) -> List[Impulse]:
    """Detect impulses from a list of origins in a processed OHLCV DataFrame.

    For each origin the algorithm:
    1. Determines direction from origin_type (``"low"`` → bullish / upward;
       ``"high"`` → bearish / downward).
    2. Searches forward up to ``max_lookahead_bars`` bars.
    3. Tracks the running extreme (highest high for up; lowest low for down).
    4. Terminates the search early if price reverses by ``reversal_pct``
       percent from the running extreme back toward the origin.
    5. If ``skip_on_gap=True`` and a bar_index gap is detected inside the
       window, the origin is skipped (no Impulse produced).
    6. Packages the result as an :class:`Impulse` if ``delta_t ≥ min_delta_t``
       and ``|delta_p| / origin_price ≥ min_delta_p_pct / 100``.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame with columns: ``timestamp``, ``open``,
        ``high``, ``low``, ``close``, ``bar_index``.
    origins:
        List of :class:`~modules.origin_selection.Origin` objects.  Origins
        whose ``bar_index`` is not found in ``df`` are silently skipped.
    max_lookahead_bars:
        Maximum number of bars to search forward from each origin.
    reversal_pct:
        Early-stop threshold: if price reverses by this percentage from the
        running extreme, the search ends and the current extreme is frozen.
    skip_on_gap:
        If ``True``, skip any origin whose forward search window crosses a
        bar_index gap (increment > 1).  Recommended for 6H data with
        ``missing_bar_count > 0``.
    atr_warmup_rows:
        Leading rows with unreliable ATR; used for quality-score computation.
    min_delta_t:
        Minimum bar distance; impulses shorter than this are discarded.
    min_delta_p_pct:
        Minimum impulse magnitude as a percentage of origin price.  Impulses
        smaller than this are discarded.

    Returns
    -------
    List of :class:`Impulse` objects sorted ascending by ``origin_time``.

    Notes
    -----
    - Assumption 24: The extreme is defined as the highest ``high`` (for an
      upward impulse) or lowest ``low`` (for a downward impulse) within the
      look-ahead window, subject to early reversal stopping.
    - Assumption 25: When multiple origins share the same bar_index, each
      produces an independent Impulse (one per origin).
    - Assumption 26: If the origin bar_index falls outside the DataFrame's
      bar_index range, the origin is silently skipped and a warning is logged.
    """
    _require_columns(df, ["timestamp", "high", "low", "bar_index"])

    # Build a bar_index → row-position lookup for O(1) access
    bi_to_row = {int(bi): row for row, bi in enumerate(df["bar_index"].to_numpy())}

    timestamps = pd.to_datetime(df["timestamp"].values, utc=True)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    bar_indices = df["bar_index"].to_numpy(dtype=int)
    median_atr = _get_median_atr(df, atr_warmup_rows)

    impulses: List[Impulse] = []
    skipped_missing = 0
    skipped_too_short = 0

    for origin in origins:
        origin_row = bi_to_row.get(origin.bar_index)
        if origin_row is None:
            logger.warning(
                "detect_impulses: origin bar_index=%d not found in DataFrame; skipping",
                origin.bar_index,
            )
            continue

        is_up = origin.origin_type == "low"
        origin_px = origin.origin_price

        # Slice the look-ahead window
        window_start = origin_row + 1
        window_end = min(origin_row + 1 + max_lookahead_bars, len(df))
        if window_start >= len(df):
            continue

        window_bi = bar_indices[window_start:window_end]
        window_hi = highs[window_start:window_end]
        window_lo = lows[window_start:window_end]

        # ── Gap detection ────────────────────────────────────────────────
        has_gap = _has_bar_index_gap(window_bi)
        if skip_on_gap and has_gap:
            skipped_missing += 1
            logger.debug(
                "detect_impulses: skipping origin bar_index=%d (gap in window)",
                origin.bar_index,
            )
            continue

        # ── Walk forward for the extreme ─────────────────────────────────
        extreme_row_offset = 0  # offset within window
        if is_up:
            running_extreme = window_hi[0]
            for j in range(len(window_bi)):
                if window_hi[j] > running_extreme:
                    running_extreme = window_hi[j]
                    extreme_row_offset = j
                # Early reversal: price pulls back reversal_pct from the running high
                if reversal_pct > 0 and running_extreme > origin_px:
                    pullback = (running_extreme - window_lo[j]) / running_extreme
                    if pullback >= reversal_pct / 100.0:
                        break
        else:
            running_extreme = window_lo[0]
            for j in range(len(window_bi)):
                if window_lo[j] < running_extreme:
                    running_extreme = window_lo[j]
                    extreme_row_offset = j
                if reversal_pct > 0 and origin_px > running_extreme:
                    pullback = (window_hi[j] - running_extreme) / running_extreme
                    if pullback >= reversal_pct / 100.0:
                        break

        extreme_abs_row = window_start + extreme_row_offset
        extreme_px = float(running_extreme)
        extreme_bi = int(bar_indices[extreme_abs_row])
        delta_t = int(extreme_bi - origin.bar_index)

        if delta_t < min_delta_t:
            skipped_too_short += 1
            continue

        delta_p = extreme_px - origin_px
        min_abs_delta_p = abs(origin_px) * (min_delta_p_pct / 100.0)
        if abs(delta_p) < min_abs_delta_p:
            skipped_too_short += 1
            continue

        slope_raw = delta_p / delta_t if delta_t > 0 else 0.0
        if origin_px > 0 and extreme_px > 0:
            slope_log = (math.log(extreme_px) - math.log(origin_px)) / delta_t
        else:
            slope_log = float("nan")

        direction = "up" if is_up else "down"

        # Quality: blend origin quality and impulse magnitude vs ATR
        impulse_quality = _impulse_quality(abs(delta_p), delta_t, origin.quality_score, median_atr)

        impulse = Impulse(
            impulse_id=f"{origin.detector_name}_{origin.bar_index}",
            origin_time=origin.origin_time,
            origin_price=float(origin_px),
            extreme_time=timestamps[extreme_abs_row],
            extreme_price=extreme_px,
            origin_bar_index=origin.bar_index,
            extreme_bar_index=extreme_bi,
            delta_t=delta_t,
            delta_p=float(delta_p),
            slope_raw=float(slope_raw),
            slope_log=float(slope_log),
            direction=direction,
            quality_score=impulse_quality,
            detector_name=origin.detector_name,
            gap_in_window=has_gap,
        )
        impulses.append(impulse)

    impulses.sort(key=lambda imp: imp.origin_time)
    logger.info(
        "detect_impulses: total_origins=%d  produced=%d  skipped_gap=%d  skipped_short=%d",
        len(origins),
        len(impulses),
        skipped_missing,
        skipped_too_short,
    )
    return impulses


# ── Private helpers ────────────────────────────────────────────────────────


def _require_columns(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _get_median_atr(df: pd.DataFrame, atr_warmup_rows: int) -> float:
    if "atr_14" not in df.columns:
        return float("nan")
    valid = df["atr_14"].iloc[atr_warmup_rows:].dropna()
    if valid.empty:
        return float("nan")
    return float(valid.median())


def _has_bar_index_gap(bar_indices: np.ndarray) -> bool:
    """Return True if any consecutive pair of bar_indices has a gap > 1."""
    if len(bar_indices) < 2:
        return False
    diffs = np.diff(bar_indices)
    return bool((diffs > 1).any())


def _impulse_quality(
    abs_delta_p: float,
    delta_t: int,
    origin_quality: float,
    median_atr: float,
) -> float:
    """Blend origin quality and impulse magnitude into a [0, 1] score.

    magnitude_score = (abs_delta_p / delta_t) / (3 * median_atr), clipped [0,1]
    quality = 0.5 * origin_quality + 0.5 * magnitude_score
    """
    if np.isnan(median_atr) or median_atr <= 0 or delta_t == 0:
        return float(np.clip(origin_quality, 0.0, 1.0))
    per_bar = abs_delta_p / delta_t
    mag_score = float(np.clip(per_bar / (3.0 * median_atr), 0.0, 1.0))
    return float(np.clip(0.5 * origin_quality + 0.5 * mag_score, 0.0, 1.0))
