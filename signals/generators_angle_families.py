"""
signals/generators_angle_families.py

Phase 4 — Projection generator for angle-family based price targets.

Converts impulse angle data (computed by
:func:`~modules.adjusted_angles.compute_impulse_angles`) into standardised
:class:`~signals.projections.Projection` objects.

Angle-family projections project forward price levels at the canonical
Jenkins angle slopes (1×1, 2×1, 1×2, etc.) from the impulse extreme point.
Each canonical angle fan line yields a price target at a given horizon
(in bars).

Mapping rules
-------------
- For each impulse with a computed angle, project price targets along all
  canonical angle family lines from the impulse *extreme* point.
- ``projected_price`` = ``extreme_price + slope_raw * horizon_bars`` where
  ``slope_raw = angle_deg_to_slope(family_angle, scale_basis)``.
  For downward impulses, the family angles are negated to project in the
  impulse direction.
- ``projected_time`` = ``None`` (price-only, since the horizon is a parameter
  rather than a fixed date; for time+price, see ``generators_jttl.py``).
- ``price_band`` = ``(target * (1 - band_pct), target * (1 + band_pct))``.
- ``time_band`` = ``(None, None)`` — price-only projections.
- ``direction_hint``:
  - Fan line projecting above extreme → ``"resistance"``
  - Fan line projecting below extreme → ``"support"``
  - Flat (0°) → ``"ambiguous"``
- ``raw_score`` = ``quality_score * (1.0 - 0.1 * abs(delta_deg))`` where
  ``delta_deg`` is the deviation of the impulse's actual angle from the
  family centre.  Tighter matches score higher.  Clamped to [0.1, 1.0].

Conservative scope (MVP)
------------------------
- Only impulses that have been bucketed to a recognised angle family are
  processed (i.e. ``angle_family`` is not ``None``).
- Horizon defaults to 90 bars (≈ 90 calendar days for 1D data).
- The generator emits one ``Projection`` per canonical family line per
  impulse per horizon.  Multiple horizons can be supplied.

Public API
----------
- :func:`projections_from_angle_families` — primary function.

References
----------
signals/projections.py — Projection dataclass
modules/adjusted_angles.py — compute_impulse_angles, angle_deg_to_slope,
    get_angle_families
CLAUDE.md — Phase 4 generator spec (optional angle families)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from modules.adjusted_angles import angle_deg_to_slope, get_angle_families
from signals.projections import PriceBand, Projection, TimeBand

logger = logging.getLogger(__name__)

_MODULE_NAME = "angle_families"
_DEFAULT_BAND_PCT = 0.01       # ±1% price band
_DEFAULT_HORIZONS = [90]       # bars to project forward (conservative MVP)
_QUALITY_DECAY_PER_DEG = 0.1   # score decay per degree of family deviation


def projections_from_angle_families(
    impulse_angles: List[Dict[str, Any]],
    scale_basis: Dict[str, Any],
    band_pct: float = _DEFAULT_BAND_PCT,
    horizons: Optional[List[int]] = None,
) -> List[Projection]:
    """Convert impulse angle records to angle-family price projections.

    For each impulse that has been bucketed to a recognised angle family,
    projects price targets along all canonical Jenkins fan lines from the
    impulse extreme price at the specified horizon(s).

    Parameters
    ----------
    impulse_angles:
        List of dicts as returned by
        :func:`~modules.adjusted_angles.compute_impulse_angles`.  Each dict
        must have at minimum: ``impulse_id``, ``extreme_price``, ``delta_p``,
        ``quality_score`` (or defaults to 0.5), and the angle fields
        ``angle_family``, ``angle_family_delta_deg``.
    scale_basis:
        Dict from ``core.coordinate_system.get_angle_scale_basis()``.
        Must contain ``"price_per_bar"`` as a positive float.
    band_pct:
        Fractional price band half-width.  Default 0.01 (1%).
        Must be >= 0.
    horizons:
        List of horizon distances in bars.  Default ``[90]``.  Each
        horizon produces one Projection per canonical family line per
        impulse.  Must be positive integers.

    Returns
    -------
    List of :class:`~signals.projections.Projection` objects.  Impulses
    without a recognised angle family are skipped.

    Raises
    ------
    ValueError
        If ``band_pct < 0`` or any horizon is <= 0.
    """
    if band_pct < 0:
        raise ValueError(f"band_pct must be >= 0; got {band_pct}.")

    if horizons is None:
        horizons = list(_DEFAULT_HORIZONS)
    for h in horizons:
        if h <= 0:
            raise ValueError(f"All horizons must be > 0; got {h}.")

    families = get_angle_families()
    projections: List[Projection] = []

    for imp in impulse_angles:
        d = imp if isinstance(imp, dict) else (
            imp.to_dict() if hasattr(imp, "to_dict") else dict(imp)
        )

        # Only process impulses with a recognised angle family
        angle_family = d.get("angle_family")
        if angle_family is None:
            continue

        source_id = str(d.get("impulse_id", "unknown"))
        extreme_price = d.get("extreme_price")
        if extreme_price is None:
            continue
        extreme_price = float(extreme_price)
        if extreme_price <= 0:
            continue

        delta_p = float(d.get("delta_p", 0.0))
        quality_score = float(d.get("quality_score", 0.5))
        family_delta_deg = float(d.get("angle_family_delta_deg", 0.0))

        # Determine impulse direction: positive delta_p = upward impulse
        is_upward = delta_p >= 0

        # Score decay: tighter angle match → higher score
        base_score = max(0.1, min(1.0, quality_score))
        match_penalty = max(0.0, 1.0 - _QUALITY_DECAY_PER_DEG * abs(family_delta_deg))
        raw_score = max(0.1, min(1.0, base_score * match_penalty))

        # Project along each canonical family line at each horizon
        for fam in families:
            fam_angle = float(fam["angle_deg"])
            fam_name = fam["name"]

            for horizon in horizons:
                # For upward impulses: project upward fan lines with positive
                # angles, and downward fan lines with negative angles.
                # For downward impulses: negate to project in the correct
                # direction.
                for sign, direction_label in [(1, "up"), (-1, "down")]:
                    if not is_upward:
                        effective_sign = -sign
                    else:
                        effective_sign = sign

                    try:
                        slope = angle_deg_to_slope(
                            fam_angle * effective_sign, scale_basis
                        )
                    except ValueError:
                        continue

                    target_price = extreme_price + slope * horizon
                    if target_price <= 0:
                        continue

                    price_band: PriceBand = (
                        target_price * (1.0 - band_pct),
                        target_price * (1.0 + band_pct),
                    )
                    time_band: TimeBand = (None, None)

                    # Direction hint
                    if target_price > extreme_price:
                        direction_hint = "resistance"
                    elif target_price < extreme_price:
                        direction_hint = "support"
                    else:
                        direction_hint = "ambiguous"

                    metadata: dict = {
                        "angle_family": fam_name,
                        "fan_direction": direction_label,
                        "family_angle_deg": fam_angle * effective_sign,
                        "horizon_bars": horizon,
                        "extreme_price": extreme_price,
                        "impulse_family": angle_family,
                        "impulse_family_delta_deg": family_delta_deg,
                        "impulse_direction": "up" if is_upward else "down",
                    }

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
        "projections_from_angle_families: %d impulse angle(s) → %d projections.",
        len(impulse_angles),
        len(projections),
    )
    return projections
