"""
signals/signal_types.py

Phase 5 — Signal candidate schema.

Defines the canonical output objects for the Phase 5 signal-generation layer.
These objects carry no execution logic, no order management, and no PnL
accounting.  They are structured descriptions of candidate trade set-ups
derived from Phase 4 ConfluenceZones.

SignalCandidate
--------------
A candidate signal produced from one ConfluenceZone.  Contains a bias
direction, entry region, invalidation conditions, and a list of confirmation
check names that must pass before the signal is considered actionable.

EntryRegion
-----------
Price band (required) and optional time window for entry.  Derived from the
parent zone's ``price_window`` and ``time_window``.

InvalidationRule
----------------
A single condition that, if met, cancels the signal.  Conditions are
expressed as declarative rules (not executable trade logic).

ConfirmationResult
------------------
Output of a single confirmation check (see ``signals/confirmations.py``).
Carries pass/fail + a human-readable reason string.

Design rules
------------
- All fields explicitly typed.
- ``signal_id`` is deterministic: derived from zone_id + bias + dataset_version.
- ``quality_score`` is in [0, 1] and directly propagates the parent zone's
  ``confluence_score`` (Phase 5 does not re-score; Phase 6+ may refine).
- No execution or PnL logic; Phase 6 backtest not started.

References
----------
CLAUDE.md — Phase 5 goal; Required deliverables A
signals/projections.py — Projection, ConfluenceZone
signals/confluence.py — build_confluence_zones
PROJECT_STATUS.md — Phase 5 section
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

# Valid bias values
_VALID_BIAS = frozenset({"long", "short", "neutral"})

# Valid invalidation condition strings
_VALID_CONDITIONS = frozenset({"close_below_zone", "close_above_zone", "time_expired"})


# ── EntryRegion ───────────────────────────────────────────────────────────────


@dataclass
class EntryRegion:
    """Price (and optionally time) region for a candidate signal entry.

    Fields
    ------
    price_low : float
        Lower bound of the entry price band.
    price_high : float
        Upper bound of the entry price band.  Must be >= price_low.
    time_earliest : Optional[pd.Timestamp]
        Earliest UTC timestamp the signal is considered active.  ``None`` for
        open-ended (no time constraint).
    time_latest : Optional[pd.Timestamp]
        Latest UTC timestamp the signal is considered active.  ``None`` for
        open-ended (no time constraint).  When set, must be >= time_earliest.
    """

    price_low: float
    price_high: float
    time_earliest: Optional[pd.Timestamp] = None
    time_latest: Optional[pd.Timestamp] = None

    def __post_init__(self) -> None:
        if self.price_low > self.price_high:
            raise ValueError(
                f"EntryRegion: price_low ({self.price_low}) > price_high ({self.price_high})."
            )
        if (
            self.time_earliest is not None
            and self.time_latest is not None
            and self.time_earliest > self.time_latest
        ):
            raise ValueError(
                f"EntryRegion: time_earliest ({self.time_earliest}) > "
                f"time_latest ({self.time_latest})."
            )

    def mid_price(self) -> float:
        """Return the midpoint of the price band."""
        return (self.price_low + self.price_high) / 2.0

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "price_low": self.price_low,
            "price_high": self.price_high,
            "time_earliest": str(self.time_earliest) if self.time_earliest is not None else None,
            "time_latest": str(self.time_latest) if self.time_latest is not None else None,
        }


# ── InvalidationRule ──────────────────────────────────────────────────────────


@dataclass
class InvalidationRule:
    """A single declarative condition that cancels a SignalCandidate.

    Conditions
    ----------
    ``"close_below_zone"``
        Triggered for a *long* signal when a bar closes below
        ``price_level - buffer``.  ``price_level`` defaults to the entry
        region's low if not explicitly set.
    ``"close_above_zone"``
        Triggered for a *short* signal when a bar closes above
        ``price_level + buffer``.  ``price_level`` defaults to the entry
        region's high if not explicitly set.
    ``"time_expired"``
        Triggered when the current timestamp exceeds ``time_cutoff``.

    Fields
    ------
    condition : str
        One of ``"close_below_zone"``, ``"close_above_zone"``,
        ``"time_expired"``.
    price_level : Optional[float]
        Reference price for price-based invalidation.
    time_cutoff : Optional[pd.Timestamp]
        Reference timestamp for time-based invalidation.
    buffer : float
        Additional price tolerance applied to ``price_level`` (default 0.0).
        Must be >= 0.
    """

    condition: str
    price_level: Optional[float] = None
    time_cutoff: Optional[pd.Timestamp] = None
    buffer: float = 0.0

    def __post_init__(self) -> None:
        if self.condition not in _VALID_CONDITIONS:
            raise ValueError(
                f"condition must be one of {sorted(_VALID_CONDITIONS)!r}; "
                f"got {self.condition!r}."
            )
        if self.buffer < 0:
            raise ValueError(f"buffer must be >= 0; got {self.buffer}.")

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "condition": self.condition,
            "price_level": self.price_level,
            "time_cutoff": str(self.time_cutoff) if self.time_cutoff is not None else None,
            "buffer": self.buffer,
        }


# ── SignalCandidate ───────────────────────────────────────────────────────────


@dataclass
class SignalCandidate:
    """A candidate signal derived from one ConfluenceZone.

    Fields
    ------
    signal_id : str
        Deterministic identifier derived from ``zone_id + bias + dataset_version``.
        Generated automatically if left as empty string.
    dataset_version : str
        Version string of the dataset used to produce the parent zone
        (e.g. ``"proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1"``).
    timeframe_context : str
        Human-readable description of the primary/confirmation timeframe pair
        (e.g. ``"1D primary / 6H confirm"``).
    zone_id : str
        ``zone_id`` of the parent :class:`~signals.projections.ConfluenceZone`.
    bias : str
        One of ``"long"``, ``"short"``, ``"neutral"``.
    entry_region : EntryRegion
        Price (and optional time) band for entry.
    invalidation : List[InvalidationRule]
        Conditions that cancel the signal.
    confirmations_required : List[str]
        Names of confirmation checks that must pass.  Populated by
        ``signals/signal_generation.py``; evaluated by
        ``signals/confirmations.py``.
    quality_score : float
        Signal quality in [0, 1].  Directly inherits the parent zone's
        ``confluence_score`` in MVP; Phase 6+ may refine.
    provenance : List[str]
        Sorted list of contributing projection IDs and module names.
    notes : str
        Free-text annotation.
    metadata : dict
        Miscellaneous key-value data (gap info, downgrade reasons, etc.).
    """

    signal_id: str
    dataset_version: str
    timeframe_context: str
    zone_id: str
    bias: str
    entry_region: EntryRegion
    invalidation: List[InvalidationRule]
    confirmations_required: List[str]
    quality_score: float
    provenance: List[str]
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.bias not in _VALID_BIAS:
            raise ValueError(
                f"bias must be one of {sorted(_VALID_BIAS)!r}; got {self.bias!r}."
            )
        if not (0.0 <= self.quality_score <= 1.0):
            raise ValueError(
                f"quality_score must be in [0, 1]; got {self.quality_score}."
            )
        if not self.signal_id:
            self.signal_id = self._make_id()

    def _make_id(self) -> str:
        """Return a deterministic hex-digest ID from key fields."""
        raw = f"{self.zone_id}|{self.bias}|{self.dataset_version}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "signal_id": self.signal_id,
            "dataset_version": self.dataset_version,
            "timeframe_context": self.timeframe_context,
            "zone_id": self.zone_id,
            "bias": self.bias,
            "entry_region": self.entry_region.to_dict(),
            "invalidation": [r.to_dict() for r in self.invalidation],
            "confirmations_required": self.confirmations_required,
            "quality_score": self.quality_score,
            "provenance": self.provenance,
            "notes": self.notes,
            "metadata": self.metadata,
        }


# ── ConfirmationResult ────────────────────────────────────────────────────────


@dataclass
class ConfirmationResult:
    """Result of a single confirmation check run against a SignalCandidate.

    Fields
    ------
    signal_id : str
        ID of the parent :class:`SignalCandidate`.
    check_name : str
        Name of the check that was run (matches an entry in
        ``signal.confirmations_required``).
    passed : bool
        ``True`` if the check passed.
    reason : str
        Human-readable explanation of the result.
    metadata : dict
        Extra data (e.g. the OHLCV values inspected, gap flag).
    """

    signal_id: str
    check_name: str
    passed: bool
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "signal_id": self.signal_id,
            "check_name": self.check_name,
            "passed": self.passed,
            "reason": self.reason,
            "metadata": self.metadata,
        }
