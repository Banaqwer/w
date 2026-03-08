"""
signals/generators_time_counts.py

Phase 4 — Projection generator for time-count windows.

Converts :class:`~modules.time_counts.TimeWindow` objects (Phase 3) into
standardised :class:`~signals.projections.Projection` objects.

Time-count projections are **time-only**: they project a bar-time target with
no associated price level.  Price confluence must come from other generators.

Mapping rules
-------------
- Each ``TimeWindow`` produces one time-only ``Projection``.
- ``projected_time`` = ``target_time`` from the ``TimeWindow`` (may be ``None``
  if the target bar lies outside the dataset).  If ``None`` and the
  ``bar_to_time_map`` is not supplied, the projection is still created with
  ``projected_time = None`` (open-ended time estimate).
- ``projected_price`` = ``None`` (time-only projection).
- ``time_band``: constructed as ``(target_time - half_band_bars, target_time +
  half_band_bars)`` in bar units when ``target_time`` is known, or
  ``(None, None)`` when it is unknown.  ``half_band_bars`` defaults to 2 bars
  (≈ 2 calendar days for 1D data).
- ``price_band`` = ``(None, None)`` — time-only.
- ``direction_hint`` = ``"turn"`` (time counts are turn-date projections, not
  directional).
- ``raw_score`` = ``quality_score`` from the source impulse when available;
  defaults to 0.5.  Recency weight: windows at multiplier=1.0 have no recency
  penalty; multipliers > 1.0 are slightly discounted:
  ``raw_score *= max(0.5, 1.0 / multiplier)``.

Gap policy
----------
This module works with ``bar_index`` targets only.  If a ``bar_to_time_map``
is provided, target timestamps are resolved.  For 6H datasets with
``missing_bar_count > 0``, use bar-index arithmetic (gap-safe by construction).

Public API
----------
- :func:`projections_from_time_windows` — primary function.

References
----------
signals/projections.py — Projection dataclass
modules/time_counts.py — TimeWindow
CLAUDE.md — Phase 4 generator spec; 6H gap note
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from signals.projections import PriceBand, Projection, TimeBand

logger = logging.getLogger(__name__)

_MODULE_NAME = "time_counts"
_DEFAULT_HALF_BAND_BARS = 2   # ±2 bars time band
_DEFAULT_QUALITY = 0.5


def projections_from_time_windows(
    windows: List[Any],
    bar_to_time_map: Optional[Dict[int, pd.Timestamp]] = None,
    half_band_bars: int = _DEFAULT_HALF_BAND_BARS,
    quality_scores: Optional[Dict[str, float]] = None,
) -> List[Projection]:
    """Convert a list of TimeWindow objects to time-only Projections.

    Parameters
    ----------
    windows:
        List of :class:`~modules.time_counts.TimeWindow` objects or plain dicts
        with at minimum: ``impulse_id``, ``target_bar_index``, ``multiplier``.
    bar_to_time_map:
        Optional mapping of ``bar_index → UTC timestamp`` from the processed
        DataFrame (built via ``modules.time_counts.build_bar_to_time_map``).
        When provided, ``projected_time`` and the time band are resolved;
        otherwise both are ``None`` if ``target_time`` is missing.
    half_band_bars:
        Number of bars to extend each side of the time band.  Must be >= 0.
        Default 2.  The bar half-width is converted to a calendar-day
        approximate using the median inter-bar interval if ``bar_to_time_map``
        is available; otherwise the raw bar-count is stored in metadata.
    quality_scores:
        Optional mapping of ``impulse_id → quality_score``.  If provided,
        the score for each window's impulse_id is used; otherwise defaults to
        0.5.

    Returns
    -------
    List of :class:`~signals.projections.Projection` objects.

    Raises
    ------
    ValueError
        If ``half_band_bars < 0``.
    """
    if half_band_bars < 0:
        raise ValueError(f"half_band_bars must be >= 0; got {half_band_bars}.")

    projections: List[Projection] = []

    # Pre-compute median bar interval if bar_to_time_map has enough entries
    _bar_interval_days = _estimate_bar_interval_days(bar_to_time_map)

    for w in windows:
        d = w.to_dict() if hasattr(w, "to_dict") else dict(w)

        impulse_id = str(d.get("impulse_id", "unknown"))
        target_bar_index = d.get("target_bar_index")
        multiplier = float(d.get("multiplier", 1.0))
        in_dataset = bool(d.get("in_dataset", False))
        notes_raw = str(d.get("notes", ""))
        origin_bar_index = d.get("origin_bar_index")
        extreme_bar_index = d.get("extreme_bar_index")
        impulse_delta_t = d.get("impulse_delta_t")

        if target_bar_index is None:
            logger.debug(
                "projections_from_time_windows: missing target_bar_index for "
                "impulse_id=%r; skipping.",
                impulse_id,
            )
            continue

        target_bar_index = int(target_bar_index)

        # Resolve target_time
        target_time: Optional[pd.Timestamp] = None
        raw_target = d.get("target_time")
        if raw_target is not None and str(raw_target) not in ("None", ""):
            try:
                target_time = _to_utc(raw_target)
            except Exception:
                pass
        if target_time is None and bar_to_time_map is not None:
            target_time = bar_to_time_map.get(target_bar_index)

        # Build time band
        time_band = _make_time_band(
            target_time, target_bar_index, half_band_bars,
            bar_to_time_map, _bar_interval_days
        )

        price_band: PriceBand = (None, None)

        # Score: base from quality, then recency weight by multiplier
        base_score = float(
            quality_scores.get(impulse_id, _DEFAULT_QUALITY)
            if quality_scores else _DEFAULT_QUALITY
        )
        recency_weight = max(0.5, 1.0 / multiplier) if multiplier > 0 else 0.5
        raw_score = max(0.0, min(1.0, base_score * recency_weight))

        metadata: dict = {
            "multiplier": multiplier,
            "target_bar_index": target_bar_index,
            "in_dataset": in_dataset,
            "half_band_bars": half_band_bars,
            "notes": notes_raw,
        }
        if origin_bar_index is not None:
            metadata["origin_bar_index"] = int(origin_bar_index)
        if extreme_bar_index is not None:
            metadata["extreme_bar_index"] = int(extreme_bar_index)
        if impulse_delta_t is not None:
            metadata["impulse_delta_t"] = int(impulse_delta_t)

        proj = Projection(
            module_name=_MODULE_NAME,
            source_id=impulse_id,
            projected_time=target_time,
            projected_price=None,
            time_band=time_band,
            price_band=price_band,
            direction_hint="turn",
            raw_score=raw_score,
            metadata=metadata,
        )
        projections.append(proj)

    logger.debug(
        "projections_from_time_windows: %d windows → %d projections.",
        len(windows),
        len(projections),
    )
    return projections


# ── Helpers ───────────────────────────────────────────────────────────────────


def _to_utc(ts: Any) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")


def _estimate_bar_interval_days(
    bar_to_time_map: Optional[Dict[int, pd.Timestamp]],
) -> Optional[float]:
    """Return median bar-to-bar interval in days, or None if not computable."""
    if not bar_to_time_map or len(bar_to_time_map) < 2:
        return None
    sorted_bars = sorted(bar_to_time_map.keys())
    diffs: list = []
    for i in range(1, min(len(sorted_bars), 101)):  # sample up to 100 pairs
        try:
            d = (
                bar_to_time_map[sorted_bars[i]] - bar_to_time_map[sorted_bars[i - 1]]
            ).total_seconds() / 86400.0
            diffs.append(d)
        except Exception:
            pass
    if not diffs:
        return None
    diffs.sort()
    mid = len(diffs) // 2
    return diffs[mid]


def _make_time_band(
    target_time: Optional[pd.Timestamp],
    target_bar_index: int,
    half_band_bars: int,
    bar_to_time_map: Optional[Dict[int, pd.Timestamp]],
    bar_interval_days: Optional[float],
) -> TimeBand:
    """Build the time band around a target, using calendar days if available."""
    if target_time is None:
        # Try to resolve from bar_to_time_map for nearby bars
        if bar_to_time_map is not None and bar_interval_days is not None:
            # Find closest known bar and extrapolate
            lower = bar_to_time_map.get(target_bar_index - half_band_bars)
            upper = bar_to_time_map.get(target_bar_index + half_band_bars)
            return (lower, upper)
        return (None, None)

    if bar_interval_days is not None:
        delta = pd.Timedelta(days=half_band_bars * bar_interval_days)
        return (target_time - delta, target_time + delta)

    # Fall back: ±half_band_bars calendar days (assume 1D data)
    delta = pd.Timedelta(days=half_band_bars)
    return (target_time - delta, target_time + delta)
