"""
signals/generators_sqrt_levels.py

Phase 4 — Projection generator for square-root horizontal price levels.

Converts :class:`~modules.sqrt_levels.SqrtLevel` objects (Phase 3) into
standardised :class:`~signals.projections.Projection` objects.

Mapping rules
-------------
- Each ``SqrtLevel`` produces one price-only ``Projection``.
- ``projected_price`` = ``level_price``.
- ``projected_time`` = ``None`` (sqrt levels are horizontal — time-invariant).
- ``price_band`` = ``(level_price * (1 - band_pct), level_price * (1 + band_pct))``
  where ``band_pct`` defaults to 0.005 (0.5%; tighter than measured moves,
  since sqrt levels are exact algebraic constructs with no ratio uncertainty).
- ``time_band`` = ``(None, None)`` — price-only.
- ``direction_hint``:
  - Up levels (above origin_price) → ``"resistance"``.
  - Down levels (below origin_price) → ``"support"``.
- ``raw_score``:
  - Decreases with distance from origin: ``raw_score = 1 / (1 + step * 0.05)``.
    Step-1 levels score 0.95; step-8 levels score ~0.71.
  - Clipped to [0, 1].

Public API
----------
- :func:`projections_from_sqrt_levels` — primary function.

References
----------
signals/projections.py — Projection dataclass
modules/sqrt_levels.py — SqrtLevel, sqrt_levels
CLAUDE.md — Phase 4 generator spec
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from signals.projections import PriceBand, Projection, TimeBand

logger = logging.getLogger(__name__)

_MODULE_NAME = "sqrt_levels"
_DEFAULT_BAND_PCT = 0.005  # ±0.5% price band
_STEP_DECAY = 0.05         # per-step score decay factor


def projections_from_sqrt_levels(
    levels: List[Any],
    origin_price: Optional[float] = None,
    band_pct: float = _DEFAULT_BAND_PCT,
    source_id: str = "sqrt_origin",
) -> List[Projection]:
    """Convert a list of SqrtLevel objects to Projections.

    Parameters
    ----------
    levels:
        List of :class:`~modules.sqrt_levels.SqrtLevel` objects or plain dicts
        with at minimum: ``level_price``, ``direction``, ``step``.
    origin_price:
        The price from which the levels were computed.  Used only to override
        direction detection when ``direction`` is missing from the dict.
    band_pct:
        Fractional price band half-width.  Default 0.005 (0.5%).
    source_id:
        Source identifier string shared by all projections from this set of
        levels (e.g. an impulse ID or origin label).

    Returns
    -------
    List of :class:`~signals.projections.Projection` objects.

    Raises
    ------
    ValueError
        If ``band_pct < 0``.
    """
    if band_pct < 0:
        raise ValueError(f"band_pct must be >= 0; got {band_pct}.")

    projections: List[Projection] = []

    for lvl in levels:
        d = lvl.to_dict() if hasattr(lvl, "to_dict") else dict(lvl)

        level_price = d.get("level_price")
        if level_price is None:
            continue
        level_price = float(level_price)
        if level_price <= 0:
            logger.debug(
                "projections_from_sqrt_levels: non-positive level_price=%.4f; skipping.",
                level_price,
            )
            continue

        level_dir = str(d.get("direction", ""))
        step = int(d.get("step", 1))
        label = str(d.get("label", ""))
        increment = d.get("increment_used")

        # Direction hint
        if level_dir == "up":
            direction_hint = "resistance"
        elif level_dir == "down":
            direction_hint = "support"
        elif origin_price is not None:
            direction_hint = "resistance" if level_price >= origin_price else "support"
        else:
            direction_hint = "ambiguous"

        # Score decays with step distance
        raw_score = max(0.0, min(1.0, 1.0 / (1.0 + step * _STEP_DECAY)))

        price_band: PriceBand = (
            level_price * (1.0 - band_pct),
            level_price * (1.0 + band_pct),
        )
        time_band: TimeBand = (None, None)

        metadata: dict = {
            "level_direction": level_dir,
            "step": step,
            "label": label,
        }
        if increment is not None:
            metadata["increment_used"] = float(increment)
        if origin_price is not None:
            metadata["origin_price"] = origin_price

        proj = Projection(
            module_name=_MODULE_NAME,
            source_id=source_id,
            projected_time=None,
            projected_price=level_price,
            time_band=time_band,
            price_band=price_band,
            direction_hint=direction_hint,
            raw_score=raw_score,
            metadata=metadata,
        )
        projections.append(proj)

    logger.debug(
        "projections_from_sqrt_levels: %d levels → %d projections.",
        len(levels),
        len(projections),
    )
    return projections
