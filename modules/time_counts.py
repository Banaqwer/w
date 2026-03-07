"""
modules/time_counts.py

Time-count utilities for the Jenkins quant framework.

Purpose
-------
Provide gap-safe bar-count arithmetic for projecting time windows from
structural impulses.  All counting is done via ``bar_index`` deltas (not
calendar-day arithmetic), so counts are automatically correct even when
the dataset contains missing bars.

Gap-safety guarantee
--------------------
The processed datasets store a monotonically increasing ``bar_index``
column where each present bar gets the next integer.  Missing bars have
no row and thus no ``bar_index`` entry.  Bar-count arithmetic using
``bar_index`` deltas is therefore inherently gap-safe:

    bars_between = bar_index_end - bar_index_start

This equals the number of **present** bars between the two bars, which is
exactly what structural time projections need.  (DECISIONS.md 2026-03-06
gap policy / ASSUMPTIONS.md Assumption 26.)

Contrast with calendar-day counting: if the dataset has a missing bar on
date D, calendar-day arithmetic counts D even though no bar exists.
Bar-index arithmetic does not.

Functions
---------
- ``bars_between_by_bar_index(bar0, bar1)`` — signed bar delta between two
  known ``bar_index`` values.
- ``bars_between(t0, t1, index_map)`` — look up two timestamps in an
  ``index_map`` and return the bar delta.  Returns ``None`` if either
  timestamp is not in the map.
- ``build_index_map(df)`` — build a ``timestamp → bar_index`` lookup dict
  from a processed DataFrame.
- ``time_square_windows(impulse, multipliers, index_map)`` — produce
  :class:`TimeWindow` objects projecting forward in bar time from an
  impulse's extreme.

TimeWindow objects
------------------
:class:`TimeWindow` represents a projected bar-time target with no price
component.  It carries:
- The source impulse's bar metadata.
- The multiplier applied.
- The target ``bar_index`` (``extreme_bar_index + round(multiplier * delta_t)``).
- An optional resolved timestamp (if ``index_map`` is supplied and the
  target bar index exists in the dataset).

No confluence, confirmation, or signal logic is included (Phase 4+).

References
----------
ASSUMPTIONS.md — Assumption 26
DECISIONS.md — 2026-03-06 gap policy
modules/impulse.py — Impulse dataclass (delta_t, bar_index fields)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _to_utc_timestamp(ts: Any) -> pd.Timestamp:
    """Convert any timestamp-like value to a UTC-aware pd.Timestamp."""
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class TimeWindow:
    """A projected time target derived from one impulse at one multiplier.

    The target bar index is::

        target_bar_index = extreme_bar_index + round(multiplier * delta_t)

    If ``index_map`` was supplied and ``target_bar_index`` is present,
    ``target_time`` is the corresponding timestamp; otherwise ``None``.

    Fields
    ------
    impulse_id : str
        Propagated from the source impulse.
    origin_bar_index : int
        ``bar_index`` of the impulse origin.
    extreme_bar_index : int
        ``bar_index`` of the impulse extreme.
    impulse_delta_t : int
        Number of bars from origin to extreme (= ``delta_t`` on the impulse).
    multiplier : float
        Applied multiple of ``delta_t``.
    bar_offset : int
        ``round(multiplier * delta_t)`` — bars forward from the extreme.
    target_bar_index : int
        ``extreme_bar_index + bar_offset``.
    target_time : Optional[pd.Timestamp]
        UTC timestamp of the target bar, or ``None`` if it lies outside the
        known dataset or no ``index_map`` was provided.
    in_dataset : bool
        ``True`` iff ``target_bar_index`` is present in the supplied
        ``index_map``.  Always ``False`` when no ``index_map`` is given.
    notes : str
        Free-text notes (e.g. boundary conditions, warnings).
    """

    impulse_id: str
    origin_bar_index: int
    extreme_bar_index: int
    impulse_delta_t: int
    multiplier: float
    bar_offset: int
    target_bar_index: int
    target_time: Optional[pd.Timestamp]
    in_dataset: bool
    notes: str

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "impulse_id": self.impulse_id,
            "origin_bar_index": self.origin_bar_index,
            "extreme_bar_index": self.extreme_bar_index,
            "impulse_delta_t": self.impulse_delta_t,
            "multiplier": self.multiplier,
            "bar_offset": self.bar_offset,
            "target_bar_index": self.target_bar_index,
            "target_time": str(self.target_time) if self.target_time is not None else None,
            "in_dataset": self.in_dataset,
            "notes": self.notes,
        }


# ── Index-map helpers ─────────────────────────────────────────────────────────


def build_index_map(df: pd.DataFrame) -> Dict[pd.Timestamp, int]:
    """Build a ``timestamp → bar_index`` lookup dict from a processed DataFrame.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame with ``bar_index`` and either a
        ``timestamp`` column or a ``DatetimeIndex``.

    Returns
    -------
    Dict mapping each UTC-normalised timestamp to its ``bar_index``.

    Notes
    -----
    - Timestamps are normalised to UTC-aware ``pd.Timestamp`` objects so
      that the map works regardless of whether the source column had a
      timezone annotation.
    - The inverse map (``bar_index → timestamp``) is also useful; see
      :func:`build_bar_to_time_map`.
    """
    if "bar_index" not in df.columns:
        raise ValueError("DataFrame must have a 'bar_index' column.")

    if "timestamp" in df.columns:
        ts_series = pd.to_datetime(df["timestamp"], utc=True)
    elif isinstance(df.index, pd.DatetimeIndex):
        ts_series = df.index.to_series()
        if ts_series.dt.tz is None:
            ts_series = ts_series.dt.tz_localize("UTC")
        ts_series = pd.to_datetime(ts_series, utc=True)
    else:
        raise ValueError(
            "DataFrame must have a 'timestamp' column or a DatetimeIndex."
        )

    bar_indices = df["bar_index"].to_numpy()
    return {
        _to_utc_timestamp(ts): int(bi)
        for ts, bi in zip(ts_series, bar_indices)
    }


def build_bar_to_time_map(df: pd.DataFrame) -> Dict[int, pd.Timestamp]:
    """Build a ``bar_index → timestamp`` lookup dict from a processed DataFrame.

    This is the inverse of :func:`build_index_map` and is used by
    :func:`time_square_windows` to resolve target timestamps.

    Parameters
    ----------
    df:
        Processed OHLCV DataFrame with ``bar_index`` and timestamp info.

    Returns
    -------
    Dict mapping each ``bar_index`` integer to its UTC timestamp.
    """
    if "bar_index" not in df.columns:
        raise ValueError("DataFrame must have a 'bar_index' column.")

    if "timestamp" in df.columns:
        ts_series = pd.to_datetime(df["timestamp"], utc=True)
    elif isinstance(df.index, pd.DatetimeIndex):
        ts_series = df.index.to_series()
        if ts_series.dt.tz is None:
            ts_series = ts_series.dt.tz_localize("UTC")
        ts_series = pd.to_datetime(ts_series, utc=True)
    else:
        raise ValueError(
            "DataFrame must have a 'timestamp' column or a DatetimeIndex."
        )

    bar_indices = df["bar_index"].to_numpy()
    return {
        int(bi): _to_utc_timestamp(ts)
        for bi, ts in zip(bar_indices, ts_series)
    }


# ── Primary API ───────────────────────────────────────────────────────────────


def bars_between_by_bar_index(bar0: int, bar1: int) -> int:
    """Return the signed bar count between two ``bar_index`` values.

    This is the canonical gap-safe bar-count operation:
    ``result = bar1 - bar0``.

    Parameters
    ----------
    bar0:
        Starting ``bar_index`` (inclusive).
    bar1:
        Ending ``bar_index`` (inclusive).

    Returns
    -------
    Signed integer: positive when ``bar1 > bar0``, zero when equal,
    negative when ``bar1 < bar0``.
    """
    return int(bar1) - int(bar0)


def bars_between(
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    index_map: Dict[pd.Timestamp, int],
) -> Optional[int]:
    """Return the bar count between two timestamps using a ``timestamp → bar_index`` map.

    The result is ``index_map[t1] - index_map[t0]``, which is gap-safe
    because it uses ``bar_index`` values (not calendar arithmetic).

    Parameters
    ----------
    t0:
        Start timestamp (UTC).
    t1:
        End timestamp (UTC).
    index_map:
        Dict from :func:`build_index_map`.  Maps UTC timestamps to
        ``bar_index`` integers.

    Returns
    -------
    Signed bar delta, or ``None`` if either timestamp is absent from
    ``index_map``.

    Notes
    -----
    Timestamps are normalised to UTC before lookup so that timezone-naive
    inputs (rare, but possible) still resolve correctly.
    """
    # Normalise to UTC-aware Timestamps for reliable lookup.
    t0 = _to_utc_timestamp(t0)
    t1 = _to_utc_timestamp(t1)

    b0 = index_map.get(t0)
    b1 = index_map.get(t1)

    if b0 is None:
        logger.debug("bars_between: t0=%s not found in index_map.", t0)
        return None
    if b1 is None:
        logger.debug("bars_between: t1=%s not found in index_map.", t1)
        return None

    return int(b1) - int(b0)


def time_square_windows(
    impulse: Any,
    multipliers: Optional[List[float]] = None,
    bar_to_time_map: Optional[Dict[int, pd.Timestamp]] = None,
) -> List[TimeWindow]:
    """Produce time-window objects for an impulse at given ``delta_t`` multipliers.

    Each window is a forward bar target from the impulse extreme::

        target_bar_index = extreme_bar_index + round(multiplier * delta_t)

    If ``bar_to_time_map`` is provided and the target bar index exists in the
    map, the window's ``target_time`` is resolved to the corresponding
    timestamp.

    Parameters
    ----------
    impulse:
        :class:`~modules.impulse.Impulse` object or plain dict with at
        minimum: ``impulse_id``, ``delta_t``, ``origin_bar_index``,
        ``extreme_bar_index``.
    multipliers:
        List of multipliers to apply to ``delta_t``.
        Default ``[0.5, 1.0, 1.5, 2.0]``.
    bar_to_time_map:
        Optional dict from :func:`build_bar_to_time_map` mapping
        ``bar_index`` → ``pd.Timestamp``.  Used to resolve target times.
        If ``None``, ``target_time`` will be ``None`` for all windows.

    Returns
    -------
    List of :class:`TimeWindow` objects; one per valid multiplier.
    Empty if ``delta_t <= 0`` or ``multipliers`` is empty.

    Raises
    ------
    ValueError
        If any multiplier is negative.

    Notes
    -----
    - Multiplier = 0 is a degenerate case (projects to the extreme itself);
      it is included but noted.
    - ``round(multiplier * delta_t)`` uses Python's built-in round-half-to-
      even rule.  This is deterministic and reproducible.
    """
    if multipliers is None:
        multipliers = [0.5, 1.0, 1.5, 2.0]

    d = impulse.to_dict() if hasattr(impulse, "to_dict") else dict(impulse)

    impulse_id = str(d.get("impulse_id", "unknown"))
    delta_t = int(d.get("delta_t", 0))
    origin_bar_index = int(d.get("origin_bar_index", 0))
    extreme_bar_index = int(d.get("extreme_bar_index", 0))

    if delta_t <= 0:
        logger.debug(
            "time_square_windows: impulse_id=%r delta_t=%d <= 0; no windows.",
            impulse_id,
            delta_t,
        )
        return []

    if bar_to_time_map is None:
        bar_to_time_map = {}

    windows: List[TimeWindow] = []

    for mult in multipliers:
        if mult < 0:
            raise ValueError(
                f"time_square_windows: multipliers must be >= 0; got {mult}."
            )

        bar_offset = round(mult * delta_t)
        target_bar = extreme_bar_index + bar_offset

        target_time = bar_to_time_map.get(target_bar)
        in_dataset = target_time is not None

        notes_parts: List[str] = []
        if mult == 0:
            notes_parts.append("degenerate:projects_to_extreme")
        if not in_dataset and bar_to_time_map:
            notes_parts.append("target_bar_beyond_dataset")

        windows.append(
            TimeWindow(
                impulse_id=impulse_id,
                origin_bar_index=origin_bar_index,
                extreme_bar_index=extreme_bar_index,
                impulse_delta_t=delta_t,
                multiplier=mult,
                bar_offset=bar_offset,
                target_bar_index=target_bar,
                target_time=target_time,
                in_dataset=in_dataset,
                notes="; ".join(notes_parts),
            )
        )

    logger.debug(
        "time_square_windows: impulse_id=%r delta_t=%d multipliers=%r → %d windows.",
        impulse_id,
        delta_t,
        multipliers,
        len(windows),
    )
    return windows
