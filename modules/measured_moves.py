"""
modules/measured_moves.py

Measured move projection module.

Purpose
-------
Given a structural impulse (origin → extreme price move), project forward
target prices at configurable multiples of the impulse magnitude.  The
targets are returned as structured objects; they are **not** trade signals
and carry no confirmation or confluence logic (Phase 4+).

Terminology
-----------
Extension target:
    A price level beyond the extreme in the same direction as the impulse.
    For an upward impulse, extensions are above the extreme.
    For a downward impulse, extensions are below the extreme.

Retracement target:
    A price level between the extreme and origin (or past the origin).
    For an upward impulse, retracements are below the extreme.
    For a downward impulse, retracements are above the extreme.

Formula (raw mode)
------------------
Given an impulse with signed ``delta_p = extreme_price - origin_price``:

- Extension at ratio r:    ``target = extreme_price + r * delta_p``
- Retracement at ratio r:  ``target = extreme_price - r * delta_p``

For an upward impulse (``delta_p > 0``):
- Extension ratio 1.0 projects the full move above the extreme.
- Retracement ratio 0.5 projects back 50% toward the origin.
- Retracement ratio 1.0 projects back to the origin.

Formula (log mode)
------------------
Let ``log_delta = log(extreme_price / origin_price)``.

- Extension at ratio r:    ``target = exp(log(extreme_price) + r * log_delta)``
- Retracement at ratio r:  ``target = exp(log(extreme_price) - r * log_delta)``

Log mode preserves percentage symmetry: an extension at 1.0 in log space is
the same percentage gain above the extreme as the gain from origin to extreme.

Gap policy
----------
This module operates on Impulse objects whose ``delta_t`` and
``delta_p`` fields are already gap-safe (bar-index derived, per
DECISIONS.md 2026-03-06).  No DataFrame access is needed.

Inputs
------
- Impulse objects (from ``modules/impulse.py`` Phase 2 output)
- Optional angle-family tags (from Phase 3A output; stored in notes if provided)
- ``ratios`` list (default ``[0.5, 1.0, 1.5, 2.0]``)
- ``mode``: ``"raw"`` (linear price space) or ``"log"`` (log price space)

Outputs
-------
- List of :class:`MeasuredMoveTarget` objects (NOT signals).

Known limitations
-----------------
- Raw-mode extension targets may produce negative prices for large downward
  impulses.  These are included with a note; callers should filter if needed.
- Log-mode handles zero and negative prices gracefully: targets with
  non-positive prices are skipped and logged.
- No time projection is included here; time counts are in
  ``modules/time_counts.py``.
- No confluence or confirmation logic (Phase 4+).

References
----------
CLAUDE.md — Phase 3 required MVP module 2 (measured moves)
docs/handoff/jenkins_quant_prd.md — Projection fields
ASSUMPTIONS.md — Assumption 25
modules/impulse.py — Impulse dataclass
modules/log_levels.py — log_return, log_price
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from modules.log_levels import log_return

logger = logging.getLogger(__name__)

# Valid ratios guard: silently skip non-positive ratios
_MIN_RATIO = 1e-9


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class MeasuredMoveTarget:
    """A single measured-move target derived from one impulse at one ratio.

    Fields
    ------
    impulse_id : str
        Propagated from the source :class:`~modules.impulse.Impulse`.
    ratio : float
        The multiple of the impulse magnitude used for this target.
    target_price : float
        Projected target price.
    direction : str
        ``"extension"`` (beyond extreme in impulse direction) or
        ``"retracement"`` (back from extreme toward / past origin).
    mode : str
        ``"raw"`` or ``"log"`` — which formula was used.
    origin_price : float
        Origin price of the source impulse.
    origin_time : pd.Timestamp
        UTC timestamp of the origin bar.
    extreme_price : float
        Extreme price of the source impulse.
    extreme_time : pd.Timestamp
        UTC timestamp of the extreme bar.
    origin_bar_index : int
        ``bar_index`` of the origin bar.
    extreme_bar_index : int
        ``bar_index`` of the extreme bar.
    quality_score : float
        Quality score propagated from the source impulse.
    notes : str
        Free-text notes (e.g. angle-family tag, edge-case warnings).
    """

    impulse_id: str
    ratio: float
    target_price: float
    direction: str
    mode: str
    origin_price: float
    origin_time: pd.Timestamp
    extreme_price: float
    extreme_time: pd.Timestamp
    origin_bar_index: int
    extreme_bar_index: int
    quality_score: float
    notes: str

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "impulse_id": self.impulse_id,
            "ratio": self.ratio,
            "target_price": self.target_price,
            "direction": self.direction,
            "mode": self.mode,
            "origin_price": self.origin_price,
            "origin_time": str(self.origin_time),
            "extreme_price": self.extreme_price,
            "extreme_time": str(self.extreme_time),
            "origin_bar_index": self.origin_bar_index,
            "extreme_bar_index": self.extreme_bar_index,
            "quality_score": self.quality_score,
            "notes": self.notes,
        }


# ── Primary API ───────────────────────────────────────────────────────────────


def measured_move_targets(
    impulse: Any,
    ratios: List[float],
    mode: str = "raw",
    angle_family_tag: Optional[str] = None,
) -> List[MeasuredMoveTarget]:
    """Compute measured-move targets for one impulse at the given ratios.

    Both extension and retracement targets are produced for each ratio.

    Parameters
    ----------
    impulse:
        :class:`~modules.impulse.Impulse` object or plain dict with at
        minimum the fields: ``impulse_id``, ``delta_p``, ``origin_price``,
        ``extreme_price``, ``origin_time``, ``extreme_time``,
        ``origin_bar_index``, ``extreme_bar_index``, ``quality_score``.
    ratios:
        List of ratio multiples.  Non-positive ratios are skipped.
    mode:
        ``"raw"`` (linear price space) or ``"log"`` (log price space).
    angle_family_tag:
        Optional string from Phase 3A angle-family output; appended to
        the ``notes`` field of every target for this impulse.

    Returns
    -------
    List of :class:`MeasuredMoveTarget` objects.  May be empty if all
    ratios are invalid or the impulse has ``delta_p == 0``.

    Raises
    ------
    ValueError
        If ``mode`` is not ``"raw"`` or ``"log"``.
    """
    if mode not in ("raw", "log"):
        raise ValueError(f"mode must be 'raw' or 'log'; got {mode!r}.")

    d = impulse.to_dict() if hasattr(impulse, "to_dict") else dict(impulse)

    impulse_id = str(d.get("impulse_id", "unknown"))
    delta_p = float(d.get("delta_p", 0.0))
    origin_price = float(d.get("origin_price", 0.0))
    extreme_price = float(d.get("extreme_price", 0.0))
    quality_score = float(d.get("quality_score", 0.0))

    origin_time = d.get("origin_time")
    if not isinstance(origin_time, pd.Timestamp):
        origin_time = pd.Timestamp(origin_time, tz="UTC")
    if origin_time.tzinfo is None:
        origin_time = origin_time.tz_localize("UTC")

    extreme_time = d.get("extreme_time")
    if not isinstance(extreme_time, pd.Timestamp):
        extreme_time = pd.Timestamp(extreme_time, tz="UTC")
    if extreme_time.tzinfo is None:
        extreme_time = extreme_time.tz_localize("UTC")

    origin_bar_index = int(d.get("origin_bar_index", 0))
    extreme_bar_index = int(d.get("extreme_bar_index", 0))

    family_note = f"angle_family={angle_family_tag}" if angle_family_tag else ""

    targets: List[MeasuredMoveTarget] = []

    if delta_p == 0:
        logger.debug(
            "measured_move_targets: impulse_id=%r has delta_p=0; no targets.",
            impulse_id,
        )
        return targets

    # Pre-compute log delta for log mode.
    log_delta: Optional[float] = None
    if mode == "log":
        if origin_price > 0 and extreme_price > 0:
            log_delta = log_return(origin_price, extreme_price)
        else:
            logger.warning(
                "measured_move_targets: impulse_id=%r: non-positive prices "
                "(origin=%.4f, extreme=%.4f); falling back to raw for all targets.",
                impulse_id,
                origin_price,
                extreme_price,
            )
            mode = "raw"  # graceful fallback

    log_extreme = math.log(extreme_price) if (mode == "log" and extreme_price > 0) else None

    for ratio in ratios:
        if ratio < _MIN_RATIO:
            logger.debug(
                "measured_move_targets: skipping non-positive ratio=%r.", ratio
            )
            continue

        for direction in ("extension", "retracement"):
            notes_parts = []
            if family_note:
                notes_parts.append(family_note)

            if mode == "raw":
                if direction == "extension":
                    # Beyond extreme, in same direction as impulse.
                    target_price = extreme_price + ratio * delta_p
                else:
                    # Back from extreme toward / past origin.
                    target_price = extreme_price - ratio * delta_p

                if target_price <= 0:
                    notes_parts.append("WARNING:non_positive_target")

            else:  # log mode
                assert log_delta is not None and log_extreme is not None
                if direction == "extension":
                    target_price = math.exp(log_extreme + ratio * log_delta)
                else:
                    target_price = math.exp(log_extreme - ratio * log_delta)

                if target_price <= 0:
                    # Should not happen for valid prices, but guard anyway.
                    logger.debug(
                        "measured_move_targets: impulse_id=%r log target ≤ 0 "
                        "(ratio=%g direction=%s); skipping.",
                        impulse_id,
                        ratio,
                        direction,
                    )
                    continue

            targets.append(
                MeasuredMoveTarget(
                    impulse_id=impulse_id,
                    ratio=ratio,
                    target_price=target_price,
                    direction=direction,
                    mode=mode,
                    origin_price=origin_price,
                    origin_time=origin_time,
                    extreme_price=extreme_price,
                    extreme_time=extreme_time,
                    origin_bar_index=origin_bar_index,
                    extreme_bar_index=extreme_bar_index,
                    quality_score=quality_score,
                    notes="; ".join(notes_parts),
                )
            )

    logger.debug(
        "measured_move_targets: impulse_id=%r mode=%r ratios=%r → %d targets.",
        impulse_id,
        mode,
        ratios,
        len(targets),
    )
    return targets


def compute_measured_moves(
    impulses: List[Any],
    ratios: Optional[List[float]] = None,
    mode: str = "raw",
    angle_family_tags: Optional[Dict[str, str]] = None,
) -> List[MeasuredMoveTarget]:
    """Compute measured-move targets for a list of impulses.

    Parameters
    ----------
    impulses:
        List of :class:`~modules.impulse.Impulse` objects or plain dicts.
    ratios:
        Ratio multiples.  Default ``[0.5, 1.0, 1.5, 2.0]``.
    mode:
        ``"raw"`` (default) or ``"log"``.
    angle_family_tags:
        Optional mapping of ``impulse_id → angle_family_name`` from Phase 3A
        output.  If provided, the family name is appended to each target's
        ``notes`` field.

    Returns
    -------
    Flat list of :class:`MeasuredMoveTarget` objects across all impulses.
    Empty list if ``impulses`` is empty.

    Raises
    ------
    ValueError
        If ``mode`` is not ``"raw"`` or ``"log"``.
    """
    if ratios is None:
        ratios = [0.5, 1.0, 1.5, 2.0]

    if mode not in ("raw", "log"):
        raise ValueError(f"mode must be 'raw' or 'log'; got {mode!r}.")

    if not impulses:
        return []

    if angle_family_tags is None:
        angle_family_tags = {}

    all_targets: List[MeasuredMoveTarget] = []
    for imp in impulses:
        d = imp.to_dict() if hasattr(imp, "to_dict") else dict(imp)
        iid = str(d.get("impulse_id", ""))
        tag = angle_family_tags.get(iid)
        targets = measured_move_targets(imp, ratios=ratios, mode=mode, angle_family_tag=tag)
        all_targets.extend(targets)

    logger.info(
        "compute_measured_moves: %d impulse(s), %d ratio(s), mode=%r → %d target(s).",
        len(impulses),
        len(ratios),
        mode,
        len(all_targets),
    )
    return all_targets
