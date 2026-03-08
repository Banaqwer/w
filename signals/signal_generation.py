"""
signals/signal_generation.py

Phase 5 — Generate SignalCandidate objects from ConfluenceZones.

Converts a list of :class:`~signals.projections.ConfluenceZone` objects (and
the corresponding :class:`~signals.projections.Projection` list) into
:class:`~signals.signal_types.SignalCandidate` objects using fully
deterministic, config-driven rules.

Bias rule (MVP, deterministic)
------------------------------
Count the ``direction_hint`` values across all Projections contributing to a
zone (via ``contributing_projection_ids``):

1. Majority ``"support"``  → ``bias = "long"``
2. Majority ``"resistance"`` → ``bias = "short"``
3. Equal / mixed / ``"turn"`` / ``"ambiguous"`` majority → ``bias = "neutral"``

Neutral zones are **skipped by default** unless their ``confluence_score``
meets the ``min_score_for_neutral`` threshold.

Entry region
------------
``price_low`` / ``price_high`` come directly from ``zone.price_window``.
Zones with no ``price_window`` are skipped (cannot build an entry region).
``time_earliest`` / ``time_latest`` come from ``zone.time_window`` when present.

Invalidation rules
------------------
* For *long*: ``close_below_zone`` at ``zone.price_window[0] - buffer``.
* For *short*: ``close_above_zone`` at ``zone.price_window[1] + buffer``.
* If ``zone.time_window`` is set: an additional ``time_expired`` rule with
  ``time_cutoff = zone.time_window[1]``.
* *Neutral* signals receive both a ``close_below_zone`` and a
  ``close_above_zone`` rule bracketing the zone.

Confirmation names
------------------
Two confirmation check names are always attached:

* ``"candle_direction"`` — most recent 6H candle closes in the direction
  consistent with bias.
* ``"zone_rejection"`` — price returned to the entry zone and rejected.

When the dataset manifest reports ``missing_bar_count > 0``, a third name
``"strict_multi_candle"`` is added to signal that stricter confirmation is
required (evaluated in ``signals/confirmations.py``).

Gap policy
----------
Reads ``missing_bar_count`` from the supplied manifest dict.  When > 0:
- logs a note in ``signal.metadata["gap_note"]``
- appends ``"strict_multi_candle"`` to ``confirmations_required``
- sets ``signal.metadata["missing_bar_count"]`` for downstream inspection

Quality score
-------------
``quality_score = zone.confluence_score`` (no modification in Phase 5).

Provenance
----------
``provenance = sorted(contributing_projection_ids) + sorted(distinct_module_names)``

Public API
----------
- :func:`generate_signals` — primary function.
- :func:`build_projection_index` — helper to build a {projection_id → Projection} dict.

References
----------
signals/signal_types.py — SignalCandidate, EntryRegion, InvalidationRule
signals/projections.py — ConfluenceZone, Projection
CLAUDE.md — Phase 5 goal; Required deliverables B
ASSUMPTIONS.md — Phase 5 signal-generation assumptions
PROJECT_STATUS.md — Phase 5 section
"""

from __future__ import annotations

import hashlib
import logging
from typing import Dict, List, Optional

import pandas as pd

from signals.projections import ConfluenceZone, Projection
from signals.signal_types import EntryRegion, InvalidationRule, SignalCandidate

logger = logging.getLogger(__name__)

# Default thresholds
_DEFAULT_INVALIDATION_BUFFER = 0.0
_DEFAULT_MIN_SCORE_NEUTRAL = 0.5
_DEFAULT_PRIMARY_TF = "1D"
_DEFAULT_CONFIRM_TF = "6H"

# Confirmation check names
_CHECK_CANDLE_DIRECTION = "candle_direction"
_CHECK_ZONE_REJECTION = "zone_rejection"
_CHECK_STRICT_MULTI_CANDLE = "strict_multi_candle"


# ── Public API ────────────────────────────────────────────────────────────────


def build_projection_index(projections: List[Projection]) -> Dict[str, Projection]:
    """Return a {projection_id → Projection} dict for fast lookup.

    Parameters
    ----------
    projections:
        List of :class:`~signals.projections.Projection` objects.

    Returns
    -------
    Dict mapping each projection's ``projection_id`` to the Projection.
    Duplicate IDs are silently overwritten by the last occurrence.
    """
    return {p.projection_id: p for p in projections}


def generate_signals(
    zones: List[ConfluenceZone],
    projections: List[Projection],
    dataset_version: str,
    manifest: Optional[dict] = None,
    primary_timeframe: str = _DEFAULT_PRIMARY_TF,
    confirm_timeframe: str = _DEFAULT_CONFIRM_TF,
    invalidation_buffer: float = _DEFAULT_INVALIDATION_BUFFER,
    min_score_for_neutral: float = _DEFAULT_MIN_SCORE_NEUTRAL,
) -> List[SignalCandidate]:
    """Convert ConfluenceZones into SignalCandidate objects.

    Parameters
    ----------
    zones:
        List of :class:`~signals.projections.ConfluenceZone` objects from
        ``signals/confluence.py``.  May be empty; returns empty list.
    projections:
        All Projection objects used to build the zones.  Used to look up
        ``direction_hint`` values for bias determination.
    dataset_version:
        Version string of the dataset (e.g.
        ``"proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1"``).
    manifest:
        Dataset manifest dict (from ``data/loader.py:load_manifest``).
        Used to read ``missing_bar_count``.  May be ``None`` or ``{}``.
    primary_timeframe:
        Label for the primary analysis timeframe (default ``"1D"``).
    confirm_timeframe:
        Label for the confirmation timeframe (default ``"6H"``).
    invalidation_buffer:
        Additional price tolerance applied to invalidation levels (default 0).
        Must be >= 0.
    min_score_for_neutral:
        Minimum ``confluence_score`` required to include a neutral-bias signal.
        Neutral zones below this threshold are skipped.  Default 0.5.

    Returns
    -------
    List of :class:`~signals.signal_types.SignalCandidate` objects, one per
    accepted zone.  Zones without a ``price_window`` are always skipped.
    The list preserves the order of ``zones`` (which is already sorted by
    ``confluence_score`` descending from the confluence engine).

    Notes
    -----
    - Deterministic: same inputs always produce the same outputs.
    - No execution logic, no order management, no PnL accounting.
    - Phase 6 backtest not started.
    """
    if invalidation_buffer < 0:
        raise ValueError(
            f"invalidation_buffer must be >= 0; got {invalidation_buffer}."
        )
    if not (0.0 <= min_score_for_neutral <= 1.0):
        raise ValueError(
            f"min_score_for_neutral must be in [0, 1]; got {min_score_for_neutral}."
        )

    manifest = manifest or {}
    missing_bar_count: int = int(manifest.get("missing_bar_count", 0))

    proj_index = build_projection_index(projections)
    timeframe_context = f"{primary_timeframe} primary / {confirm_timeframe} confirm"

    signals: List[SignalCandidate] = []

    for zone in zones:
        signal = _zone_to_signal(
            zone=zone,
            proj_index=proj_index,
            dataset_version=dataset_version,
            timeframe_context=timeframe_context,
            invalidation_buffer=invalidation_buffer,
            min_score_for_neutral=min_score_for_neutral,
            missing_bar_count=missing_bar_count,
        )
        if signal is not None:
            signals.append(signal)

    logger.info(
        "generate_signals: %d zone(s) → %d signal candidate(s) "
        "(missing_bar_count=%d).",
        len(zones),
        len(signals),
        missing_bar_count,
    )
    return signals


# ── Internal helpers ──────────────────────────────────────────────────────────


def _zone_to_signal(
    zone: ConfluenceZone,
    proj_index: Dict[str, Projection],
    dataset_version: str,
    timeframe_context: str,
    invalidation_buffer: float,
    min_score_for_neutral: float,
    missing_bar_count: int,
) -> Optional[SignalCandidate]:
    """Convert one ConfluenceZone to a SignalCandidate, or None if skipped."""

    # ── Require price_window ──────────────────────────────────────────────────
    if zone.price_window is None:
        logger.debug("Zone %s skipped: no price_window.", zone.zone_id)
        return None

    price_lo, price_hi = zone.price_window
    if price_lo is None or price_hi is None or price_lo > price_hi:
        logger.debug("Zone %s skipped: invalid price_window (%s, %s).", zone.zone_id, price_lo, price_hi)
        return None

    # ── Determine bias ────────────────────────────────────────────────────────
    bias = _determine_bias(zone, proj_index)

    # ── Apply neutral threshold ───────────────────────────────────────────────
    if bias == "neutral" and zone.confluence_score < min_score_for_neutral:
        logger.debug(
            "Zone %s skipped: neutral bias and score %.4f < %.4f.",
            zone.zone_id,
            zone.confluence_score,
            min_score_for_neutral,
        )
        return None

    # ── Build entry region ────────────────────────────────────────────────────
    time_earliest: Optional[pd.Timestamp] = None
    time_latest: Optional[pd.Timestamp] = None
    if zone.time_window is not None:
        time_earliest, time_latest = zone.time_window

    entry_region = EntryRegion(
        price_low=price_lo,
        price_high=price_hi,
        time_earliest=time_earliest,
        time_latest=time_latest,
    )

    # ── Build invalidation rules ──────────────────────────────────────────────
    invalidation = _build_invalidation(bias, price_lo, price_hi, time_latest, invalidation_buffer)

    # ── Build confirmations_required ─────────────────────────────────────────
    confirmations_required = [_CHECK_CANDLE_DIRECTION, _CHECK_ZONE_REJECTION]
    if missing_bar_count > 0:
        confirmations_required.append(_CHECK_STRICT_MULTI_CANDLE)

    # ── Build provenance ──────────────────────────────────────────────────────
    proj_ids = sorted(zone.contributing_projection_ids)
    module_names = sorted({
        proj_index[pid].module_name
        for pid in zone.contributing_projection_ids
        if pid in proj_index
    })
    provenance = proj_ids + [f"module:{m}" for m in module_names]

    # ── Build metadata ────────────────────────────────────────────────────────
    metadata: dict = {
        "confluence_score": zone.confluence_score,
        "module_counts": zone.module_counts,
        "missing_bar_count": missing_bar_count,
    }
    notes_parts = [f"bias={bias}", f"zone_type={zone.notes}"]
    if missing_bar_count > 0:
        gap_note = (
            f"Dataset has {missing_bar_count} missing bar(s); "
            "strict_multi_candle confirmation required."
        )
        metadata["gap_note"] = gap_note
        notes_parts.append(f"gap_policy=strict (missing_bars={missing_bar_count})")

    # ── Assemble signal ───────────────────────────────────────────────────────
    signal_id_raw = f"{zone.zone_id}|{bias}|{dataset_version}"
    signal_id = hashlib.sha1(signal_id_raw.encode()).hexdigest()[:16]

    signal = SignalCandidate(
        signal_id=signal_id,
        dataset_version=dataset_version,
        timeframe_context=timeframe_context,
        zone_id=zone.zone_id,
        bias=bias,
        entry_region=entry_region,
        invalidation=invalidation,
        confirmations_required=confirmations_required,
        quality_score=min(1.0, max(0.0, zone.confluence_score)),
        provenance=provenance,
        notes="; ".join(notes_parts),
        metadata=metadata,
    )
    return signal


def _determine_bias(
    zone: ConfluenceZone,
    proj_index: Dict[str, Projection],
) -> str:
    """Return the bias for a zone based on contributing projections' direction_hints.

    Rules:
    - Majority ``"support"`` (strictly > other categories combined) → ``"long"``
    - Majority ``"resistance"`` (strictly > other categories combined) → ``"short"``
    - All else (tie, equal, ``"turn"``/``"ambiguous"`` majority) → ``"neutral"``
    """
    counts: Dict[str, int] = {"support": 0, "resistance": 0, "turn": 0, "ambiguous": 0}

    for pid in zone.contributing_projection_ids:
        proj = proj_index.get(pid)
        if proj is None:
            continue
        hint = proj.direction_hint
        if hint in counts:
            counts[hint] += 1

    total = sum(counts.values())
    if total == 0:
        return "neutral"

    support_n = counts["support"]
    resist_n = counts["resistance"]

    # Strict majority: one category must exceed the other
    if support_n > resist_n:
        return "long"
    if resist_n > support_n:
        return "short"
    # Equal support/resistance or no clear majority → neutral
    return "neutral"


def _build_invalidation(
    bias: str,
    price_lo: float,
    price_hi: float,
    time_latest: Optional[pd.Timestamp],
    buffer: float,
) -> List[InvalidationRule]:
    """Build the list of InvalidationRule objects for a signal."""
    rules: List[InvalidationRule] = []

    if bias == "long":
        rules.append(InvalidationRule(
            condition="close_below_zone",
            price_level=price_lo,
            buffer=buffer,
        ))
    elif bias == "short":
        rules.append(InvalidationRule(
            condition="close_above_zone",
            price_level=price_hi,
            buffer=buffer,
        ))
    else:
        # Neutral: bracket the zone with both directions
        rules.append(InvalidationRule(
            condition="close_below_zone",
            price_level=price_lo,
            buffer=buffer,
        ))
        rules.append(InvalidationRule(
            condition="close_above_zone",
            price_level=price_hi,
            buffer=buffer,
        ))

    # Time invalidation when zone has a time_window
    if time_latest is not None:
        rules.append(InvalidationRule(
            condition="time_expired",
            time_cutoff=time_latest,
        ))

    return rules
