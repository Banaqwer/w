"""
signals/generators_jttl.py

Phase 4 — Projection generator for JTTL (Jenkins Theoretical Target Level) lines.

Converts :class:`~modules.jttl.JTTLLine` objects (Phase 3) into standardised
:class:`~signals.projections.Projection` objects.

Two projection modes are supported per JTTL line:

1. **Endpoint projection** (default): projects the endpoint ``(t1, p1)`` —
   the theoretical target price at the horizon timestamp.  This is a combined
   time+price projection.

2. **Price-at-time queries**: for a list of query timestamps, compute the price
   on the JTTL line at each time and produce a price projection at that level.
   (optional, enabled via ``query_times`` parameter)

Mapping rules
-------------
- ``projected_time`` = ``t1`` (horizon endpoint).
- ``projected_price`` = ``p1`` (theoretical target price).
- ``time_band`` = ``(t1 - half_band_days, t1 + half_band_days)`` where
  ``half_band_days`` defaults to 7 calendar days.
- ``price_band`` = ``(p1 * (1 - band_pct), p1 * (1 + band_pct))``.
- ``direction_hint``:
  - ``p1 > p0`` → ``"resistance"`` (JTTL is rising; projects above origin).
  - ``p1 < p0`` → ``"support"`` (JTTL is falling).
  - ``p1 == p0`` → ``"ambiguous"`` (flat JTTL).
- ``raw_score`` = clipped ``quality_score`` if supplied; defaults to 0.5.

Public API
----------
- :func:`projections_from_jttl_lines` — primary function.

References
----------
signals/projections.py — Projection dataclass
modules/jttl.py — JTTLLine, compute_jttl
CLAUDE.md — Phase 4 generator spec
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

import pandas as pd

from signals.projections import PriceBand, Projection, TimeBand

logger = logging.getLogger(__name__)

_MODULE_NAME = "jttl"
_DEFAULT_BAND_PCT = 0.01       # ±1% price band
_DEFAULT_HALF_BAND_DAYS = 7    # ±7 calendar days time band
_DEFAULT_QUALITY = 0.5


def projections_from_jttl_lines(
    jttl_lines: List[Any],
    band_pct: float = _DEFAULT_BAND_PCT,
    half_band_days: float = _DEFAULT_HALF_BAND_DAYS,
    quality_scores: Optional[List[float]] = None,
    source_ids: Optional[List[str]] = None,
) -> List[Projection]:
    """Convert a list of JTTLLine objects to Projections (endpoint mode).

    Each ``JTTLLine`` produces one ``Projection`` at its horizon endpoint
    ``(t1, p1)``.

    Parameters
    ----------
    jttl_lines:
        List of :class:`~modules.jttl.JTTLLine` objects or plain dicts with at
        minimum: ``t1``, ``p1``, ``p0``, ``t0``.
    band_pct:
        Fractional price band half-width.  Default 0.01 (1%).
    half_band_days:
        Calendar-day half-width of the time band around ``t1``.  Default 7.
    quality_scores:
        Optional list of quality scores parallel to ``jttl_lines``.  If
        ``None``, all projections receive ``raw_score = 0.5``.
    source_ids:
        Optional list of string IDs parallel to ``jttl_lines``.  If ``None``,
        IDs are auto-generated as ``"jttl_{i}"``.

    Returns
    -------
    List of :class:`~signals.projections.Projection` objects.

    Raises
    ------
    ValueError
        If ``band_pct < 0`` or ``half_band_days < 0``.
    """
    if band_pct < 0:
        raise ValueError(f"band_pct must be >= 0; got {band_pct}.")
    if half_band_days < 0:
        raise ValueError(f"half_band_days must be >= 0; got {half_band_days}.")

    projections: List[Projection] = []

    for i, jl in enumerate(jttl_lines):
        d = jl.to_dict() if hasattr(jl, "to_dict") else dict(jl)

        source_id = (
            source_ids[i] if source_ids and i < len(source_ids) else f"jttl_{i}"
        )
        q = (
            float(quality_scores[i])
            if quality_scores and i < len(quality_scores)
            else _DEFAULT_QUALITY
        )
        raw_score = max(0.0, min(1.0, q))

        t1_raw = d.get("t1")
        p1 = d.get("p1")
        p0 = d.get("p0")
        t0_raw = d.get("t0")
        k = d.get("k")
        horizon_days = d.get("horizon_days")
        basis = d.get("basis", "calendar_days")

        if t1_raw is None or p1 is None:
            logger.debug(
                "projections_from_jttl_lines: missing t1/p1 for index %d; skipping.", i
            )
            continue

        p1 = float(p1)
        t1 = _to_utc(t1_raw)

        if p1 <= 0:
            logger.debug(
                "projections_from_jttl_lines: non-positive p1=%.4f for index %d; skipping.",
                p1, i,
            )
            continue

        # Time band
        delta = pd.Timedelta(days=half_band_days)
        time_band: TimeBand = (t1 - delta, t1 + delta)

        # Price band
        price_band: PriceBand = (p1 * (1.0 - band_pct), p1 * (1.0 + band_pct))

        # Direction hint
        if p0 is not None:
            p0f = float(p0)
            if p1 > p0f:
                direction_hint = "resistance"
            elif p1 < p0f:
                direction_hint = "support"
            else:
                direction_hint = "ambiguous"
        else:
            direction_hint = "ambiguous"

        metadata: dict = {
            "k": k,
            "horizon_days": horizon_days,
            "basis": basis,
        }
        if t0_raw is not None:
            metadata["t0"] = str(_to_utc(t0_raw))
        if p0 is not None:
            metadata["p0"] = float(p0)

        proj = Projection(
            module_name=_MODULE_NAME,
            source_id=source_id,
            projected_time=t1,
            projected_price=p1,
            time_band=time_band,
            price_band=price_band,
            direction_hint=direction_hint,
            raw_score=raw_score,
            metadata=metadata,
        )
        projections.append(proj)

    logger.debug(
        "projections_from_jttl_lines: %d lines → %d projections.",
        len(jttl_lines),
        len(projections),
    )
    return projections


# ── Helpers ───────────────────────────────────────────────────────────────────


def _to_utc(ts: Any) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize("UTC")
    return t.tz_convert("UTC")
