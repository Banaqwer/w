"""
backtest/execution.py

Phase 6 — Deterministic execution simulator.

Provides the :class:`Trade` schema and pure-function fill logic.  No broker
connectivity, no live trading, no partial fills.

Fill model (deterministic)
--------------------------
Entry and exit fills are computed as::

    long  entry fill = open_price * (1 + (slippage_bps + fees_bps) / 10_000)
    long  exit  fill = open_price * (1 - (slippage_bps + fees_bps) / 10_000)
    short entry fill = open_price * (1 - (slippage_bps + fees_bps) / 10_000)
    short exit  fill = open_price * (1 + (slippage_bps + fees_bps) / 10_000)

Fees and slippage are applied symmetrically per side (entry and exit each pay
half of the configured round-trip bps).  This is documented as a simplification
(ASSUMPTIONS.md Assumption 33).

Partial fills are **not supported**.  Any fill is treated as a complete fill at
the computed price.

Position sizing
---------------
- ``"fixed_fraction"``: ``position_size = equity * fraction``
- ``"fixed_notional"``: ``position_size = fixed_notional``

``position_size`` is always in USD notional.  Units are kept in USD for
research reproducibility.

References
----------
configs/backtest.yaml — configurable defaults
ASSUMPTIONS.md — Assumptions 31–38
CLAUDE.md — Phase 6 goal
PROJECT_STATUS.md — Phase 6 section
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_VALID_SIDES = frozenset({"long", "short"})
_VALID_EXIT_REASONS = frozenset(
    {"invalidation", "time_expired", "max_hold_bars", "end_of_data", "no_entry"}
)


# ── Trade dataclass ───────────────────────────────────────────────────────────


@dataclass
class Trade:
    """Record of a single simulated trade.

    Fields
    ------
    trade_id : str
        Deterministic identifier: ``"{signal_id}_{entry_time}"``.
    signal_id : str
        Identifier of the parent :class:`~signals.signal_types.SignalCandidate`.
    side : str
        ``"long"`` or ``"short"``.
    entry_time : pd.Timestamp
        UTC timestamp of the bar whose open was used as the entry fill.
    entry_price : float
        Actual fill price after slippage+fees at entry.
    entry_open : float
        Raw bar open price before fees/slippage (for audit).
    exit_time : Optional[pd.Timestamp]
        UTC timestamp of the exit bar open.  ``None`` if no exit yet (should
        not occur in completed backtest runs).
    exit_price : Optional[float]
        Actual fill price after slippage+fees at exit.
    exit_open : Optional[float]
        Raw bar open price before fees/slippage at exit (for audit).
    exit_reason : str
        One of ``"invalidation"``, ``"time_expired"``, ``"max_hold_bars"``,
        ``"end_of_data"``, ``"no_entry"``.
    position_size : float
        USD notional of the position.
    gross_pnl : float
        PnL before fees/slippage: ``(exit_fill_raw - entry_fill_raw) * direction``
        where ``direction`` is +1 for long, -1 for short.  Uses raw opens.
    fees_and_slippage : float
        Total fees+slippage paid (always positive).
    net_pnl : float
        ``gross_pnl - fees_and_slippage``.
    r_multiple : float
        ``net_pnl / initial_risk`` where ``initial_risk`` is the notional
        distance from entry to the closest price-based invalidation level
        (times position_size).  ``0.0`` if no invalidation level is defined.
    entry_region_low : float
        Lower bound of the entry price region (from signal).
    entry_region_high : float
        Upper bound of the entry price region (from signal).
    invalidation_price : Optional[float]
        Price level at which the signal is invalidated (from signal).
    quality_score : float
        Parent signal's quality_score (confluence_score).
    dataset_version : str
        Dataset version used for this trade.
    metadata : dict
        Extra audit data.
    """

    trade_id: str
    signal_id: str
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    entry_open: float
    exit_time: Optional[pd.Timestamp]
    exit_price: Optional[float]
    exit_open: Optional[float]
    exit_reason: str
    position_size: float
    gross_pnl: float
    fees_and_slippage: float
    net_pnl: float
    r_multiple: float
    entry_region_low: float
    entry_region_high: float
    invalidation_price: Optional[float]
    quality_score: float
    dataset_version: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.side not in _VALID_SIDES:
            raise ValueError(f"side must be 'long' or 'short'; got {self.side!r}.")
        if self.exit_reason not in _VALID_EXIT_REASONS:
            raise ValueError(
                f"exit_reason must be one of {sorted(_VALID_EXIT_REASONS)!r}; "
                f"got {self.exit_reason!r}."
            )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable / CSV-compatible dict."""
        return {
            "trade_id": self.trade_id,
            "signal_id": self.signal_id,
            "side": self.side,
            "entry_time": str(self.entry_time),
            "entry_price": self.entry_price,
            "entry_open": self.entry_open,
            "exit_time": str(self.exit_time) if self.exit_time is not None else None,
            "exit_price": self.exit_price,
            "exit_open": self.exit_open,
            "exit_reason": self.exit_reason,
            "position_size": self.position_size,
            "gross_pnl": self.gross_pnl,
            "fees_and_slippage": self.fees_and_slippage,
            "net_pnl": self.net_pnl,
            "r_multiple": self.r_multiple,
            "entry_region_low": self.entry_region_low,
            "entry_region_high": self.entry_region_high,
            "invalidation_price": self.invalidation_price,
            "quality_score": self.quality_score,
            "dataset_version": self.dataset_version,
        }


# ── Fill price helpers ────────────────────────────────────────────────────────


def compute_entry_fill(
    open_price: float,
    side: str,
    fees_bps: float,
    slippage_bps: float,
) -> float:
    """Return the actual entry fill price after fees and slippage.

    Parameters
    ----------
    open_price:
        Raw bar open price.
    side:
        ``"long"`` or ``"short"``.
    fees_bps:
        One-way fee in basis points (half of the round-trip bps config).
    slippage_bps:
        One-way slippage in basis points (half of the round-trip bps config).

    Returns
    -------
    Adjusted fill price.  Long entry fills *above* open (market pays more);
    short entry fills *below* open (market pays more to short).
    """
    if side not in _VALID_SIDES:
        raise ValueError(f"side must be 'long' or 'short'; got {side!r}.")
    adjustment = (fees_bps + slippage_bps) / 10_000.0
    if side == "long":
        return open_price * (1.0 + adjustment)
    return open_price * (1.0 - adjustment)


def compute_exit_fill(
    open_price: float,
    side: str,
    fees_bps: float,
    slippage_bps: float,
) -> float:
    """Return the actual exit fill price after fees and slippage.

    Parameters
    ----------
    open_price:
        Raw bar open price at exit.
    side:
        ``"long"`` or ``"short"``.
    fees_bps:
        One-way fee in basis points.
    slippage_bps:
        One-way slippage in basis points.

    Returns
    -------
    Adjusted exit fill price.  Long exit fills *below* open (market gets less);
    short exit fills *above* open.
    """
    if side not in _VALID_SIDES:
        raise ValueError(f"side must be 'long' or 'short'; got {side!r}.")
    adjustment = (fees_bps + slippage_bps) / 10_000.0
    if side == "long":
        return open_price * (1.0 - adjustment)
    return open_price * (1.0 + adjustment)


def compute_fees_and_slippage(
    entry_open: float,
    exit_open: float,
    position_size: float,
    fees_bps: float,
    slippage_bps: float,
) -> float:
    """Return total fees+slippage paid for a round-trip trade in USD.

    Parameters
    ----------
    entry_open:
        Raw entry bar open price.
    exit_open:
        Raw exit bar open price.
    position_size:
        USD notional of the position.
    fees_bps:
        One-way fee in basis points.
    slippage_bps:
        One-way slippage in basis points.

    Returns
    -------
    Total cost in USD (always positive).
    """
    entry_adj = (fees_bps + slippage_bps) / 10_000.0
    exit_adj = (fees_bps + slippage_bps) / 10_000.0
    # cost = entry_open * entry_adj * units + exit_open * exit_adj * units
    # units = position_size / entry_open
    units = position_size / entry_open if entry_open > 0 else 0.0
    return abs(entry_open * entry_adj * units) + abs(exit_open * exit_adj * units)


def compute_gross_pnl(
    entry_open: float,
    exit_open: float,
    position_size: float,
    side: str,
) -> float:
    """Return gross PnL (before fees/slippage) for a completed trade.

    Parameters
    ----------
    entry_open:
        Raw entry bar open price.
    exit_open:
        Raw exit bar open price.
    position_size:
        USD notional.
    side:
        ``"long"`` or ``"short"``.

    Returns
    -------
    Gross PnL in USD.  Positive = profit, negative = loss.
    """
    if side not in _VALID_SIDES:
        raise ValueError(f"side must be 'long' or 'short'; got {side!r}.")
    if entry_open <= 0:
        return 0.0
    units = position_size / entry_open
    direction = 1.0 if side == "long" else -1.0
    return direction * (exit_open - entry_open) * units


def compute_position_size(
    equity: float,
    sizing_mode: str,
    fraction: float = 0.01,
    fixed_notional: float = 1000.0,
) -> float:
    """Return position size in USD notional.

    Parameters
    ----------
    equity:
        Current account equity in USD.
    sizing_mode:
        ``"fixed_fraction"`` or ``"fixed_notional"``.
    fraction:
        Fraction of equity per trade (used when sizing_mode='fixed_fraction').
    fixed_notional:
        Fixed dollar amount per trade (used when sizing_mode='fixed_notional').

    Returns
    -------
    Position size in USD.
    """
    if sizing_mode == "fixed_fraction":
        return equity * fraction
    if sizing_mode == "fixed_notional":
        return fixed_notional
    raise ValueError(
        f"sizing_mode must be 'fixed_fraction' or 'fixed_notional'; "
        f"got {sizing_mode!r}."
    )


# ── Trade builder ─────────────────────────────────────────────────────────────


def build_trade(
    signal_id: str,
    side: str,
    entry_time: pd.Timestamp,
    entry_open: float,
    exit_time: pd.Timestamp,
    exit_open: float,
    exit_reason: str,
    position_size: float,
    fees_bps: float,
    slippage_bps: float,
    entry_region_low: float,
    entry_region_high: float,
    invalidation_price: Optional[float],
    quality_score: float,
    dataset_version: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Trade:
    """Build a completed :class:`Trade` from fill parameters.

    Applies fees+slippage symmetrically (one-way bps at entry and exit), then
    computes gross PnL, net PnL, and R-multiple.

    Parameters
    ----------
    signal_id:
        ID of the generating signal.
    side:
        ``"long"`` or ``"short"``.
    entry_time:
        UTC timestamp of the entry bar.
    entry_open:
        Raw open price of the entry bar.
    exit_time:
        UTC timestamp of the exit bar.
    exit_open:
        Raw open price of the exit bar.
    exit_reason:
        Reason for exit (see :data:`_VALID_EXIT_REASONS`).
    position_size:
        USD notional of the position.
    fees_bps:
        One-way fees in basis points (half of round-trip config).
    slippage_bps:
        One-way slippage in basis points (half of round-trip config).
    entry_region_low:
        Lower bound of entry price region.
    entry_region_high:
        Upper bound of entry price region.
    invalidation_price:
        Price level at which signal is invalidated (for R-multiple).
    quality_score:
        Parent signal quality score.
    dataset_version:
        Dataset version string.
    metadata:
        Optional extra audit data.

    Returns
    -------
    A fully-populated :class:`Trade` object.
    """
    entry_fill = compute_entry_fill(entry_open, side, fees_bps, slippage_bps)
    exit_fill = compute_exit_fill(exit_open, side, fees_bps, slippage_bps)
    gross = compute_gross_pnl(entry_open, exit_open, position_size, side)
    cost = compute_fees_and_slippage(
        entry_open, exit_open, position_size, fees_bps, slippage_bps
    )
    net = gross - cost

    # R-multiple: net_pnl / initial_risk_per_unit
    r_mult = 0.0
    if invalidation_price is not None and entry_open > 0:
        initial_risk_per_unit = abs(entry_open - invalidation_price)
        units = position_size / entry_open
        initial_risk_dollars = initial_risk_per_unit * units
        if initial_risk_dollars > 0:
            r_mult = net / initial_risk_dollars

    trade_id = f"{signal_id}_{entry_time.isoformat()}"

    return Trade(
        trade_id=trade_id,
        signal_id=signal_id,
        side=side,
        entry_time=entry_time,
        entry_price=entry_fill,
        entry_open=entry_open,
        exit_time=exit_time,
        exit_price=exit_fill,
        exit_open=exit_open,
        exit_reason=exit_reason,
        position_size=position_size,
        gross_pnl=gross,
        fees_and_slippage=cost,
        net_pnl=net,
        r_multiple=r_mult,
        entry_region_low=entry_region_low,
        entry_region_high=entry_region_high,
        invalidation_price=invalidation_price,
        quality_score=quality_score,
        dataset_version=dataset_version,
        metadata=metadata or {},
    )
