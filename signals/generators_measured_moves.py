"""
signals/generators_measured_moves.py

Phase 4 — Projection generator for measured-move targets.

Converts :class:`~modules.measured_moves.MeasuredMoveTarget` objects (Phase 3)
into standardised :class:`~signals.projections.Projection` objects.

Mapping rules
-------------
- Each ``MeasuredMoveTarget`` produces exactly one ``Projection`` (price-only).
- ``projected_price`` = ``target_price``.
- ``projected_time`` = ``None`` (measured moves are price projections only;
  time projections come from ``time_counts``).
- ``price_band`` = ``(target_price * (1 - band_pct), target_price * (1 + band_pct))``
  where ``band_pct`` defaults to 0.01 (1%).  This represents a ±1% tolerance
  around the target price level.
- ``direction_hint``:
  - Extension of an upward impulse → ``"resistance"``
  - Extension of a downward impulse → ``"support"``
  - Retracement of an upward impulse → ``"support"``
  - Retracement of a downward impulse → ``"resistance"``
  - Ambiguous (delta_p == 0 or unknown direction) → ``"ambiguous"``
- ``raw_score`` = ``quality_score`` from the source impulse (already [0, 1]).

Public API
----------
- :func:`projections_from_measured_moves` — primary function.

References
----------
signals/projections.py — Projection dataclass
modules/measured_moves.py — MeasuredMoveTarget
CLAUDE.md — Phase 4 generator spec
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from signals.projections import PriceBand, Projection, TimeBand

logger = logging.getLogger(__name__)

_MODULE_NAME = "measured_moves"
_DEFAULT_BAND_PCT = 0.01  # ±1% price tolerance band


def projections_from_measured_moves(
    targets: List[Any],
    band_pct: float = _DEFAULT_BAND_PCT,
) -> List[Projection]:
    """Convert a list of MeasuredMoveTarget objects to Projections.

    Parameters
    ----------
    targets:
        List of :class:`~modules.measured_moves.MeasuredMoveTarget` objects or
        plain dicts with at minimum: ``impulse_id``, ``target_price``,
        ``direction``, ``quality_score``, ``notes``, and optionally
        ``origin_price``, ``extreme_price``, ``ratio``, ``mode``.
    band_pct:
        Fractional price tolerance band half-width.  Default 0.01 (1%).
        Must be >= 0.

    Returns
    -------
    List of :class:`~signals.projections.Projection` objects; one per input
    target.  Targets with non-positive ``target_price`` are skipped.

    Raises
    ------
    ValueError
        If ``band_pct < 0``.
    """
    if band_pct < 0:
        raise ValueError(f"band_pct must be >= 0; got {band_pct}.")

    projections: List[Projection] = []

    for t in targets:
        d = t.to_dict() if hasattr(t, "to_dict") else dict(t)

        source_id = str(d.get("impulse_id", "unknown"))
        target_price = float(d.get("target_price", 0.0))
        direction = str(d.get("direction", ""))
        quality_score = float(d.get("quality_score", 0.0))
        notes_raw = str(d.get("notes", ""))
        ratio = d.get("ratio")
        mode = str(d.get("mode", "raw"))
        origin_price = d.get("origin_price")
        extreme_price = d.get("extreme_price")
        impulse_direction = _infer_impulse_direction(origin_price, extreme_price, d)

        if target_price <= 0:
            logger.debug(
                "projections_from_measured_moves: skipping non-positive "
                "target_price=%.4f for source_id=%r.",
                target_price,
                source_id,
            )
            continue

        price_band: PriceBand = (
            target_price * (1.0 - band_pct),
            target_price * (1.0 + band_pct),
        )
        time_band: TimeBand = (None, None)

        direction_hint = _direction_hint(direction, impulse_direction)
        raw_score = max(0.0, min(1.0, quality_score))

        metadata = {
            "ratio": ratio,
            "mode": mode,
            "move_direction": direction,
            "impulse_direction": impulse_direction,
            "notes": notes_raw,
        }
        if origin_price is not None:
            metadata["origin_price"] = origin_price
        if extreme_price is not None:
            metadata["extreme_price"] = extreme_price

        proj = Projection(
            module_name=_MODULE_NAME,
            source_id=source_id,
            projected_time=None,
            projected_price=target_price,
            time_band=time_band,
            price_band=price_band,
            direction_hint=direction_hint,
            raw_score=raw_score,
            metadata=metadata,
        )
        projections.append(proj)

    logger.debug(
        "projections_from_measured_moves: %d targets → %d projections.",
        len(targets),
        len(projections),
    )
    return projections


# ── Helpers ───────────────────────────────────────────────────────────────────


def _infer_impulse_direction(
    origin_price: Optional[Any],
    extreme_price: Optional[Any],
    d: dict,
) -> str:
    """Return 'up', 'down', or 'unknown' from price fields or dict key."""
    # Direct field
    imp_dir = d.get("impulse_direction") or d.get("direction_impulse")
    if imp_dir in ("up", "down"):
        return str(imp_dir)
    # Infer from prices
    if origin_price is not None and extreme_price is not None:
        try:
            op = float(origin_price)
            ep = float(extreme_price)
            if ep > op:
                return "up"
            if ep < op:
                return "down"
        except (TypeError, ValueError):
            pass
    return "unknown"


def _direction_hint(move_direction: str, impulse_direction: str) -> str:
    """Map move direction + impulse direction to a direction_hint string."""
    # extension in direction of impulse
    if move_direction == "extension":
        if impulse_direction == "up":
            return "resistance"
        if impulse_direction == "down":
            return "support"
    # retracement back against impulse direction
    if move_direction == "retracement":
        if impulse_direction == "up":
            return "support"
        if impulse_direction == "down":
            return "resistance"
    return "ambiguous"
