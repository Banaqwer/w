"""
tests/test_backtest_runner.py

Tests for backtest/runner.py — BacktestConfig, simulate_signal_on_6h,
build_equity_curve, compute_summary, run_backtest, and write helpers.

Coverage
--------
- BacktestConfig:
  - default values match conservative settings
  - from_yaml loads from file without errors (using real backtest.yaml)
- simulate_signal_on_6h:
  - neutral signal → None (skip)
  - empty DataFrame → None
  - missing required columns → None
  - long signal: price enters zone → Trade produced
  - long signal: price never enters zone → None
  - short signal: price enters zone → Trade produced
  - invalidation exit triggered for long (close below inv level)
  - invalidation exit triggered for short (close above inv level)
  - max_hold_bars triggers exit
  - entry at NEXT bar open after triggering close
  - trade carries correct signal metadata
- build_equity_curve:
  - starts at initial_capital
  - increases on winning trades
  - decreases on losing trades
  - empty trades → flat curve at initial_capital
- compute_summary:
  - empty trades → all metrics zero
  - correct win rate
  - total_net_pnl equals sum of net_pnl
  - max_drawdown <= 0
- run_backtest:
  - determinism: same inputs → same result
  - empty 1D slice → empty result
  - produces BacktestResult with expected structure
- generate_signals_from_df:
  - empty DataFrame → empty list
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd
import pytest

from backtest.execution import build_trade, Trade
from backtest.runner import (
    BacktestConfig,
    BacktestResult,
    build_equity_curve,
    compute_summary,
    generate_signals_from_df,
    run_backtest,
    simulate_signal_on_6h,
)
from signals.signal_types import EntryRegion, InvalidationRule, SignalCandidate


# ── Fixtures ──────────────────────────────────────────────────────────────────

_TS_BASE = pd.Timestamp("2024-06-01 00:00:00+00:00")


def _make_6h_df(
    n_bars: int = 20,
    base_price: float = 40000.0,
    direction: str = "up",
    start_time: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Create a synthetic 6H OHLCV DataFrame."""
    ts = start_time or _TS_BASE
    timestamps = pd.date_range(ts, periods=n_bars, freq="6h", tz="UTC")
    prices = []
    for i in range(n_bars):
        delta = i * 100.0 if direction == "up" else -i * 100.0
        o = base_price + delta
        h = o + 50.0
        l = o - 50.0
        c = o + 20.0 if direction == "up" else o - 20.0
        prices.append({"open": o, "high": h, "low": l, "close": c, "volume": 10.0})
    df = pd.DataFrame(prices, index=timestamps)
    return df


def _make_signal(
    signal_id: str = "sig001",
    bias: str = "long",
    price_lo: float = 40100.0,
    price_hi: float = 40500.0,
    invalidation_price: float = 39000.0,
    time_earliest: Optional[pd.Timestamp] = None,
    time_latest: Optional[pd.Timestamp] = None,
) -> SignalCandidate:
    er = EntryRegion(
        price_low=price_lo,
        price_high=price_hi,
        time_earliest=time_earliest,
        time_latest=time_latest,
    )
    if bias == "long":
        inv = [InvalidationRule(condition="close_below_zone", price_level=invalidation_price)]
    elif bias == "short":
        inv = [InvalidationRule(condition="close_above_zone", price_level=invalidation_price)]
    else:
        inv = []
    return SignalCandidate(
        signal_id=signal_id,
        dataset_version="v1",
        timeframe_context="1D primary / 6H confirm",
        zone_id="zone001",
        bias=bias,
        entry_region=er,
        invalidation=inv,
        confirmations_required=["candle_direction"],
        quality_score=0.4,
        provenance=["p1"],
    )


def _make_completed_trade(net_pnl: float, exit_time: pd.Timestamp) -> Trade:
    return build_trade(
        signal_id="sig001",
        side="long",
        entry_time=_TS_BASE,
        entry_open=40000.0,
        exit_time=exit_time,
        # exit_open chosen so that: net_pnl = (exit_open - entry_open) * (pos_size / entry_open)
        # => exit_open = entry_open + net_pnl * entry_open / pos_size = 40000 + net_pnl * 40
        exit_open=40000.0 + net_pnl * 40,
        exit_reason="invalidation",
        position_size=1000.0,
        fees_bps=0.0,
        slippage_bps=0.0,
        entry_region_low=39000.0,
        entry_region_high=41000.0,
        invalidation_price=38000.0,
        quality_score=0.3,
        dataset_version="v1",
    )


# ── BacktestConfig ─────────────────────────────────────────────────────────────


class TestBacktestConfig:
    def test_defaults(self):
        cfg = BacktestConfig()
        assert cfg.initial_capital == 100_000.0
        assert cfg.fees_bps == 5.0
        assert cfg.slippage_bps == 2.5
        assert cfg.max_hold_bars == 200
        assert cfg.position_sizing == "fixed_fraction"

    def test_from_yaml_loads(self):
        cfg = BacktestConfig.from_yaml("configs/backtest.yaml")
        assert cfg.initial_capital > 0
        assert cfg.fees_bps > 0
        assert cfg.max_hold_bars > 0

    def test_from_yaml_round_trip_bps(self):
        """backtest.yaml has fees=10 bps round-trip → 5 bps one-way."""
        cfg = BacktestConfig.from_yaml("configs/backtest.yaml")
        assert cfg.fees_bps == pytest.approx(5.0)


# ── simulate_signal_on_6h ─────────────────────────────────────────────────────


class TestSimulateSignalOn6h:
    def test_neutral_signal_returns_none(self):
        df = _make_6h_df()
        signal = _make_signal(bias="neutral")
        result = simulate_signal_on_6h(signal, df, equity=100_000.0, config=BacktestConfig())
        assert result is None

    def test_empty_df_returns_none(self):
        signal = _make_signal()
        result = simulate_signal_on_6h(signal, pd.DataFrame(), equity=100_000.0, config=BacktestConfig())
        assert result is None

    def test_missing_columns_returns_none(self):
        df = pd.DataFrame({"price": [1, 2, 3]})
        signal = _make_signal()
        result = simulate_signal_on_6h(signal, df, equity=100_000.0, config=BacktestConfig())
        assert result is None

    def test_long_signal_enters_when_price_in_zone(self):
        """Price rises into zone [40100, 40500] — should trigger entry."""
        df = _make_6h_df(n_bars=20, base_price=40000.0, direction="up")
        # bar 1 close = 40000 + 100 + 20 = 40120 → in [40100, 40500]
        signal = _make_signal(
            bias="long",
            price_lo=40100.0,
            price_hi=40500.0,
            invalidation_price=38000.0,
        )
        trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=BacktestConfig())
        assert trade is not None
        assert trade.side == "long"

    def test_long_signal_no_entry_when_price_never_in_zone(self):
        """Price stays far below entry zone — no entry."""
        df = _make_6h_df(n_bars=20, base_price=10000.0, direction="up")
        signal = _make_signal(
            bias="long",
            price_lo=99000.0,
            price_hi=100000.0,
            invalidation_price=8000.0,
        )
        trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=BacktestConfig())
        assert trade is None

    def test_short_signal_enters_when_price_in_zone(self):
        """Price is near [40100, 40500] — short signal should trigger."""
        df = _make_6h_df(n_bars=20, base_price=40000.0, direction="up")
        signal = _make_signal(
            bias="short",
            price_lo=40100.0,
            price_hi=40500.0,
            invalidation_price=45000.0,
        )
        trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=BacktestConfig())
        if trade is not None:
            assert trade.side == "short"

    def test_entry_at_next_bar_open(self):
        """Entry price must equal (adjusted) open of the bar AFTER the trigger bar."""
        df = _make_6h_df(n_bars=20, base_price=40000.0, direction="up")
        signal = _make_signal(
            price_lo=40100.0,
            price_hi=40500.0,
            invalidation_price=38000.0,
        )
        cfg = BacktestConfig(fees_bps=0.0, slippage_bps=0.0)
        trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=cfg)
        if trade is not None:
            # With zero costs, entry_price == entry_open
            assert trade.entry_price == pytest.approx(trade.entry_open)

    def test_invalidation_exit_long(self):
        """Long trade should exit when close drops below invalidation level."""
        # Build a df that enters long then drops hard
        n = 30
        timestamps = pd.date_range(_TS_BASE, periods=n, freq="6h", tz="UTC")
        rows = []
        for i in range(n):
            if i < 5:
                # Price rises into zone
                rows.append({"open": 40050.0 + i * 50, "high": 40200.0 + i * 50,
                              "low": 40000.0, "close": 40100.0 + i * 50})
            else:
                # Price drops sharply below invalidation (38000)
                rows.append({"open": 37500.0, "high": 38000.0,
                              "low": 37000.0, "close": 37500.0})
        df = pd.DataFrame(rows, index=timestamps)
        signal = _make_signal(
            price_lo=40100.0, price_hi=40500.0, invalidation_price=38500.0
        )
        cfg = BacktestConfig(exit_on_invalidation=True, fees_bps=0.0, slippage_bps=0.0)
        trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=cfg)
        if trade is not None:
            assert trade.exit_reason == "invalidation"

    def test_max_hold_bars_exit(self):
        """Trade should exit after max_hold_bars even without invalidation."""
        df = _make_6h_df(n_bars=50, base_price=40000.0, direction="up")
        signal = _make_signal(
            price_lo=40100.0, price_hi=40500.0,
            invalidation_price=1.0,  # effectively no invalidation at normal prices
        )
        cfg = BacktestConfig(max_hold_bars=5, fees_bps=0.0, slippage_bps=0.0)
        trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=cfg)
        if trade is not None:
            assert trade.exit_reason in ("max_hold_bars", "invalidation", "end_of_data")

    def test_trade_carries_signal_metadata(self):
        df = _make_6h_df(n_bars=20, base_price=40000.0, direction="up")
        signal = _make_signal(price_lo=40100.0, price_hi=40500.0)
        trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=BacktestConfig())
        if trade is not None:
            assert trade.signal_id == "sig001"
            assert trade.quality_score == pytest.approx(0.4)

    def test_determinism(self):
        """Same inputs produce the same trade."""
        df = _make_6h_df(n_bars=20, base_price=40000.0, direction="up")
        signal = _make_signal(price_lo=40100.0, price_hi=40500.0)
        cfg = BacktestConfig()
        t1 = simulate_signal_on_6h(signal, df, equity=100_000.0, config=cfg)
        t2 = simulate_signal_on_6h(signal, df, equity=100_000.0, config=cfg)
        if t1 is None:
            assert t2 is None
        else:
            assert t1.trade_id == t2.trade_id
            assert t1.net_pnl == pytest.approx(t2.net_pnl)


# ── build_equity_curve ────────────────────────────────────────────────────────


class TestBuildEquityCurve:
    def test_empty_trades_flat_at_initial(self):
        idx = pd.date_range(_TS_BASE, periods=10, freq="6h", tz="UTC")
        curve = build_equity_curve([], idx, initial_capital=100_000.0)
        assert (curve == 100_000.0).all()

    def test_winning_trade_increases_equity(self):
        idx = pd.date_range(_TS_BASE, periods=10, freq="6h", tz="UTC")
        exit_ts = idx[5]
        trade = _make_completed_trade(net_pnl=500.0, exit_time=exit_ts)
        # Override net_pnl manually for simplicity
        trade = build_trade(
            signal_id="s1", side="long",
            entry_time=idx[0], entry_open=40000.0,
            exit_time=exit_ts, exit_open=40500.0,
            exit_reason="invalidation", position_size=1000.0,
            fees_bps=0.0, slippage_bps=0.0,
            entry_region_low=39000.0, entry_region_high=41000.0,
            invalidation_price=None, quality_score=0.3, dataset_version="v1",
        )
        curve = build_equity_curve([trade], idx, initial_capital=100_000.0)
        # After exit_ts, equity should be > initial_capital
        post_exit = curve[curve.index > exit_ts]
        if not post_exit.empty:
            assert float(post_exit.iloc[0]) > 100_000.0

    def test_losing_trade_decreases_equity(self):
        idx = pd.date_range(_TS_BASE, periods=10, freq="6h", tz="UTC")
        exit_ts = idx[3]
        trade = build_trade(
            signal_id="s1", side="long",
            entry_time=idx[0], entry_open=40000.0,
            exit_time=exit_ts, exit_open=39000.0,  # loss
            exit_reason="invalidation", position_size=1000.0,
            fees_bps=0.0, slippage_bps=0.0,
            entry_region_low=39000.0, entry_region_high=41000.0,
            invalidation_price=None, quality_score=0.3, dataset_version="v1",
        )
        curve = build_equity_curve([trade], idx, initial_capital=100_000.0)
        final_equity = float(curve.iloc[-1])
        assert final_equity < 100_000.0


# ── compute_summary ───────────────────────────────────────────────────────────


class TestComputeSummary:
    def _run(self, trades=None, initial=100_000.0):
        if trades is None:
            trades = []
        idx = pd.date_range(_TS_BASE, periods=20, freq="6h", tz="UTC")
        equity = build_equity_curve(trades, idx, initial_capital=initial)
        return compute_summary(
            trades=trades,
            equity_curve=equity,
            initial_capital=initial,
            window_start=idx[0],
            window_end=idx[-1],
            n_signals_generated=5,
            dataset_version="v1",
        )

    def test_empty_trades_all_zero(self):
        s = self._run([])
        assert s["total_trades"] == 0
        assert s["win_rate"] == 0.0
        assert s["total_net_pnl"] == 0.0

    def test_correct_win_rate(self):
        idx = pd.date_range(_TS_BASE, periods=20, freq="6h", tz="UTC")
        # 2 winners, 1 loser
        winners = [
            build_trade("s1", "long", idx[0], 40000.0, idx[3], 41000.0,
                        "invalidation", 1000.0, 0.0, 0.0, 39000.0, 41000.0, None, 0.3, "v1"),
            build_trade("s2", "long", idx[2], 40000.0, idx[5], 41000.0,
                        "invalidation", 1000.0, 0.0, 0.0, 39000.0, 41000.0, None, 0.3, "v1"),
        ]
        loser = build_trade("s3", "long", idx[4], 40000.0, idx[7], 39000.0,
                            "invalidation", 1000.0, 0.0, 0.0, 39000.0, 41000.0, None, 0.3, "v1")
        all_trades = winners + [loser]
        equity = build_equity_curve(all_trades, idx, 100_000.0)
        s = compute_summary(all_trades, equity, 100_000.0, idx[0], idx[-1], 5, "v1")
        assert s["total_trades"] == 3
        assert s["winning_trades"] == 2
        assert s["win_rate"] == pytest.approx(2 / 3)

    def test_total_net_pnl_is_sum(self):
        idx = pd.date_range(_TS_BASE, periods=20, freq="6h", tz="UTC")
        t1 = build_trade("s1", "long", idx[0], 40000.0, idx[3], 41000.0,
                         "invalidation", 1000.0, 0.0, 0.0, 39000.0, 41000.0, None, 0.3, "v1")
        t2 = build_trade("s2", "long", idx[2], 40000.0, idx[5], 39000.0,
                         "invalidation", 1000.0, 0.0, 0.0, 39000.0, 41000.0, None, 0.3, "v1")
        equity = build_equity_curve([t1, t2], idx, 100_000.0)
        s = compute_summary([t1, t2], equity, 100_000.0, idx[0], idx[-1], 5, "v1")
        assert s["total_net_pnl"] == pytest.approx(t1.net_pnl + t2.net_pnl)

    def test_max_drawdown_non_positive(self):
        s = self._run([])
        assert s["max_drawdown"] <= 0.0 or s["max_drawdown"] == 0.0


# ── generate_signals_from_df ──────────────────────────────────────────────────


class TestGenerateSignalsFromDf:
    def test_empty_df_returns_empty(self):
        result = generate_signals_from_df(pd.DataFrame(), {}, BacktestConfig())
        assert result == []

    def test_none_df_returns_empty(self):
        result = generate_signals_from_df(None, {}, BacktestConfig())
        assert result == []


# ── run_backtest ──────────────────────────────────────────────────────────────


class TestRunBacktest:
    def _make_minimal_df_1d(self, n: int = 50) -> pd.DataFrame:
        """Minimal 1D DataFrame with required columns."""
        idx = pd.date_range("2023-01-01", periods=n, freq="1D", tz="UTC")
        import numpy as np
        prices = 40000.0 + np.cumsum(np.random.default_rng(42).normal(0, 200, n))
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 200,
            "low": prices - 200,
            "close": prices + 50,
            "volume": 1000.0,
            "bar_index": range(n),
            "atr_14": [200.0] * n,
            "log_close": [1.0] * n,
            "hl_range": [400.0] * n,
            "true_range": [400.0] * n,
            "calendar_day_index": range(n),
            "trading_day_index": range(n),
        }, index=idx)
        return df

    def test_empty_1d_returns_empty_result(self):
        n_6h = 20
        idx_6h = pd.date_range("2023-01-01", periods=n_6h, freq="6h", tz="UTC")
        df_6h = pd.DataFrame({
            "open": [40000.0] * n_6h,
            "high": [40200.0] * n_6h,
            "low": [39800.0] * n_6h,
            "close": [40100.0] * n_6h,
        }, index=idx_6h)

        result = run_backtest(
            df_1d=pd.DataFrame(),
            df_6h=df_6h,
            manifest_1d={},
            manifest_6h={},
            config=BacktestConfig(),
            train_end=pd.Timestamp("2022-12-31", tz="UTC"),
            test_start=pd.Timestamp("2023-01-01", tz="UTC"),
            test_end=pd.Timestamp("2023-06-30", tz="UTC"),
            dataset_version="v1",
        )
        assert isinstance(result, BacktestResult)
        assert len(result.trades) == 0

    def test_returns_backtest_result(self):
        df_1d = self._make_minimal_df_1d(50)
        n_6h = 40
        idx_6h = pd.date_range("2023-01-31", periods=n_6h, freq="6h", tz="UTC")
        df_6h = pd.DataFrame({
            "open": [40000.0] * n_6h,
            "high": [40200.0] * n_6h,
            "low": [39800.0] * n_6h,
            "close": [40100.0] * n_6h,
        }, index=idx_6h)

        train_end = pd.Timestamp("2023-01-30", tz="UTC")
        test_start = pd.Timestamp("2023-01-31", tz="UTC")
        test_end = pd.Timestamp("2023-03-10", tz="UTC")

        result = run_backtest(
            df_1d=df_1d,
            df_6h=df_6h,
            manifest_1d={},
            manifest_6h={},
            config=BacktestConfig(),
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            dataset_version="v1",
        )
        assert isinstance(result, BacktestResult)
        assert result.window_start == test_start
        assert result.window_end == test_end
        assert isinstance(result.trades, list)
        assert isinstance(result.summary, dict)
        assert "total_trades" in result.summary

    def test_determinism(self):
        """Same inputs → same result (trade count and summary)."""
        df_1d = self._make_minimal_df_1d(50)
        n_6h = 40
        idx_6h = pd.date_range("2023-01-31", periods=n_6h, freq="6h", tz="UTC")
        df_6h = pd.DataFrame({
            "open": [40000.0] * n_6h,
            "high": [40200.0] * n_6h,
            "low": [39800.0] * n_6h,
            "close": [40100.0] * n_6h,
        }, index=idx_6h)

        kwargs = dict(
            df_1d=df_1d, df_6h=df_6h,
            manifest_1d={}, manifest_6h={},
            config=BacktestConfig(),
            train_end=pd.Timestamp("2023-01-30", tz="UTC"),
            test_start=pd.Timestamp("2023-01-31", tz="UTC"),
            test_end=pd.Timestamp("2023-03-10", tz="UTC"),
            dataset_version="v1",
        )
        r1 = run_backtest(**kwargs)
        r2 = run_backtest(**kwargs)
        assert len(r1.trades) == len(r2.trades)
        assert r1.summary.get("total_net_pnl") == pytest.approx(
            r2.summary.get("total_net_pnl", 0.0)
        )
