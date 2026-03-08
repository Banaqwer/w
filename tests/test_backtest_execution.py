"""
tests/test_backtest_execution.py

Tests for backtest/execution.py — Trade schema, fill model, fees+slippage,
position sizing, and build_trade lifecycle.

Coverage
--------
- compute_entry_fill:
  - long entry fills above open (costs more)
  - short entry fills below open (receives less)
  - zero fees and slippage → fill equals open
  - invalid side raises ValueError
- compute_exit_fill:
  - long exit fills below open (receives less)
  - short exit fills above open (costs more)
  - zero adjustments → fill equals open
  - invalid side raises ValueError
- compute_fees_and_slippage:
  - positive fee for any trade
  - scales with notional
  - symmetric (entry + exit)
  - zero fees → zero cost
- compute_gross_pnl:
  - long profit when exit > entry
  - long loss when exit < entry
  - short profit when exit < entry
  - short loss when exit > entry
  - invalid side raises ValueError
- compute_position_size:
  - fixed_fraction scales with equity
  - fixed_notional ignores equity
  - invalid sizing_mode raises ValueError
- build_trade:
  - deterministic: same inputs → same trade_id
  - fees_and_slippage > 0 for non-zero costs
  - net_pnl = gross_pnl - fees_and_slippage
  - r_multiple > 0 for profitable trade with defined invalidation
  - r_multiple = 0 when no invalidation_price
  - Trade.to_dict() includes all required keys
- Trade dataclass:
  - valid side accepted
  - invalid side raises ValueError
  - invalid exit_reason raises ValueError
- Determinism: repeated calls with same inputs produce identical results
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd
import pytest

from backtest.execution import (
    Trade,
    build_trade,
    compute_entry_fill,
    compute_exit_fill,
    compute_fees_and_slippage,
    compute_gross_pnl,
    compute_position_size,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_TS_ENTRY = pd.Timestamp("2024-01-10 12:00:00+00:00")
_TS_EXIT = pd.Timestamp("2024-01-12 06:00:00+00:00")


def _build_trade(
    side: str = "long",
    entry_open: float = 40000.0,
    exit_open: float = 42000.0,
    exit_reason: str = "invalidation",
    fees_bps: float = 5.0,
    slippage_bps: float = 2.5,
    invalidation_price: Optional[float] = 38000.0,
) -> Trade:
    return build_trade(
        signal_id="sig001",
        side=side,
        entry_time=_TS_ENTRY,
        entry_open=entry_open,
        exit_time=_TS_EXIT,
        exit_open=exit_open,
        exit_reason=exit_reason,
        position_size=1000.0,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        entry_region_low=39000.0,
        entry_region_high=41000.0,
        invalidation_price=invalidation_price,
        quality_score=0.3,
        dataset_version="v1",
    )


# ── compute_entry_fill ────────────────────────────────────────────────────────


class TestComputeEntryFill:
    def test_long_entry_fills_above_open(self):
        fill = compute_entry_fill(40000.0, "long", fees_bps=5.0, slippage_bps=2.5)
        assert fill > 40000.0

    def test_short_entry_fills_below_open(self):
        fill = compute_entry_fill(40000.0, "short", fees_bps=5.0, slippage_bps=2.5)
        assert fill < 40000.0

    def test_zero_adjustment_equals_open(self):
        fill = compute_entry_fill(40000.0, "long", fees_bps=0.0, slippage_bps=0.0)
        assert fill == pytest.approx(40000.0)

    def test_long_fill_formula(self):
        adj = (5.0 + 2.5) / 10_000.0
        expected = 40000.0 * (1.0 + adj)
        assert compute_entry_fill(40000.0, "long", 5.0, 2.5) == pytest.approx(expected)

    def test_short_fill_formula(self):
        adj = (5.0 + 2.5) / 10_000.0
        expected = 40000.0 * (1.0 - adj)
        assert compute_entry_fill(40000.0, "short", 5.0, 2.5) == pytest.approx(expected)

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            compute_entry_fill(40000.0, "neutral", 5.0, 2.5)


# ── compute_exit_fill ─────────────────────────────────────────────────────────


class TestComputeExitFill:
    def test_long_exit_fills_below_open(self):
        fill = compute_exit_fill(40000.0, "long", fees_bps=5.0, slippage_bps=2.5)
        assert fill < 40000.0

    def test_short_exit_fills_above_open(self):
        fill = compute_exit_fill(40000.0, "short", fees_bps=5.0, slippage_bps=2.5)
        assert fill > 40000.0

    def test_zero_adjustment_equals_open(self):
        fill = compute_exit_fill(40000.0, "long", fees_bps=0.0, slippage_bps=0.0)
        assert fill == pytest.approx(40000.0)

    def test_long_exit_formula(self):
        adj = (5.0 + 2.5) / 10_000.0
        expected = 40000.0 * (1.0 - adj)
        assert compute_exit_fill(40000.0, "long", 5.0, 2.5) == pytest.approx(expected)

    def test_short_exit_formula(self):
        adj = (5.0 + 2.5) / 10_000.0
        expected = 40000.0 * (1.0 + adj)
        assert compute_exit_fill(40000.0, "short", 5.0, 2.5) == pytest.approx(expected)

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            compute_exit_fill(40000.0, "bad", 5.0, 2.5)


# ── compute_fees_and_slippage ─────────────────────────────────────────────────


class TestComputeFeesAndSlippage:
    def test_nonzero_fees(self):
        cost = compute_fees_and_slippage(40000.0, 42000.0, 1000.0, 5.0, 2.5)
        assert cost > 0.0

    def test_zero_fees_and_slippage(self):
        cost = compute_fees_and_slippage(40000.0, 42000.0, 1000.0, 0.0, 0.0)
        assert cost == pytest.approx(0.0)

    def test_scales_with_notional(self):
        cost_1 = compute_fees_and_slippage(40000.0, 40000.0, 1000.0, 5.0, 2.5)
        cost_2 = compute_fees_and_slippage(40000.0, 40000.0, 2000.0, 5.0, 2.5)
        assert cost_2 == pytest.approx(cost_1 * 2.0)

    def test_always_positive(self):
        cost = compute_fees_and_slippage(40000.0, 38000.0, 1000.0, 5.0, 2.5)
        assert cost > 0.0


# ── compute_gross_pnl ─────────────────────────────────────────────────────────


class TestComputeGrossPnl:
    def test_long_profit(self):
        pnl = compute_gross_pnl(40000.0, 42000.0, 1000.0, "long")
        assert pnl > 0.0

    def test_long_loss(self):
        pnl = compute_gross_pnl(40000.0, 38000.0, 1000.0, "long")
        assert pnl < 0.0

    def test_short_profit(self):
        pnl = compute_gross_pnl(40000.0, 38000.0, 1000.0, "short")
        assert pnl > 0.0

    def test_short_loss(self):
        pnl = compute_gross_pnl(40000.0, 42000.0, 1000.0, "short")
        assert pnl < 0.0

    def test_long_pnl_formula(self):
        # units = 1000/40000 = 0.025; pnl = 0.025 * (42000-40000) = 50
        pnl = compute_gross_pnl(40000.0, 42000.0, 1000.0, "long")
        assert pnl == pytest.approx(50.0)

    def test_short_pnl_formula(self):
        pnl = compute_gross_pnl(40000.0, 38000.0, 1000.0, "short")
        assert pnl == pytest.approx(50.0)

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            compute_gross_pnl(40000.0, 42000.0, 1000.0, "neutral")

    def test_zero_entry_price_returns_zero(self):
        assert compute_gross_pnl(0.0, 1000.0, 1000.0, "long") == 0.0


# ── compute_position_size ─────────────────────────────────────────────────────


class TestComputePositionSize:
    def test_fixed_fraction(self):
        size = compute_position_size(100_000.0, "fixed_fraction", fraction=0.01)
        assert size == pytest.approx(1000.0)

    def test_fixed_fraction_scales_with_equity(self):
        size1 = compute_position_size(100_000.0, "fixed_fraction", fraction=0.01)
        size2 = compute_position_size(200_000.0, "fixed_fraction", fraction=0.01)
        assert size2 == pytest.approx(size1 * 2.0)

    def test_fixed_notional_ignores_equity(self):
        size1 = compute_position_size(100_000.0, "fixed_notional", fixed_notional=500.0)
        size2 = compute_position_size(999_999.0, "fixed_notional", fixed_notional=500.0)
        assert size1 == pytest.approx(500.0)
        assert size2 == pytest.approx(500.0)

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            compute_position_size(100_000.0, "variable")


# ── build_trade ───────────────────────────────────────────────────────────────


class TestBuildTrade:
    def test_determinism(self):
        t1 = _build_trade()
        t2 = _build_trade()
        assert t1.trade_id == t2.trade_id
        assert t1.net_pnl == pytest.approx(t2.net_pnl)

    def test_fees_positive_for_nonzero_costs(self):
        t = _build_trade(fees_bps=5.0, slippage_bps=2.5)
        assert t.fees_and_slippage > 0.0

    def test_fees_zero_for_zero_costs(self):
        t = _build_trade(fees_bps=0.0, slippage_bps=0.0)
        assert t.fees_and_slippage == pytest.approx(0.0)

    def test_net_pnl_equals_gross_minus_cost(self):
        t = _build_trade()
        assert t.net_pnl == pytest.approx(t.gross_pnl - t.fees_and_slippage)

    def test_long_profit_trade(self):
        t = _build_trade(side="long", entry_open=40000.0, exit_open=42000.0)
        assert t.gross_pnl > 0.0

    def test_short_profit_trade(self):
        t = _build_trade(side="short", entry_open=40000.0, exit_open=38000.0)
        assert t.gross_pnl > 0.0

    def test_r_multiple_defined_for_invalidation_price(self):
        t = _build_trade(invalidation_price=38000.0)
        assert t.r_multiple != 0.0

    def test_r_multiple_zero_when_no_invalidation(self):
        t = _build_trade(invalidation_price=None)
        assert t.r_multiple == 0.0

    def test_trade_id_includes_signal_id(self):
        t = _build_trade()
        assert "sig001" in t.trade_id

    def test_to_dict_keys(self):
        t = _build_trade()
        d = t.to_dict()
        required_keys = {
            "trade_id", "signal_id", "side", "entry_time", "entry_price",
            "exit_time", "exit_price", "exit_reason", "position_size",
            "gross_pnl", "fees_and_slippage", "net_pnl", "r_multiple",
            "entry_region_low", "entry_region_high", "quality_score",
        }
        assert required_keys.issubset(d.keys())

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            build_trade(
                signal_id="x", side="neutral",
                entry_time=_TS_ENTRY, entry_open=40000.0,
                exit_time=_TS_EXIT, exit_open=42000.0,
                exit_reason="invalidation", position_size=1000.0,
                fees_bps=5.0, slippage_bps=2.5,
                entry_region_low=39000.0, entry_region_high=41000.0,
                invalidation_price=None, quality_score=0.3,
                dataset_version="v1",
            )

    def test_invalid_exit_reason_raises(self):
        with pytest.raises(ValueError, match="exit_reason"):
            build_trade(
                signal_id="x", side="long",
                entry_time=_TS_ENTRY, entry_open=40000.0,
                exit_time=_TS_EXIT, exit_open=42000.0,
                exit_reason="bad_reason", position_size=1000.0,
                fees_bps=5.0, slippage_bps=2.5,
                entry_region_low=39000.0, entry_region_high=41000.0,
                invalidation_price=None, quality_score=0.3,
                dataset_version="v1",
            )

    def test_multiple_exit_reasons_valid(self):
        for reason in ("invalidation", "time_expired", "max_hold_bars", "end_of_data", "no_entry"):
            t = _build_trade(exit_reason=reason)
            assert t.exit_reason == reason

    def test_fees_not_double_charged(self):
        """Net PnL should be less than gross PnL (costs reduce profit)."""
        t = _build_trade(fees_bps=5.0, slippage_bps=2.5)
        assert t.net_pnl < t.gross_pnl


# ── Trade dataclass ───────────────────────────────────────────────────────────


class TestTradeDataclass:
    def test_valid_long_trade(self):
        t = _build_trade(side="long")
        assert t.side == "long"

    def test_valid_short_trade(self):
        t = _build_trade(side="short")
        assert t.side == "short"

    def test_invalid_side(self):
        with pytest.raises(ValueError):
            Trade(
                trade_id="t1", signal_id="s1", side="bad",
                entry_time=_TS_ENTRY, entry_price=40000.0, entry_open=40000.0,
                exit_time=_TS_EXIT, exit_price=42000.0, exit_open=42000.0,
                exit_reason="invalidation", position_size=1000.0,
                gross_pnl=50.0, fees_and_slippage=3.0, net_pnl=47.0,
                r_multiple=1.0,
                entry_region_low=39000.0, entry_region_high=41000.0,
                invalidation_price=38000.0, quality_score=0.3,
                dataset_version="v1",
            )

    def test_invalid_exit_reason(self):
        with pytest.raises(ValueError):
            Trade(
                trade_id="t1", signal_id="s1", side="long",
                entry_time=_TS_ENTRY, entry_price=40000.0, entry_open=40000.0,
                exit_time=_TS_EXIT, exit_price=42000.0, exit_open=42000.0,
                exit_reason="unknown_reason", position_size=1000.0,
                gross_pnl=50.0, fees_and_slippage=3.0, net_pnl=47.0,
                r_multiple=1.0,
                entry_region_low=39000.0, entry_region_high=41000.0,
                invalidation_price=38000.0, quality_score=0.3,
                dataset_version="v1",
            )
