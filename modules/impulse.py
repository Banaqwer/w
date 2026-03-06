"""
modules/impulse.py

Impulse detection: for each Origin, find the subsequent extreme price move and
produce an Impulse object.

An Impulse represents a directed move from a structural origin to a subsequent
extreme:

  - ``origin_type="low"``  → upward impulse (extreme is the forward high)
  - ``origin_type="high"`` → downward impulse (extreme is the forward low)

The extreme is defined as the highest high (upward) or lowest low (downward)
within a forward window of up to ``max_bars`` bars from the origin bar.

Gap-handling policy (DECISIONS.md 2026-03-06 / ASSUMPTIONS.md Assumption 18)
-----------------------------------------------------------------------------
When ``skip_on_gap=True``, any origin whose forward window contains a detected
missing-bar gap is **silently skipped** (no Impulse is produced).

A gap is detected when the timestamp difference between two consecutive bars
exceeds **1.5 × the dataset's median inter-bar interval**.  This rule is
dataset-agnostic and works for any timeframe.

For the 6H dataset (``missing_bar_count=1`` per manifest), callers must pass
``skip_on_gap=True``.  The run_phase2_smoke script reads the manifest and sets
this flag automatically.

References
----------
CLAUDE.md — Phase 2 goal, Required deliverables B; Phase 0 Impulse spec
docs/handoff/jenkins_quant_prd.md — Impulse fields
ASSUMPTIONS.md — Assumption 18
DECISIONS.md — 2026-03-06 gap policy
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from modules.origin_selection import Origin

logger = logging.getLogger(__name__)


# ── Data model ───────────────────────────────────────────────────────────────


@dataclass
class Impulse:
    """A directed price move from a structural origin to a subsequent extreme.

    All fields are compatible with the Phase 0 Impulse spec (CLAUDE.md).

    Fields
    ------
    impulse_id : str
        Unique identifier: ``"{detector_name}_{origin_bar_index}"``.
    origin_time : pd.Timestamp
        UTC timestamp of the origin bar.
    origin_price : float
        Price at the origin (low for upward impulse, high for downward).
    extreme_time : pd.Timestamp
        UTC timestamp of the extreme bar.
    extreme_price : float
        Price at the extreme (highest high for up; lowest low for down).
    delta_t : int
        Number of bars from origin to extreme (``bar_index`` difference).
    delta_p : float
        Signed price difference: ``extreme_price - origin_price``.
        Positive for upward impulses, negative for downward.
    slope_raw : float
        Linear slope: ``delta_p / delta_t`` (price per bar).
    slope_log : float
        Log slope: ``log(extreme_price / origin_price) / delta_t``.
    quality_score : float
        ATR-normalised impulse magnitude clipped to [0.0, 1.0].
        Formula: ``|delta_p| / (median_atr * sqrt(delta_t))``.
    detector_name : str
        Origin detector name, propagated from the input :class:`Origin`.
    direction : str
        ``"up"`` or ``"down"``.
    origin_bar_index : int
        ``bar_index`` of the origin bar.
    extreme_bar_index : int
        ``bar_index`` of the extreme bar.
    """

    impulse_id: str
    origin_time: pd.Timestamp
    origin_price: float
    extreme_time: pd.Timestamp
    extreme_price: float
    delta_t: int
    delta_p: float
    slope_raw: float
    slope_log: float
    quality_score: float
    detector_name: str
    direction: str
    origin_bar_index: int
    extreme_bar_index: int

    def to_dict(self) -> dict:
        return {
            "impulse_id": self.impulse_id,
            "origin_time": self.origin_time,
            "origin_price": self.origin_price,
            "extreme_time": self.extreme_time,
            "extreme_price": self.extreme_price,
            "delta_t": self.delta_t,
            "delta_p": self.delta_p,
            "slope_raw": self.slope_raw,
            "slope_log": self.slope_log,
            "quality_score": self.quality_score,
            "detector_name": self.detector_name,
            "direction": self.direction,
            "origin_bar_index": self.origin_bar_index,
            "extreme_bar_index": self.extreme_bar_index,
        }


# ── Public API ───────────────────────────────────────────────────────────────


def detect_impulses(
    df: pd.DataFrame,
    origins: List[Origin],
    max_bars: int = 200,
    atr_col: str = "atr_14",
    skip_on_gap: bool = False,
) -> List[Impulse]:
    """Detect impulses from a list of Origins against a processed OHLCV DataFrame.

    For each origin:

    - ``origin_type="low"`` → upward impulse: the extreme is the bar with the
      **maximum high** in the forward window ``[origin_row+1, origin_row+max_bars]``.
    - ``origin_type="high"`` → downward impulse: the extreme is the bar with
      the **minimum low** in the same forward window.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame with ``bar_index``, ``timestamp``, ``high``,
        ``low``, and optionally an ATR column for quality scoring.
    origins:
        List of :class:`~modules.origin_selection.Origin` objects.
    max_bars:
        Maximum forward search window in bars.  Default 200.
    atr_col:
        ATR column for quality scoring.  If absent, quality defaults to 0.5.
    skip_on_gap:
        If ``True``, skip any origin whose forward window contains a
        missing-bar gap (see module docstring for gap rule).
        **Set to ``True`` when the manifest ``missing_bar_count > 0``.**

    Returns
    -------
    List of :class:`Impulse` objects sorted by ``origin_bar_index`` ascending.

    Notes
    -----
    - Origins at or near the end of the dataset with no forward bars available
      are silently skipped.
    - Degenerate impulses with ``delta_t <= 0``, or with zero / NaN prices,
      are silently skipped.
    - The slope fields use the coordinate_system scaling contract:
      ``slope_raw = delta_p / delta_t`` (price per bar);
      ``slope_log = log(extreme / origin) / delta_t`` (log-return per bar).
      Angle-basis scaling is deferred to Phase 3.
    """
    if not origins:
        return []

    _require_columns(df, {"bar_index", "high", "low"})

    n = len(df)
    if n < 2:
        return []

    bar_indices = df["bar_index"].to_numpy(dtype=np.int64)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts = _get_timestamps(df)

    has_atr = atr_col in df.columns
    atr_values = df[atr_col].to_numpy(dtype=float) if has_atr else None

    # Pre-compute global median ATR (excluding NaN warm-up rows).
    if has_atr and atr_values is not None:
        valid_atr = atr_values[~np.isnan(atr_values)]
        median_atr = float(np.median(valid_atr)) if len(valid_atr) > 0 else 0.0
    else:
        median_atr = 0.0

    # Build bar_index → row-position lookup for O(1) origin resolution.
    bar_idx_to_row: dict[int, int] = {
        int(b): r for r, b in enumerate(bar_indices)
    }

    # Pre-compute gap flags if gap-skipping is requested.
    gap_flags: Optional[np.ndarray] = None
    if skip_on_gap:
        gap_flags = _compute_gap_flags(df)

    impulses: List[Impulse] = []
    skipped_gap_count = 0

    for origin in origins:
        origin_row = bar_idx_to_row.get(origin.bar_index)
        if origin_row is None:
            logger.debug(
                "Origin bar_index=%d not found in DataFrame; skipping.",
                origin.bar_index,
            )
            continue

        window_start = origin_row + 1
        window_end = min(origin_row + max_bars + 1, n)

        if window_start >= n:
            logger.debug(
                "Origin at bar_index=%d is at/near end of dataset; no forward bars.",
                origin.bar_index,
            )
            continue

        # Gap check: skip if the forward window crosses a missing bar.
        if skip_on_gap and gap_flags is not None:
            if _window_has_gap(gap_flags, window_start, window_end):
                skipped_gap_count += 1
                logger.debug(
                    "Skipping origin at bar_index=%d: forward window crosses a gap.",
                    origin.bar_index,
                )
                continue

        # Find extreme in the forward window.
        if origin.origin_type == "low":
            # Upward impulse: highest high in window.
            local_idx = int(np.argmax(highs[window_start:window_end]))
            extreme_row = window_start + local_idx
            extreme_price = float(highs[extreme_row])
        else:
            # Downward impulse: lowest low in window.
            local_idx = int(np.argmin(lows[window_start:window_end]))
            extreme_row = window_start + local_idx
            extreme_price = float(lows[extreme_row])

        origin_price = float(origin.origin_price)

        # Skip degenerate cases.
        if origin_price <= 0 or extreme_price <= 0:
            continue
        if np.isnan(origin_price) or np.isnan(extreme_price):
            continue

        delta_t = int(bar_indices[extreme_row]) - int(bar_indices[origin_row])
        if delta_t <= 0:
            continue

        delta_p = extreme_price - origin_price
        slope_raw = delta_p / delta_t
        slope_log = float(np.log(extreme_price / origin_price)) / delta_t

        direction = "up" if origin.origin_type == "low" else "down"

        # Quality score: ATR-normalised magnitude, clipped to [0, 1].
        if median_atr > 0:
            expected_move = median_atr * np.sqrt(float(delta_t))
            quality_score = float(min(1.0, abs(delta_p) / expected_move))
        else:
            quality_score = 0.5

        impulse = Impulse(
            impulse_id=f"{origin.detector_name}_{origin.bar_index}",
            origin_time=ts[origin_row],
            origin_price=origin_price,
            extreme_time=ts[extreme_row],
            extreme_price=extreme_price,
            delta_t=delta_t,
            delta_p=delta_p,
            slope_raw=slope_raw,
            slope_log=slope_log,
            quality_score=quality_score,
            detector_name=origin.detector_name,
            direction=direction,
            origin_bar_index=int(bar_indices[origin_row]),
            extreme_bar_index=int(bar_indices[extreme_row]),
        )
        impulses.append(impulse)

    if skipped_gap_count > 0:
        logger.info(
            "detect_impulses: skipped %d origin(s) due to gap crossing.",
            skipped_gap_count,
        )

    impulses.sort(key=lambda imp: imp.origin_bar_index)
    logger.info(
        "detect_impulses: produced %d impulse(s) from %d origin(s).",
        len(impulses),
        len(origins),
    )
    return impulses


def impulses_to_dataframe(impulses: List[Impulse]) -> pd.DataFrame:
    """Convert a list of Impulses to a DataFrame for export or inspection."""
    if not impulses:
        return pd.DataFrame(
            columns=[
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
            ]
        )
    return pd.DataFrame([imp.to_dict() for imp in impulses])


# ── Private helpers ──────────────────────────────────────────────────────────


def _require_columns(df: pd.DataFrame, required: set) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")


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


def _compute_gap_flags(df: pd.DataFrame) -> np.ndarray:
    """Return a boolean array where ``gap_flags[i]`` is ``True`` if there is a
    missing-bar gap **immediately before** row ``i``.

    Gap rule (Assumption 18 / DECISIONS.md 2026-03-06):
    A gap exists when the timestamp difference between bar ``i-1`` and bar
    ``i`` exceeds **1.5 × the dataset's median inter-bar interval**.

    Parameters
    ----------
    df:
        Processed DataFrame with timestamps.

    Returns
    -------
    Boolean array of length ``len(df)``.  ``gap_flags[0]`` is always False.
    """
    ts = _get_timestamps(df)
    n = len(ts)
    gap_flags = np.zeros(n, dtype=bool)

    if n < 2:
        return gap_flags

    diffs_sec = np.array(
        [(ts[i] - ts[i - 1]).total_seconds() for i in range(1, n)],
        dtype=float,
    )
    median_sec = float(np.median(diffs_sec))

    if median_sec <= 0:
        return gap_flags

    gap_threshold = 1.5 * median_sec
    for i in range(1, n):
        if diffs_sec[i - 1] > gap_threshold:
            gap_flags[i] = True

    n_gaps = int(np.sum(gap_flags))
    if n_gaps > 0:
        logger.info(
            "_compute_gap_flags: detected %d gap(s) in %d bars "
            "(median_interval=%.0fs, threshold=%.0fs).",
            n_gaps,
            n,
            median_sec,
            gap_threshold,
        )

    return gap_flags


def _window_has_gap(
    gap_flags: np.ndarray, window_start: int, window_end: int
) -> bool:
    """Return ``True`` if any bar in ``[window_start, window_end)`` has a gap before it."""
    return bool(np.any(gap_flags[window_start:window_end]))
