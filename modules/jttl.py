"""
modules/jttl.py

Jenkins Theoretical Target Level (JTTL) module.

Purpose
-------
Compute a straight "theoretical target level" line from an origin price
over a defined horizon.  The endpoint price is derived from a square-root
price transform, reflecting the Jenkins technique of working in sqrt-price
space to project future price levels.

Formula
-------
The theoretical target price at the horizon endpoint is::

    p1 = (sqrt(p0) + k) ** 2

where ``p0`` is the origin price and ``k`` is a configurable additive
increment in sqrt-price space (default ``k = 2.0``).

The JTTL line is a straight line from ``(t0, p0)`` to ``(t1, p1)``::

    price(t) = p0 + slope_raw * days_elapsed(t)
    slope_raw = (p1 - p0) / horizon_days

where ``days_elapsed(t) = (t - t0).total_seconds() / 86400.0`` and
``horizon_days`` is the calendar-day length of the horizon.

Time basis: price per calendar day
-----------------------------------
``slope_raw`` and ``intercept_raw`` are expressed in **price per
calendar day** (not price per bar).  For 24/7 crypto this is the natural
continuous-time choice: there are no market-closure gaps, so calendar days
and trading days coincide for daily data.

"One Year" horizon mapping for crypto
---------------------------------------
The default horizon is **365 calendar days in UTC**.

For a traditional equity market, "one year" might be 252 trading days.
BTC/USD (and crypto generally) trades 24/7 with no exchange closures, so
every calendar day is a trading day.  Using 365 calendar days accurately
captures "one year" of continuous crypto exposure without any trading-day
adjustment.

Alternate horizon: N daily bars
--------------------------------
If ``horizon_bars`` is supplied, the horizon is ``horizon_bars`` calendar
days (one 1D bar = one calendar day for the primary MVP timeframe).  For a
gapless daily dataset this is equivalent to the default 365-day mode when
``horizon_bars=365``.  Set ``basis="bars"`` on the returned ``JTTLLine``
to signal which mode was active.

Inputs
------
- origin_time (pd.Timestamp, UTC)
- origin_price (float, > 0)
- k (float, default 2.0)
- horizon_days (int, default 365)
- horizon_bars (Optional[int], overrides horizon_days when given)

Outputs
-------
- ``JTTLLine`` object (see class docstring)

Assumptions
-----------
- Assumption 23 (ASSUMPTIONS.md): JTTL horizon = 365 calendar days UTC for
  crypto (24/7 market, no exchange closures).  One daily bar = one calendar
  day.  k = 2.0 is the default additive sqrt-price increment.

Known limitations
-----------------
- The JTTL line is a linear interpolation / extrapolation in price space,
  not in sqrt-price space.  Projecting beyond ``t1`` is valid mathematically
  but has no grounding in the Jenkins framework.
- ``k = 2.0`` is the default empirical choice.  Its optimal value is an
  open research question (see ASSUMPTIONS.md Assumption 23).
- No confluence or confirmation logic is applied here (Phase 4+).

References
----------
ASSUMPTIONS.md — Assumption 23
DECISIONS.md   — 2026-03-07 Phase 3B.1 JTTL horizon decision
docs/phase0_builder_output.md — "JTTL exact root-transform formula" (Phase 3)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Default "one year" in calendar days for 24/7 crypto
_CALENDAR_DAYS_PER_YEAR: int = 365


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class JTTLLine:
    """A Jenkins Theoretical Target Level line from origin to horizon.

    The line connects ``(t0, p0)`` and ``(t1, p1)`` linearly in price space.
    It can be evaluated at any timestamp or price level via the helper
    methods ``price_at`` and ``time_at_price``.

    Fields
    ------
    t0 : pd.Timestamp
        Origin time (UTC, timezone-aware).
    p0 : float
        Origin price.
    t1 : pd.Timestamp
        Horizon endpoint time (UTC) = t0 + horizon_days calendar days.
    p1 : float
        Theoretical target price: ``(sqrt(p0) + k) ** 2``.
    k : float
        Additive increment in sqrt-price space used to compute p1.
    horizon_days : float
        Calendar-day length of the horizon (t0 → t1).
    horizon_bars : Optional[int]
        Non-None when the horizon was specified as a bar count.  For 1D
        data, ``horizon_bars == horizon_days`` (one bar = one calendar day).
    slope_raw : float
        Price change per calendar day: ``(p1 - p0) / horizon_days``.
        Units: **price per calendar day**.
    intercept_raw : float
        Price at ``t0`` (equals ``p0``).  Line equation::

            price = intercept_raw + slope_raw * days_elapsed

        where ``days_elapsed = (t - t0).total_seconds() / 86400``.
    basis : str
        ``"calendar_days"`` or ``"bars"`` — which time system set the
        horizon length.
    """

    t0: pd.Timestamp
    p0: float
    t1: pd.Timestamp
    p1: float
    k: float
    horizon_days: float
    horizon_bars: Optional[int]
    slope_raw: float
    intercept_raw: float
    basis: str

    # ── Helpers ────────────────────────────────────────────────────────────

    def price_at(self, t: pd.Timestamp) -> float:
        """Return the JTTL line price at timestamp *t*.

        Uses linear interpolation / extrapolation from ``(t0, p0)`` to
        ``(t1, p1)``.  Valid for any ``t``; extrapolation beyond ``t1`` is
        mathematically valid but has no Jenkins framework backing.

        Parameters
        ----------
        t:
            Timestamp (UTC, timezone-aware).

        Returns
        -------
        Estimated price on the JTTL line at time *t*.
        """
        days = (t - self.t0).total_seconds() / 86400.0
        return self.intercept_raw + self.slope_raw * days

    def time_at_price(self, p: float) -> Optional[pd.Timestamp]:
        """Return the timestamp where the JTTL line crosses price *p*.

        Parameters
        ----------
        p:
            Target price level.

        Returns
        -------
        UTC timestamp of the JTTL line crossing *p*, or ``None`` if
        ``slope_raw == 0`` (flat line — cannot solve for time).
        """
        if self.slope_raw == 0.0:
            return None
        days = (p - self.intercept_raw) / self.slope_raw
        return self.t0 + pd.Timedelta(days=days)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        return {
            "t0": str(self.t0),
            "p0": self.p0,
            "t1": str(self.t1),
            "p1": self.p1,
            "k": self.k,
            "horizon_days": self.horizon_days,
            "horizon_bars": self.horizon_bars,
            "slope_raw": self.slope_raw,
            "intercept_raw": self.intercept_raw,
            "basis": self.basis,
        }


# ── Primary API ───────────────────────────────────────────────────────────────


def theoretical_price(origin_price: float, k: float = 2.0) -> float:
    """Compute the JTTL theoretical target price.

    Formula::

        p1 = (sqrt(origin_price) + k) ** 2

    Parameters
    ----------
    origin_price:
        Origin price.  Must be >= 0.
    k:
        Additive increment in sqrt-price space.  Default 2.0.

    Returns
    -------
    Theoretical target price.

    Raises
    ------
    ValueError
        If ``origin_price < 0``.
    """
    if origin_price < 0:
        raise ValueError(
            f"origin_price must be >= 0; got {origin_price}."
        )
    return (math.sqrt(origin_price) + k) ** 2


def compute_jttl(
    origin_time: pd.Timestamp,
    origin_price: float,
    k: float = 2.0,
    horizon_days: int = _CALENDAR_DAYS_PER_YEAR,
    horizon_bars: Optional[int] = None,
) -> JTTLLine:
    """Compute a JTTL line from an origin time and price.

    Parameters
    ----------
    origin_time:
        Origin timestamp (UTC, timezone-aware).
    origin_price:
        Origin price.  Must be > 0 (a price of 0 is undefined for the
        sqrt transform).
    k:
        Additive increment in sqrt-price space.  Default 2.0.
    horizon_days:
        Calendar-day horizon length.  Default 365 (one year for 24/7
        crypto; see module docstring).  Ignored when ``horizon_bars`` is
        supplied.
    horizon_bars:
        If given, overrides ``horizon_days``.  Interpreted as N daily
        bars; one bar = one calendar day for 1D data.  Sets
        ``JTTLLine.basis = "bars"``.

    Returns
    -------
    JTTLLine

    Raises
    ------
    ValueError
        - If ``origin_price <= 0``.
        - If ``horizon_days <= 0`` and ``horizon_bars`` is None.
        - If ``horizon_bars`` is given and ``horizon_bars <= 0``.
    """
    if origin_price <= 0:
        raise ValueError(
            f"origin_price must be > 0 for the JTTL sqrt transform; "
            f"got {origin_price}."
        )

    # ── Resolve horizon ────────────────────────────────────────────────────
    if horizon_bars is not None:
        if horizon_bars <= 0:
            raise ValueError(
                f"horizon_bars must be > 0; got {horizon_bars}."
            )
        active_horizon_days: float = float(horizon_bars)
        basis = "bars"
    else:
        if horizon_days <= 0:
            raise ValueError(
                f"horizon_days must be > 0; got {horizon_days}."
            )
        active_horizon_days = float(horizon_days)
        basis = "calendar_days"

    # ── Compute endpoint ───────────────────────────────────────────────────
    p1 = theoretical_price(origin_price, k=k)
    t1 = origin_time + pd.Timedelta(days=active_horizon_days)

    # ── Line parameters ────────────────────────────────────────────────────
    #   slope_raw : price per calendar day
    #   intercept_raw : price at t0 (= p0)
    slope_raw = (p1 - origin_price) / active_horizon_days
    intercept_raw = origin_price

    jttl = JTTLLine(
        t0=origin_time,
        p0=origin_price,
        t1=t1,
        p1=p1,
        k=k,
        horizon_days=active_horizon_days,
        horizon_bars=horizon_bars,
        slope_raw=slope_raw,
        intercept_raw=intercept_raw,
        basis=basis,
    )

    logger.debug(
        "compute_jttl: p0=%.4f k=%.4f p1=%.4f horizon=%s=%.1f "
        "slope_raw=%.6f basis=%s",
        origin_price, k, p1,
        "bars" if horizon_bars is not None else "days",
        active_horizon_days, slope_raw, basis,
    )

    return jttl
