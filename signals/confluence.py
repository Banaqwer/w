"""
signals/confluence.py

Phase 4 — Confluence engine.

Clusters overlapping :class:`~signals.projections.Projection` objects into
:class:`~signals.projections.ConfluenceZone` objects and scores each zone.

Clustering rules (MVP)
-----------------------
Two projections are **connected** (i.e. belong to the same cluster candidate)
if they share at least one non-trivial overlapping dimension:

* **Price overlap**: both projections have non-None price bands AND
  ``max(low1, low2) <= min(high1, high2)`` (intervals touch or cross).
* **Time overlap**: both projections have non-None time bands (both bounds of
  at least one band are non-None) AND the bands overlap similarly.

A cluster is grown via single-linkage connected-component search:
- Start with each projection as its own component.
- Merge any two components that have at least one pair of projections that
  are connected by price overlap OR time overlap.

This means a time-only projection and a price-only projection are NOT merged
(they have no shared dimension).  A mixed projection (both price and time
bands non-None) can act as a bridge.

Zone formation
--------------
After clustering, each component with ≥ ``min_cluster_size`` projections
(default 1, i.e. all projections produce a zone) becomes a
:class:`~signals.projections.ConfluenceZone`.

- ``price_window``: the **intersection** (tightest common sub-interval) of
  all contributing price bands that are non-None.  ``None`` if no contributing
  projection has a price band.
- ``time_window``: the **intersection** of all contributing time bands that are
  fully-bounded (both bounds non-None).  ``None`` if no such time band exists.

Scoring formula (deterministic)
--------------------------------
For a zone with ``N`` contributing projections:

1. ``n_score``:  ``min(1.0, N / 10)``.  Rewards having more projections.
2. ``diversity_score``:  ``M / max_module_types`` where ``M`` is the number of
   distinct ``module_name`` values in the zone and ``max_module_types`` defaults
   to 4 (the four MVP generators).
3. ``avg_raw_score``:  arithmetic mean of ``raw_score`` values.
4. ``recency_score`` (optional): not included in MVP; set to 1.0 (neutral).

``confluence_score = n_score * diversity_score * avg_raw_score``

The score is in ``(0, 1]``.  Higher is better.

Public API
----------
- :func:`build_confluence_zones` — primary function.

References
----------
signals/projections.py — Projection, ConfluenceZone, make_zone_id
CLAUDE.md — Phase 4 Confluence spec
docs/phase0_builder_output.md — ForecastZone interface
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pandas as pd

from signals.projections import ConfluenceZone, Projection, make_zone_id

logger = logging.getLogger(__name__)

_MAX_MODULE_TYPES = 4   # MVP: measured_moves, jttl, sqrt_levels, time_counts
_DEFAULT_MIN_CLUSTER_SIZE = 1


# ── Public API ────────────────────────────────────────────────────────────────


def build_confluence_zones(
    projections: List[Projection],
    min_cluster_size: int = _DEFAULT_MIN_CLUSTER_SIZE,
) -> List[ConfluenceZone]:
    """Cluster projections into ConfluenceZones and score each zone.

    Parameters
    ----------
    projections:
        List of :class:`~signals.projections.Projection` objects.  May be
        empty; returns empty list.
    min_cluster_size:
        Minimum number of projections to form a zone.  Default 1 (all
        projections, including singletons, form a zone).

    Returns
    -------
    List of :class:`~signals.projections.ConfluenceZone` objects, sorted by
    ``confluence_score`` descending.

    Notes
    -----
    - Deterministic: same input list (same order) always produces same output.
    - Price-only and time-only projections are never merged with each other
      (no shared dimension), but each forms its own singleton zone.
    - Projections with both price and time bands can bridge clusters.
    """
    if not projections:
        return []

    n = len(projections)
    # Union-find / component labelling
    component = list(range(n))

    def find(x: int) -> int:
        while component[x] != x:
            component[x] = component[component[x]]
            x = component[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            component[ra] = rb

    # Pairwise overlap test (O(n²) — acceptable for MVP scale)
    for i in range(n):
        for j in range(i + 1, n):
            if _are_connected(projections[i], projections[j]):
                union(i, j)

    # Group by root component
    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    zones: List[ConfluenceZone] = []
    for root, members in groups.items():
        if len(members) < min_cluster_size:
            continue

        contrib_projs = [projections[i] for i in members]
        zone = _make_zone(contrib_projs)
        zones.append(zone)

    zones.sort(key=lambda z: z.confluence_score, reverse=True)
    logger.info(
        "build_confluence_zones: %d projection(s) → %d zone(s).",
        n,
        len(zones),
    )
    return zones


# ── Zone construction ─────────────────────────────────────────────────────────


def _make_zone(projections: List[Projection]) -> ConfluenceZone:
    """Build a ConfluenceZone from a list of contributing Projections."""
    ids = [p.projection_id for p in projections]
    zone_id = make_zone_id(ids)

    # Compute intersecting price_window
    price_window = _intersect_price_bands(
        [p.price_band for p in projections if _has_price_band(p)]
    )

    # Compute intersecting time_window (only fully-bounded bands)
    time_window = _intersect_time_bands(
        [p.time_band for p in projections if _has_time_band(p)]
    )

    # Module counts
    module_counts: Dict[str, int] = defaultdict(int)
    for p in projections:
        module_counts[p.module_name] += 1

    # Score
    confluence_score = _score_zone(projections)

    notes_parts: list = []
    if price_window is not None and time_window is not None:
        notes_parts.append("type=price+time")
    elif price_window is not None:
        notes_parts.append("type=price_only")
    elif time_window is not None:
        notes_parts.append("type=time_only")
    else:
        notes_parts.append("type=disconnected")

    return ConfluenceZone(
        zone_id=zone_id,
        time_window=time_window,
        price_window=price_window,
        contributing_projection_ids=sorted(ids),
        confluence_score=confluence_score,
        module_counts=dict(module_counts),
        notes="; ".join(notes_parts),
    )


def _score_zone(projections: List[Projection]) -> float:
    """Compute deterministic confluence score for a zone."""
    n = len(projections)
    if n == 0:
        return 0.0

    # 1. n_score
    n_score = min(1.0, n / 10.0)

    # 2. diversity_score
    distinct_modules = len({p.module_name for p in projections})
    diversity_score = distinct_modules / _MAX_MODULE_TYPES

    # 3. avg_raw_score
    avg_raw = sum(p.raw_score for p in projections) / n

    score = n_score * diversity_score * avg_raw
    return max(0.0, min(1.0, score))


# ── Overlap logic ─────────────────────────────────────────────────────────────


def _are_connected(a: Projection, b: Projection) -> bool:
    """Return True if projections share an overlapping price OR time dimension."""
    return _price_overlap(a, b) or _time_overlap(a, b)


def _price_overlap(a: Projection, b: Projection) -> bool:
    """Return True if both have price bands and they overlap."""
    if not (_has_price_band(a) and _has_price_band(b)):
        return False
    a_lo, a_hi = a.price_band
    b_lo, b_hi = b.price_band
    # Replace None bounds with ±inf for comparison
    a_lo = a_lo if a_lo is not None else float("-inf")
    a_hi = a_hi if a_hi is not None else float("inf")
    b_lo = b_lo if b_lo is not None else float("-inf")
    b_hi = b_hi if b_hi is not None else float("inf")
    return max(a_lo, b_lo) <= min(a_hi, b_hi)


def _time_overlap(a: Projection, b: Projection) -> bool:
    """Return True if both have fully-bounded time bands and they overlap."""
    if not (_has_time_band(a) and _has_time_band(b)):
        return False
    a_lo, a_hi = a.time_band
    b_lo, b_hi = b.time_band
    if a_lo is None or a_hi is None or b_lo is None or b_hi is None:
        return False
    return max(a_lo, b_lo) <= min(a_hi, b_hi)


def _has_price_band(p: Projection) -> bool:
    """Return True if the projection has at least one non-None price bound."""
    lo, hi = p.price_band
    return lo is not None or hi is not None


def _has_time_band(p: Projection) -> bool:
    """Return True if the projection has both time bounds non-None (fully bounded)."""
    lo, hi = p.time_band
    return lo is not None and hi is not None


# ── Band intersection helpers ─────────────────────────────────────────────────


def _intersect_price_bands(
    bands: list,
) -> Optional[Tuple[float, float]]:
    """Return the intersection of a list of (lo, hi) price bands, or None."""
    if not bands:
        return None
    lo = float("-inf")
    hi = float("inf")
    for band in bands:
        b_lo, b_hi = band
        if b_lo is not None:
            lo = max(lo, b_lo)
        if b_hi is not None:
            hi = min(hi, b_hi)
    if lo > hi:
        # No common intersection; return the union instead (defensive fallback)
        lo_vals = [b[0] for b in bands if b[0] is not None]
        hi_vals = [b[1] for b in bands if b[1] is not None]
        lo = min(lo_vals) if lo_vals else float("-inf")
        hi = max(hi_vals) if hi_vals else float("inf")
    if lo == float("-inf") and hi == float("inf"):
        return None
    return (lo, hi)


def _intersect_time_bands(
    bands: list,
) -> Optional[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Return the intersection of a list of (lo, hi) time bands, or None."""
    fully_bounded = [
        (lo, hi) for lo, hi in bands if lo is not None and hi is not None
    ]
    if not fully_bounded:
        return None
    lo = fully_bounded[0][0]
    hi = fully_bounded[0][1]
    for b_lo, b_hi in fully_bounded[1:]:
        lo = max(lo, b_lo)
        hi = min(hi, b_hi)
    if lo > hi:
        # No common intersection; return union instead (defensive fallback)
        lo = min(b[0] for b in fully_bounded)
        hi = max(b[1] for b in fully_bounded)
    return (lo, hi)
