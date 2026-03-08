"""
signals/projections.py

Phase 4 — Projection and ConfluenceZone dataclasses.

These are the canonical output objects for all Phase 4 projection generators
and the confluence engine.  They are NOT trade signals; they carry no
confirmation or execution logic (Phase 5+).

Projection
----------
A single forward-looking estimate produced by one Phase 3 module from one
source (impulse, JTTL line, sqrt level, time window).

ConfluenceZone
--------------
A cluster of overlapping Projections that agree in price space, time space, or
both.  Produced by ``signals/confluence.py``.

Design rules
------------
- All fields have explicit types.
- ``projected_time`` and ``projected_price`` may be ``None`` for time-only or
  price-only projections respectively.
- ``time_band`` and ``price_band`` are 2-tuples; either or both elements of each
  tuple may be ``None`` (open-ended) but at least one of the two bands must be
  non-trivially bounded for the projection to be useful.
- ``raw_score`` is in [0, 1] and represents the source quality / confidence
  contributed by the originating module.
- Every Projection has a stable ``projection_id`` derived deterministically from
  its content; callers must not rely on object identity for equality.

References
----------
CLAUDE.md — Phase 4 goal; Phase 0 Projection / ForecastZone spec
docs/phase0_builder_output.md — Projection / ForecastZone interface
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Type aliases
TimeBand = Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]
PriceBand = Tuple[Optional[float], Optional[float]]

# Valid direction_hint values
_VALID_DIRECTION_HINTS = frozenset({"support", "resistance", "turn", "ambiguous"})


# ── Projection ────────────────────────────────────────────────────────────────


@dataclass
class Projection:
    """A single forward-looking estimate from one Phase 3 module.

    Fields
    ------
    projection_id : str
        Deterministic identifier derived from module_name + source_id +
        projected_time + projected_price.  Generated automatically if left
        as empty string; see :meth:`ensure_id`.
    module_name : str
        Name of the generating module (e.g. ``"measured_moves"``,
        ``"jttl"``, ``"sqrt_levels"``, ``"time_counts"``).
    source_id : str
        Identifier of the source object (impulse_id, jttl_id, origin_id, etc.).
    projected_time : Optional[pd.Timestamp]
        UTC timestamp of the projected event.  ``None`` for price-only
        projections.
    projected_price : Optional[float]
        Projected price level.  ``None`` for time-only projections.
    time_band : TimeBand
        ``(earliest, latest)`` time window around ``projected_time``.
        Either bound may be ``None`` for open-ended bands.
        Both bounds are ``None`` for price-only projections.
    price_band : PriceBand
        ``(low, high)`` price band around ``projected_price``.
        Either bound may be ``None`` for open-ended bands.
        Both bounds are ``None`` for time-only projections.
    direction_hint : str
        One of ``"support"``, ``"resistance"``, ``"turn"``, ``"ambiguous"``.
    raw_score : float
        Source quality score in ``[0, 1]``.  Propagated from the Phase 3
        object (e.g. impulse quality_score).
    metadata : dict
        Module-specific extra data (ratios, angle_family, horizon, etc.).
    """

    module_name: str
    source_id: str
    projected_time: Optional[pd.Timestamp]
    projected_price: Optional[float]
    time_band: TimeBand
    price_band: PriceBand
    direction_hint: str
    raw_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    projection_id: str = ""

    def __post_init__(self) -> None:
        if self.direction_hint not in _VALID_DIRECTION_HINTS:
            raise ValueError(
                f"direction_hint must be one of {sorted(_VALID_DIRECTION_HINTS)!r}; "
                f"got {self.direction_hint!r}."
            )
        if not (0.0 <= self.raw_score <= 1.0):
            raise ValueError(
                f"raw_score must be in [0, 1]; got {self.raw_score}."
            )
        if not self.projection_id:
            self.projection_id = self._make_id()

    def _make_id(self) -> str:
        """Return a deterministic hex-digest ID from key fields."""
        pt_str = str(self.projected_time) if self.projected_time is not None else "None"
        pp_str = f"{self.projected_price:.6f}" if self.projected_price is not None else "None"
        raw = f"{self.module_name}|{self.source_id}|{pt_str}|{pp_str}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def ensure_id(self) -> "Projection":
        """Re-compute and store ``projection_id`` if it is empty.  Returns self."""
        if not self.projection_id:
            self.projection_id = self._make_id()
        return self

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        tb_lo = str(self.time_band[0]) if self.time_band[0] is not None else None
        tb_hi = str(self.time_band[1]) if self.time_band[1] is not None else None
        return {
            "projection_id": self.projection_id,
            "module_name": self.module_name,
            "source_id": self.source_id,
            "projected_time": str(self.projected_time) if self.projected_time is not None else None,
            "projected_price": self.projected_price,
            "time_band": [tb_lo, tb_hi],
            "price_band": list(self.price_band),
            "direction_hint": self.direction_hint,
            "raw_score": self.raw_score,
            "metadata": _serialise_meta(self.metadata),
        }


# ── ConfluenceZone ────────────────────────────────────────────────────────────


@dataclass
class ConfluenceZone:
    """A cluster of overlapping Projections.

    Fields
    ------
    zone_id : str
        Deterministic identifier: sha1 of sorted contributing_projection_ids.
    time_window : Optional[Tuple[pd.Timestamp, pd.Timestamp]]
        Intersection of contributing time bands, or ``None`` if no time-band
        projections contributed.
    price_window : Optional[Tuple[float, float]]
        Intersection of contributing price bands, or ``None`` if no
        price-band projections contributed.
    contributing_projection_ids : List[str]
        Sorted list of Projection IDs in this zone.
    confluence_score : float
        Weighted scoring of zone quality (see scoring formula in
        ``signals/confluence.py``).
    module_counts : Dict[str, int]
        Number of contributing projections per module_name.
    notes : str
        Free-text metadata.
    """

    zone_id: str
    time_window: Optional[Tuple[pd.Timestamp, pd.Timestamp]]
    price_window: Optional[Tuple[float, float]]
    contributing_projection_ids: List[str]
    confluence_score: float
    module_counts: Dict[str, int]
    notes: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        tw = None
        if self.time_window is not None:
            tw = [str(self.time_window[0]), str(self.time_window[1])]
        pw = None
        if self.price_window is not None:
            pw = list(self.price_window)
        return {
            "zone_id": self.zone_id,
            "time_window": tw,
            "price_window": pw,
            "contributing_projection_ids": sorted(self.contributing_projection_ids),
            "confluence_score": self.confluence_score,
            "module_counts": self.module_counts,
            "notes": self.notes,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_zone_id(projection_ids: List[str]) -> str:
    """Return a deterministic zone ID from a list of projection IDs."""
    key = "|".join(sorted(projection_ids))
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _serialise_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Return a JSON-safe version of a metadata dict (timestamps → str, etc.)."""
    out: Dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, pd.Timestamp):
            out[k] = str(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x) if isinstance(x, pd.Timestamp) else x for x in v]
        else:
            out[k] = v
    return out
