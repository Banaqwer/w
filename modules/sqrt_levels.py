"""
modules/sqrt_levels.py

Square-root horizontal price level module.

Purpose
-------
Generate a set of horizontal price levels derived from the Jenkins
square-root method.  Given an origin price ``p0``, levels are placed at::

    level_price = (sqrt(p0) + increment * step) ** 2      # upward
    level_price = (sqrt(p0) - increment * step) ** 2      # downward

where ``increment`` is one of the configured step sizes and ``step`` runs
from 1 to ``steps`` (inclusive).

This is the classical Jenkins "square-root of the price" horizontal grid —
equally spaced in sqrt-price space, which maps to unequal but self-similar
intervals in price space.

Formula
-------
Given ``sqrt_base = sqrt(origin_price)``::

    up_level(inc, n)   = (sqrt_base + inc * n) ** 2   for n = 1..steps
    down_level(inc, n) = (sqrt_base - inc * n) ** 2   for n = 1..steps
                         (clamped: sqrt_base - inc * n must be >= 0)

The label format is ``"+{inc}×{n}"`` for upward levels and
``"-{inc}×{n}"`` for downward levels.

Inputs
------
- origin_price (float, > 0)
- increments (list of float, default [0.25, 0.5, 0.75, 1.0])
- steps (int, default 8) — how many steps per increment per direction
- direction (str, one of "up", "down", "both") — which side(s) to generate

Outputs
-------
- List of :class:`SqrtLevel` objects, sorted by level_price ascending.

Assumptions
-----------
- Assumption 24 (ASSUMPTIONS.md): Sqrt levels are equally spaced in
  sqrt-price space.  The default increments [0.25, 0.5, 0.75, 1.0] are
  provisional; optimal spacing is a research question.
- Down-levels where ``sqrt_base - inc * n < 0`` are silently skipped
  (negative sqrt-price has no meaning).

Known limitations
-----------------
- Levels are horizontal (time-invariant); they carry no directional or
  time-based information.
- No confluence or confirmation logic is applied here (Phase 4+).

References
----------
ASSUMPTIONS.md — Assumption 24
DECISIONS.md   — 2026-03-07 Phase 3B.1 sqrt levels decision
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

# Default configuration
_DEFAULT_INCREMENTS: List[float] = [0.25, 0.5, 0.75, 1.0]
_DEFAULT_STEPS: int = 8
_VALID_DIRECTIONS = frozenset({"up", "down", "both"})


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class SqrtLevel:
    """A single Jenkins square-root horizontal price level.

    Fields
    ------
    level_price : float
        The horizontal price level: ``(sqrt(origin_price) + increment * step) ** 2``
        for upward levels; ``(sqrt(origin_price) - increment * step) ** 2`` for
        downward levels.
    increment_used : float
        The sqrt-space increment used to derive this level.
    step : int
        Which multiple of the increment this level is at (1-based).
    direction : str
        ``"up"`` or ``"down"``.
    label : str
        Human-readable label, e.g. ``"+1.0×1"`` or ``"-0.5×2"``.
    """

    level_price: float
    increment_used: float
    step: int
    direction: str
    label: str

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        return {
            "level_price": self.level_price,
            "increment_used": self.increment_used,
            "step": self.step,
            "direction": self.direction,
            "label": self.label,
        }


# ── Primary API ───────────────────────────────────────────────────────────────


def sqrt_levels(
    origin_price: float,
    increments: List[float] = _DEFAULT_INCREMENTS,
    steps: int = _DEFAULT_STEPS,
    direction: str = "both",
) -> List[SqrtLevel]:
    """Generate Jenkins square-root horizontal price levels.

    Parameters
    ----------
    origin_price:
        Origin price.  Must be > 0.
    increments:
        List of additive sqrt-space step sizes.  Each value produces its
        own set of levels.  Default ``[0.25, 0.5, 0.75, 1.0]``.
    steps:
        Number of steps per increment per direction (1-based).
        Default 8.
    direction:
        Which side(s) to generate: ``"up"``, ``"down"``, or ``"both"``.
        Default ``"both"``.

    Returns
    -------
    List of :class:`SqrtLevel` objects sorted by ``level_price`` ascending.
    Duplicate price levels (from different increment/step combinations that
    happen to produce the same price) are all included.

    Raises
    ------
    ValueError
        - If ``origin_price <= 0``.
        - If ``steps <= 0``.
        - If ``direction`` is not ``"up"``, ``"down"``, or ``"both"``.
        - If any value in ``increments`` is <= 0.
    """
    if origin_price <= 0:
        raise ValueError(
            f"origin_price must be > 0 for sqrt levels; got {origin_price}."
        )
    if steps <= 0:
        raise ValueError(f"steps must be > 0; got {steps}.")
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_VALID_DIRECTIONS)!r}; "
            f"got {direction!r}."
        )
    if not increments:
        raise ValueError("increments must be a non-empty list.")
    for inc in increments:
        if inc <= 0:
            raise ValueError(
                f"All increments must be > 0; got {inc}."
            )

    sqrt_base = math.sqrt(origin_price)
    results: List[SqrtLevel] = []

    for inc in increments:
        # ── Upward levels ─────────────────────────────────────────────────
        if direction in ("up", "both"):
            for n in range(1, steps + 1):
                val = sqrt_base + inc * n
                level_price = val * val
                inc_str = f"{inc:g}"
                label = f"+{inc_str}×{n}"
                results.append(
                    SqrtLevel(
                        level_price=level_price,
                        increment_used=inc,
                        step=n,
                        direction="up",
                        label=label,
                    )
                )

        # ── Downward levels ───────────────────────────────────────────────
        if direction in ("down", "both"):
            for n in range(1, steps + 1):
                val = sqrt_base - inc * n
                if val < 0.0:
                    # sqrt-price would be negative — physically meaningless
                    logger.debug(
                        "sqrt_levels: skipping down level inc=%g step=%d "
                        "(sqrt_base=%.6f, val=%.6f < 0)",
                        inc, n, sqrt_base, val,
                    )
                    break  # further steps will also be negative; stop early
                level_price = val * val
                inc_str = f"{inc:g}"
                label = f"-{inc_str}×{n}"
                results.append(
                    SqrtLevel(
                        level_price=level_price,
                        increment_used=inc,
                        step=n,
                        direction="down",
                        label=label,
                    )
                )

    results.sort(key=lambda s: s.level_price)

    logger.debug(
        "sqrt_levels: origin_price=%.4f steps=%d direction=%r "
        "increments=%r → %d levels",
        origin_price, steps, direction, increments, len(results),
    )

    return results
