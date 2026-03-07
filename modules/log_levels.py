"""
modules/log_levels.py

Canonical log-price conversion helpers used across Phase 3 modules.

Purpose
-------
Provide a single, authoritative implementation of log-price arithmetic so
that every Phase 3 module uses identical conventions.  Prevents silent
drift between modules that each define their own ``log(p)`` formulas.

Conventions
-----------
All logarithms are **natural** (base *e*).  This matches the convention used
in:

- ``modules/impulse.py`` — ``slope_log = log(extreme / origin) / delta_t``
- ``modules/adjusted_angles.py`` — log-mode angle uses
  ``log(extreme / origin)`` as the log-space price difference and
  ``log(1 + ppb / origin_price)`` as the per-bar log scale basis.

Function signatures mirror the above usage patterns exactly so callers can
replace inline expressions with these helpers without changing results.

Gap policy
----------
These helpers operate on scalar price and bar-count values; they require no
DataFrame access.  Gap-safety is the responsibility of the calling module
(which must use bar-index deltas from the :class:`~modules.impulse.Impulse`
object rather than calendar-day spans).

Known limitations
-----------------
- ``log_price(0)`` and ``log_price`` of any non-positive value raises
  ``ValueError`` (log is undefined for p ≤ 0).
- ``log_return`` with ``p0 ≤ 0`` or ``p1 ≤ 0`` raises ``ValueError``.
- ``log_slope`` with ``delta_t = 0`` raises ``ValueError``.
- ``log_slope`` with ``p0 + delta_p ≤ 0`` raises ``ValueError`` (the
  implied end-price is non-positive; log is undefined).

References
----------
ASSUMPTIONS.md — Assumptions 21–22 (log-mode angle basis)
modules/adjusted_angles.py — log-mode angle computation
modules/impulse.py — slope_log field
"""

from __future__ import annotations

import math
import logging

logger = logging.getLogger(__name__)


# ── Primary API ───────────────────────────────────────────────────────────────


def log_price(p: float) -> float:
    """Return the natural log of price *p*.

    Parameters
    ----------
    p:
        Price value.  Must be > 0.

    Returns
    -------
    ``math.log(p)``

    Raises
    ------
    ValueError
        If ``p <= 0``.
    """
    if p <= 0:
        raise ValueError(f"log_price: p must be > 0; got {p}.")
    return math.log(p)


def log_return(p0: float, p1: float) -> float:
    """Return the natural log return from price *p0* to price *p1*.

    Formula::

        log_return = log(p1 / p0)

    This is the log-space equivalent of the signed move from *p0* to *p1*.
    Positive when p1 > p0 (upward move); negative when p1 < p0 (downward).

    Matches the convention in ``modules/impulse.py`` (``slope_log`` numerator)
    and ``modules/adjusted_angles.py`` (log-mode ``log_delta_p``).

    Parameters
    ----------
    p0:
        Starting price.  Must be > 0.
    p1:
        Ending price.  Must be > 0.

    Returns
    -------
    ``math.log(p1 / p0)``

    Raises
    ------
    ValueError
        If ``p0 <= 0`` or ``p1 <= 0``.
    """
    if p0 <= 0:
        raise ValueError(f"log_return: p0 must be > 0; got {p0}.")
    if p1 <= 0:
        raise ValueError(f"log_return: p1 must be > 0; got {p1}.")
    return math.log(p1 / p0)


def log_slope(delta_p: float, p0: float, delta_t: int) -> float:
    """Return the log-space slope (log return per bar).

    Formula::

        log_slope = log(1 + delta_p / p0) / delta_t
                  = log((p0 + delta_p) / p0) / delta_t

    This is identical to the ``slope_log`` field stored on
    :class:`~modules.impulse.Impulse` objects::

        slope_log = log(extreme_price / origin_price) / delta_t

    and is consistent with the log-mode assumption in
    ``modules/adjusted_angles.py`` (Assumption 21).

    Parameters
    ----------
    delta_p:
        Signed price difference: ``extreme_price - origin_price``.
    p0:
        Origin price.  Must be > 0.
    delta_t:
        Bar count from origin to extreme.  Must be non-zero.

    Returns
    -------
    Log return per bar (float).  Positive for upward moves; negative for
    downward moves.

    Raises
    ------
    ValueError
        - If ``p0 <= 0``.
        - If ``delta_t == 0``.
        - If ``p0 + delta_p <= 0`` (implied end-price is non-positive).
    """
    if p0 <= 0:
        raise ValueError(f"log_slope: p0 must be > 0; got {p0}.")
    if delta_t == 0:
        raise ValueError("log_slope: delta_t must be non-zero.")
    p1 = p0 + delta_p
    if p1 <= 0:
        raise ValueError(
            f"log_slope: implied end-price p0 + delta_p = {p1} must be > 0."
        )
    return math.log(p1 / p0) / delta_t


def log_scale_basis(price_per_bar: float, origin_price: float) -> float:
    """Return the log-space price-per-bar for a given origin price.

    This is the per-impulse log scale basis used in the Phase 3A log-mode
    angle computation (Assumption 21)::

        log_ppb = log(1 + price_per_bar / origin_price)

    It answers: "what log return corresponds to one ``price_per_bar`` move
    from ``origin_price``?"

    Parameters
    ----------
    price_per_bar:
        Raw (linear) price-per-bar scale, e.g. the median ATR-14 from
        ``core.coordinate_system.get_angle_scale_basis()``.  Must be > 0.
    origin_price:
        Origin price.  Must be > 0.

    Returns
    -------
    Log-space equivalent of one ``price_per_bar`` move (float, > 0).

    Raises
    ------
    ValueError
        If ``price_per_bar <= 0`` or ``origin_price <= 0``.
    """
    if price_per_bar <= 0:
        raise ValueError(
            f"log_scale_basis: price_per_bar must be > 0; got {price_per_bar}."
        )
    if origin_price <= 0:
        raise ValueError(
            f"log_scale_basis: origin_price must be > 0; got {origin_price}."
        )
    return math.log(1.0 + price_per_bar / origin_price)
