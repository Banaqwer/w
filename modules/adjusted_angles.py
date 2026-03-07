"""
modules/adjusted_angles.py

Jenkins-style adjusted-angle module.

Purpose
-------
Convert impulse slopes into stable, comparable angle measures using the
canonical price-per-bar scale basis from ``core.coordinate_system``.

Angle basis
-----------
"45 degrees" under this module corresponds to a price move equal to exactly
``scale_basis["price_per_bar"]`` per bar.  Formally::

    angle_deg = degrees(atan(delta_p / (delta_t * price_per_bar)))

When ``delta_p == delta_t * price_per_bar`` the result is exactly 45°.

The scale basis is computed once per dataset via
``core.coordinate_system.get_angle_scale_basis(df)`` and must be passed
into every function here.  No angle function computes its own scale basis.

Angle normalisation
-------------------
``normalize_angle`` maps any angle to the half-open interval (-90, 90]:

- Positive angles represent upward (bull) moves.
- Negative angles represent downward (bear) moves.
- 0° is horizontal; ±90° is vertical.

The mapping is ``a = (angle_deg % 180.0)``, then ``a -= 180.0`` if ``a > 90.0``,
so the convention is (-90, 90].

price_mode for compute_impulse_angles
---------------------------------------
- ``"raw"``: uses ``imp.delta_p / imp.delta_t`` (slope_raw) normalized by
  ``price_per_bar``.
- ``"log"``: uses ``log(extreme_price / origin_price)`` as the log-space price
  difference, normalized by ``log(1 + price_per_bar / origin_price) * delta_t``.
  This preserves the 45°-at-scale-basis invariant in log space on a per-impulse
  basis (Assumption 21).

Gap policy
----------
Angle computations operate on Impulse objects that already carry bar-index
deltas.  No raw DataFrame access is required.  For the 6H dataset
(missing_bar_count > 0), angles are computed using ``delta_t`` (bar-index
delta), which is gap-safe (Assumption 22).

References
----------
ASSUMPTIONS.md — Assumptions 14, 21, 22
DECISIONS.md — 2026-03-07 Phase 3 angle basis decision
core/coordinate_system.py — get_angle_scale_basis()
docs/phase0_builder_output.md — adjusted_angles.py stub
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Canonical Jenkins angle families ──────────────────────────────────────────
#
# Each entry: (price_units, time_units, family_name, exact_angle_deg)
#
# A "NxM" line moves N price-units per M time-units on the normalised chart,
# so its angle is atan(N / M) degrees.  The canonical set below covers the
# primary (1x1, 2x1, 1x2) and secondary (3x1, 1x3, 4x1, 1x4, 8x1, 1x8) lines.
#
_ANGLE_FAMILIES: List[tuple] = [
    (8, 1, "8x1", math.degrees(math.atan(8.0))),     # ≈ 82.875°
    (4, 1, "4x1", math.degrees(math.atan(4.0))),     # ≈ 75.964°
    (3, 1, "3x1", math.degrees(math.atan(3.0))),     # ≈ 71.565°
    (2, 1, "2x1", math.degrees(math.atan(2.0))),     # ≈ 63.435°
    (1, 1, "1x1", 45.0),                             # = 45.000°
    (1, 2, "1x2", math.degrees(math.atan(0.5))),     # ≈ 26.565°
    (1, 3, "1x3", math.degrees(math.atan(1.0 / 3))),# ≈ 18.435°
    (1, 4, "1x4", math.degrees(math.atan(0.25))),    # ≈ 14.036°
    (1, 8, "1x8", math.degrees(math.atan(0.125))),   # ≈  7.125°
]


# ── Primary API: single-impulse angle conversion ──────────────────────────────


def slope_to_angle_deg(
    delta_p: float,
    delta_t: int,
    scale_basis: Dict[str, Any],
) -> float:
    """Convert a raw price move to an adjusted angle in degrees.

    The formula is::

        angle = degrees(atan(delta_p / (delta_t * price_per_bar)))

    where ``price_per_bar = scale_basis["price_per_bar"]``.

    At exactly ``delta_p == delta_t * price_per_bar`` the result is 45°.
    Upward moves produce positive angles; downward moves produce negative angles.

    Parameters
    ----------
    delta_p:
        Signed price difference (``extreme_price - origin_price``).
    delta_t:
        Number of bars from origin to extreme.  Must be non-zero.
    scale_basis:
        Dict from ``core.coordinate_system.get_angle_scale_basis()``.
        Must contain ``"price_per_bar"`` as a positive float.

    Returns
    -------
    Angle in degrees, always in the open interval (-90, 90).
    Positive = upward move; negative = downward move.

    Raises
    ------
    ValueError
        If ``delta_t == 0`` or ``scale_basis["price_per_bar"] <= 0``.
    """
    if delta_t == 0:
        raise ValueError("delta_t must be non-zero for angle computation.")
    ppb = float(scale_basis["price_per_bar"])
    if ppb <= 0:
        raise ValueError(
            f"scale_basis['price_per_bar'] must be positive, got {ppb}."
        )
    normalized_slope = delta_p / (delta_t * ppb)
    return math.degrees(math.atan(normalized_slope))


def angle_deg_to_slope(
    angle_deg: float,
    scale_basis: Dict[str, Any],
) -> float:
    """Convert an adjusted angle back to a raw price slope (price per bar).

    This is the exact inverse of :func:`slope_to_angle_deg`::

        slope_raw = tan(radians(angle_deg)) * price_per_bar

    Parameters
    ----------
    angle_deg:
        Angle in degrees.  Must be strictly inside (-90, 90).
    scale_basis:
        Dict from ``core.coordinate_system.get_angle_scale_basis()``.
        Must contain ``"price_per_bar"`` as a positive float.

    Returns
    -------
    Raw slope in price-per-bar units.  Positive for upward; negative for downward.

    Raises
    ------
    ValueError
        If ``abs(angle_deg) >= 90`` (vertical slope is undefined) or
        ``scale_basis["price_per_bar"] <= 0``.
    """
    if abs(angle_deg) >= 90.0:
        raise ValueError(
            f"angle_deg must be in (-90, 90); got {angle_deg}.  "
            "Vertical slopes are undefined."
        )
    ppb = float(scale_basis["price_per_bar"])
    if ppb <= 0:
        raise ValueError(
            f"scale_basis['price_per_bar'] must be positive, got {ppb}."
        )
    return math.tan(math.radians(angle_deg)) * ppb


def normalize_angle(angle_deg: float) -> float:
    """Normalise an angle to the half-open interval (-90, 90].

    Mapping rule:

    - Angles already in (-90, 90] are returned unchanged.
    - All other values are reduced by successive additions/subtractions of 180°
      until the value falls in (-90, 90].

    Concretely: the formula is ``a = angle_deg % 180.0``, then
    ``a -= 180.0`` if ``a > 90.0``, giving the interval (-90, 90].

    Examples::

        normalize_angle(135.0)  → -45.0
        normalize_angle(-135.0) → 45.0
        normalize_angle(180.0)  → 0.0
        normalize_angle(90.0)   → 90.0
        normalize_angle(-90.0)  → 90.0

    Parameters
    ----------
    angle_deg:
        Input angle in degrees (any real value).

    Returns
    -------
    Normalised angle in (-90, 90].
    """
    a = angle_deg % 180.0   # → [0, 180)
    if a > 90.0:
        a -= 180.0           # → (-90, 0]
    return a


# ── Angle family utilities ─────────────────────────────────────────────────────


def get_angle_families() -> List[Dict[str, Any]]:
    """Return the canonical list of Jenkins angle families as a list of dicts.

    Each dict has keys:
    - ``"name"``: family label, e.g. ``"1x1"``, ``"2x1"``
    - ``"price_ratio"``: price units in the NxM notation
    - ``"time_ratio"``: time units in the NxM notation
    - ``"angle_deg"``: exact angle in degrees (always positive; direction is
      carried by the sign of the impulse's delta_p)

    Returns
    -------
    List of dicts, one per angle family, sorted by angle_deg descending.
    """
    return [
        {
            "name": name,
            "price_ratio": p,
            "time_ratio": t,
            "angle_deg": a,
        }
        for p, t, name, a in _ANGLE_FAMILIES
    ]


def bucket_angle_to_family(
    angle_deg: float,
    tolerance_deg: float = 5.0,
) -> Optional[Dict[str, Any]]:
    """Find the closest Jenkins angle family within tolerance.

    The comparison is done on the **absolute** value of the input angle so
    that both upward (+) and downward (-) impulses are bucketed against the
    same positive family angles.

    Parameters
    ----------
    angle_deg:
        Normalised angle in degrees (typically from :func:`normalize_angle`).
    tolerance_deg:
        Maximum allowed deviation (in degrees) from a family's centre angle.
        Default is 5°.

    Returns
    -------
    Dict with keys ``"name"``, ``"family_angle_deg"``, ``"input_angle_deg"``,
    ``"delta_deg"`` for the closest family within tolerance, or ``None`` if
    no family is within tolerance.

    ``"family_angle_deg"`` carries the same sign as the input angle so callers
    can compare directly without re-applying direction.
    """
    abs_angle = abs(angle_deg)
    sign = 1 if angle_deg >= 0 else -1

    best: Optional[Dict[str, Any]] = None
    best_delta = float("inf")

    for _p, _t, name, family_deg in _ANGLE_FAMILIES:
        delta = abs(abs_angle - family_deg)
        if delta < best_delta and delta <= tolerance_deg:
            best_delta = delta
            best = {
                "name": name,
                "family_angle_deg": family_deg * sign,
                "input_angle_deg": angle_deg,
                "delta_deg": best_delta,
            }

    return best


def are_angles_congruent(
    angle_a: float,
    angle_b: float,
    tolerance_deg: float = 5.0,
) -> bool:
    """Return ``True`` if two angles are within *tolerance_deg* of each other.

    Both angles should already be normalised (via :func:`normalize_angle`) so
    that direction-agnostic comparison is possible.  If you want a
    direction-sensitive comparison, pass the raw signed angles.

    Parameters
    ----------
    angle_a, angle_b:
        Angles in degrees.
    tolerance_deg:
        Maximum allowed absolute difference for congruence.  Default 5°.

    Returns
    -------
    ``True`` if ``abs(angle_a - angle_b) <= tolerance_deg``.
    """
    return abs(angle_a - angle_b) <= tolerance_deg


# ── Batch processing ──────────────────────────────────────────────────────────


def compute_impulse_angles(
    impulses: List[Any],
    scale_basis: Dict[str, Any],
    price_mode: str = "raw",
    family_tolerance_deg: float = 5.0,
) -> List[Dict[str, Any]]:
    """Compute adjusted angles for a list of impulses.

    Accepts either :class:`~modules.impulse.Impulse` objects or plain dicts
    (e.g. rows loaded from a CSV or JSON).  Returns a list of dicts that
    contains all original impulse fields plus the computed angle fields.

    Added fields
    ------------
    - ``angle_deg``: primary angle in degrees (per ``price_mode``).
    - ``angle_deg_raw``: angle computed from the raw slope (``delta_p / delta_t``),
      always included regardless of ``price_mode``.
    - ``angle_deg_log``: angle computed from the log slope
      (``log(extreme_price / origin_price) / delta_t``), always included when
      both prices are positive and non-zero.  ``None`` if not computable.
    - ``angle_normalized``: :func:`normalize_angle` applied to ``angle_deg``.
    - ``angle_family``: name of the closest Jenkins family within
      *family_tolerance_deg*, or ``None``.
    - ``angle_family_deg``: signed centre angle of that family, or ``None``.
    - ``angle_family_delta_deg``: absolute deviation from the family centre,
      or ``None``.

    Parameters
    ----------
    impulses:
        List of :class:`~modules.impulse.Impulse` objects or plain dicts
        with at minimum the fields ``delta_p``, ``delta_t``, ``origin_price``,
        ``extreme_price``.
    scale_basis:
        Dict from ``core.coordinate_system.get_angle_scale_basis()``.
    price_mode:
        ``"raw"`` (default) or ``"log"``.  Controls which slope is used as
        the primary angle.
    family_tolerance_deg:
        Tolerance forwarded to :func:`bucket_angle_to_family`.

    Returns
    -------
    List of dicts, one per input impulse, with all original fields plus the
    angle fields listed above.

    Notes
    -----
    - Impulses with ``delta_t <= 0`` are skipped with a warning; they are
      not included in the output.
    - Log-mode angle uses a per-impulse log scale basis::

          log_ppb_per_bar = log(1 + price_per_bar / origin_price)
          angle_deg_log   = degrees(atan(
              log(extreme / origin) / (delta_t * log_ppb_per_bar)
          ))

      This preserves the 45°-at-scale-basis invariant in log space
      (Assumption 21).
    """
    if price_mode not in ("raw", "log"):
        raise ValueError(f"price_mode must be 'raw' or 'log'; got {price_mode!r}.")

    results: List[Dict[str, Any]] = []
    ppb = float(scale_basis["price_per_bar"])
    skipped = 0

    for imp in impulses:
        d = imp.to_dict() if hasattr(imp, "to_dict") else dict(imp)

        delta_t = int(d.get("delta_t", 0))
        if delta_t <= 0:
            logger.warning(
                "compute_impulse_angles: skipping impulse_id=%r with delta_t=%d.",
                d.get("impulse_id"),
                delta_t,
            )
            skipped += 1
            continue

        delta_p = float(d.get("delta_p", 0.0))
        origin_price = float(d.get("origin_price", 0.0))
        extreme_price = float(d.get("extreme_price", 0.0))

        # ── Raw angle (always computed) ──────────────────────────────────────
        angle_raw = slope_to_angle_deg(delta_p, delta_t, scale_basis)

        # ── Log angle ────────────────────────────────────────────────────────
        angle_log: Optional[float] = None
        if origin_price > 0 and extreme_price > 0:
            log_delta_p = math.log(extreme_price / origin_price)
            # Log-space scale basis: log return equivalent of one price_per_bar
            # move from origin_price (Assumption 21).
            log_ppb = math.log(1.0 + ppb / origin_price)
            if log_ppb > 0:
                angle_log = math.degrees(math.atan(log_delta_p / (delta_t * log_ppb)))

        # ── Primary angle per price_mode ────────────────────────────────────
        if price_mode == "log" and angle_log is not None:
            angle_primary = angle_log
        else:
            if price_mode == "log":
                logger.debug(
                    "compute_impulse_angles: impulse_id=%r cannot compute log angle "
                    "(origin_price=%.4f, extreme_price=%.4f); falling back to raw.",
                    d.get("impulse_id"),
                    origin_price,
                    extreme_price,
                )
            angle_primary = angle_raw

        angle_norm = normalize_angle(angle_primary)
        family_result = bucket_angle_to_family(angle_norm, tolerance_deg=family_tolerance_deg)

        d["angle_deg"] = angle_primary
        d["angle_deg_raw"] = angle_raw
        d["angle_deg_log"] = angle_log
        d["angle_normalized"] = angle_norm
        d["angle_family"] = family_result["name"] if family_result else None
        d["angle_family_deg"] = family_result["family_angle_deg"] if family_result else None
        d["angle_family_delta_deg"] = family_result["delta_deg"] if family_result else None

        results.append(d)

    if skipped > 0:
        logger.info(
            "compute_impulse_angles: skipped %d impulse(s) with delta_t <= 0.",
            skipped,
        )

    logger.info(
        "compute_impulse_angles: produced %d angle record(s) from %d input(s) "
        "(price_mode=%r).",
        len(results),
        len(impulses),
        price_mode,
    )
    return results
