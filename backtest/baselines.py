"""
backtest/baselines.py

Phase 7 — Deterministic baseline strategies.

Provides three simple baseline backtests that use the same execution and cost
model as the main Jenkins backtest (Phase 6).  Baseline results are comparable
to the main strategy because they share:

- Identical fill model (next-bar open, fees+slippage from config).
- Identical position sizing (fixed_fraction or fixed_notional).
- Identical exit logic (max_hold_bars safety valve).
- Identical equity curve and metric computation.

Baselines are NOT expected to be profitable.  Their purpose is to measure what
a naive, signal-free strategy achieves on the same data, enabling apples-to-
apples comparison with the Jenkins signal-based strategy.

Available baselines
-------------------
1. :class:`RandomEntryBaseline` — random long/short entries with a fixed seed.
   Seeded deterministically so repeated runs produce identical results.
2. :class:`MACrossoverBaseline` — simple moving-average crossover (fast/slow).
   Long when fast MA > slow MA; short when fast MA < slow MA.
3. :class:`BreakoutBaseline` — N-day high/low breakout.
   Long on close above N-bar high; short on close below N-bar low.

All baselines expose a ``run(df_6h, config, dataset_version)`` method that
returns a :class:`BaselineResult` compatible with the Phase 6 reporting format.

Design rules
------------
- Fully deterministic (seeded random, pure MA/breakout logic).
- No lookahead: at bar *i*, only bars ``[:i+1]`` are used.
- Same entry timing as main strategy: **next bar's open** after signal.
- Uses :func:`backtest.execution.build_trade` for fill computation.
- Returns a result dict that mirrors ``BacktestResult.summary`` structure.

Walk-forward usage
------------------
Pass each baseline's ``run()`` call the test-window DataFrame only.  The
baselines do not use the training window (they have no fit step).

References
----------
backtest/execution.py — build_trade, compute_position_size
backtest/metrics.py — compute_equity_metrics
backtest/runner.py — build_equity_curve
ASSUMPTIONS.md — Phase 7 section
PROJECT_STATUS.md — Phase 7 section
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.execution import build_trade, compute_position_size, Trade
from backtest.metrics import compute_equity_metrics
from backtest.runner import BacktestConfig, build_equity_curve

logger = logging.getLogger(__name__)

# Bars per year for 6H data (annualisation factor used by metrics)
_BARS_PER_YEAR_6H = 252 * 4  # 1008


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class BaselineResult:
    """Result of a baseline backtest run.

    Structure mirrors :class:`backtest.runner.BacktestResult` for comparability.
    """

    baseline_name: str
    trades: List[Trade] = field(default_factory=list)
    equity_curve: "pd.Series" = field(default_factory=lambda: pd.Series(dtype=float))
    summary: Dict[str, Any] = field(default_factory=dict)
    dataset_version: str = ""

    def to_dict(self) -> dict:
        return {
            "baseline_name": self.baseline_name,
            "n_trades": len(self.trades),
            "dataset_version": self.dataset_version,
            "summary": self.summary,
        }


# ── Shared helpers ────────────────────────────────────────────────────────────


def _build_baseline_summary(
    baseline_name: str,
    trades: List[Trade],
    equity_curve: pd.Series,
    initial_capital: float,
    dataset_version: str,
) -> dict:
    """Compute the standard summary dict for a baseline run."""
    n = len(trades)
    metrics = compute_equity_metrics(
        equity_curve=equity_curve,
        bars_per_year=_BARS_PER_YEAR_6H,
        initial_capital=initial_capital,
    )

    if n == 0:
        return {
            "baseline_name": baseline_name,
            "total_trades": 0,
            "winning_trades": 0,
            "win_rate": 0.0,
            "total_net_pnl": 0.0,
            "avg_net_pnl": 0.0,
            "avg_r_multiple": 0.0,
            "expectancy": 0.0,
            "dataset_version": dataset_version,
            **metrics,
        }

    net_pnls = [t.net_pnl for t in trades]
    winners = sum(1 for p in net_pnls if p > 0)
    total_net = sum(net_pnls)
    avg_net = total_net / n
    r_mults = [t.r_multiple for t in trades if t.invalidation_price is not None]
    avg_r = sum(r_mults) / len(r_mults) if r_mults else 0.0
    avg_pos = sum(t.position_size for t in trades) / n
    expectancy = avg_net / avg_pos if avg_pos > 0 else 0.0

    return {
        "baseline_name": baseline_name,
        "total_trades": n,
        "winning_trades": winners,
        "win_rate": winners / n,
        "total_net_pnl": total_net,
        "avg_net_pnl": avg_net,
        "avg_r_multiple": avg_r,
        "expectancy": expectancy,
        "dataset_version": dataset_version,
        **metrics,
    }


def _simulate_trades_from_signals(
    signals: List[Dict[str, Any]],
    df_6h: pd.DataFrame,
    config: BacktestConfig,
    dataset_version: str,
) -> List[Trade]:
    """Simulate trades from a list of synthetic signal dicts.

    Each signal dict must contain:
    - ``signal_id``: str
    - ``side``: "long" or "short"
    - ``entry_bar_idx``: int — index in df_6h where entry is triggered
    - ``invalidation_price``: Optional[float]
    - ``quality_score``: float (default 0.5 for baselines)

    Entry is at the open of bar ``entry_bar_idx + 1`` (next_bar_open).
    Exit is at ``max_hold_bars`` or end of data.
    """
    trades: List[Trade] = []
    equity = config.initial_capital

    for sig in signals:
        entry_idx = sig["entry_bar_idx"] + 1  # next bar open
        if entry_idx >= len(df_6h):
            continue

        entry_open = float(df_6h.iloc[entry_idx]["open"])
        side = sig["side"]
        inv_price = sig.get("invalidation_price")

        position_size = compute_position_size(
            equity=equity,
            sizing_mode=config.position_sizing,
            fraction=config.fraction,
            fixed_notional=config.fixed_notional,
        )

        # Determine exit bar
        exit_idx = None
        exit_reason = "end_of_data"

        for j in range(entry_idx + 1, len(df_6h)):
            bars_held = j - entry_idx
            close_j = float(df_6h.iloc[j]["close"])

            if bars_held >= config.max_hold_bars:
                exit_idx = j
                exit_reason = "max_hold_bars"
                break

            if config.exit_on_invalidation and inv_price is not None:
                if side == "long" and close_j < inv_price:
                    exit_idx = min(j + 1, len(df_6h) - 1)
                    exit_reason = "invalidation"
                    break
                if side == "short" and close_j > inv_price:
                    exit_idx = min(j + 1, len(df_6h) - 1)
                    exit_reason = "invalidation"
                    break

        if exit_idx is None:
            exit_idx = len(df_6h) - 1
            exit_reason = "end_of_data"

        exit_open = float(df_6h.iloc[exit_idx]["open"])

        trade = build_trade(
            signal_id=sig["signal_id"],
            side=side,
            entry_time=df_6h.index[entry_idx],
            entry_open=entry_open,
            exit_time=df_6h.index[exit_idx],
            exit_open=exit_open,
            exit_reason=exit_reason,
            position_size=position_size,
            fees_bps=config.fees_bps,
            slippage_bps=config.slippage_bps,
            entry_region_low=entry_open,
            entry_region_high=entry_open,
            invalidation_price=inv_price,
            quality_score=sig.get("quality_score", 0.5),
            dataset_version=dataset_version,
        )
        trades.append(trade)
        equity += trade.net_pnl

    return trades


# ── Baseline 1: Random entry ──────────────────────────────────────────────────


@dataclass
class RandomEntryBaseline:
    """Random long/short entry baseline.

    At each bar, with probability ``entry_prob``, generate a random entry
    (long or short with equal probability).  Only one position is held at
    a time.

    Deterministic: seeded by ``seed``.

    Parameters
    ----------
    seed:
        Random seed for reproducibility.  Default 42.
    entry_prob:
        Probability of generating an entry signal at each bar.  Default 0.05
        (5% of bars; roughly 1 trade per 20 bars on 6H data).
    """

    seed: int = 42
    entry_prob: float = 0.05
    name: str = "random_entry"

    def run(
        self,
        df_6h: pd.DataFrame,
        config: BacktestConfig,
        dataset_version: str = "",
    ) -> BaselineResult:
        """Run the random entry baseline on ``df_6h``.

        Parameters
        ----------
        df_6h:
            6H OHLCV DataFrame for the test window, sorted by index.
        config:
            Backtest config (for execution params and cost model).
        dataset_version:
            Dataset version string (for audit).

        Returns
        -------
        :class:`BaselineResult`
        """
        if df_6h.empty or not {"open", "high", "low", "close"}.issubset(df_6h.columns):
            return BaselineResult(
                baseline_name=self.name,
                dataset_version=dataset_version,
                summary=_build_baseline_summary(
                    self.name, [], pd.Series(dtype=float), config.initial_capital, dataset_version
                ),
            )

        rng = random.Random(self.seed)
        signals: List[Dict[str, Any]] = []
        in_trade = False

        for i in range(len(df_6h) - 1):
            if in_trade:
                continue  # one position at a time
            if rng.random() < self.entry_prob:
                side = "long" if rng.random() < 0.5 else "short"
                close = float(df_6h.iloc[i]["close"])
                # Invalidation: ±5% from entry close
                if side == "long":
                    inv = close * 0.95
                else:
                    inv = close * 1.05
                signals.append({
                    "signal_id": f"rnd_{i}",
                    "side": side,
                    "entry_bar_idx": i,
                    "invalidation_price": inv,
                    "quality_score": 0.5,
                })
                in_trade = True

        trades = _simulate_trades_from_signals(signals, df_6h, config, dataset_version)
        equity_curve = build_equity_curve(trades, df_6h.index, config.initial_capital)

        summary = _build_baseline_summary(
            self.name, trades, equity_curve, config.initial_capital, dataset_version
        )
        return BaselineResult(
            baseline_name=self.name,
            trades=trades,
            equity_curve=equity_curve,
            summary=summary,
            dataset_version=dataset_version,
        )


# ── Baseline 2: MA crossover ──────────────────────────────────────────────────


@dataclass
class MACrossoverBaseline:
    """Simple moving-average crossover baseline.

    Long when fast MA crosses above slow MA; short when fast MA crosses below
    slow MA.  One position at a time.  Entry on the close bar's signal; fill
    at next bar's open.

    Parameters
    ----------
    fast_period:
        Fast MA window (bars).  Default 10.
    slow_period:
        Slow MA window (bars).  Default 40.
    """

    fast_period: int = 10
    slow_period: int = 40
    name: str = "ma_crossover"

    def run(
        self,
        df_6h: pd.DataFrame,
        config: BacktestConfig,
        dataset_version: str = "",
    ) -> BaselineResult:
        """Run the MA crossover baseline.

        Parameters
        ----------
        df_6h:
            6H OHLCV DataFrame for the test window, sorted by index.
        config:
            Backtest config (execution params and cost model).
        dataset_version:
            Dataset version string.

        Returns
        -------
        :class:`BaselineResult`
        """
        if df_6h.empty or "close" not in df_6h.columns:
            return BaselineResult(
                baseline_name=self.name,
                dataset_version=dataset_version,
                summary=_build_baseline_summary(
                    self.name, [], pd.Series(dtype=float), config.initial_capital, dataset_version
                ),
            )

        closes = df_6h["close"].astype(float)
        fast_ma = closes.rolling(self.fast_period, min_periods=self.fast_period).mean()
        slow_ma = closes.rolling(self.slow_period, min_periods=self.slow_period).mean()

        signals: List[Dict[str, Any]] = []
        current_side: Optional[str] = None
        open_signal_idx: Optional[int] = None

        for i in range(self.slow_period, len(df_6h) - 1):
            fma = fast_ma.iloc[i]
            sma = slow_ma.iloc[i]
            fma_prev = fast_ma.iloc[i - 1]
            sma_prev = slow_ma.iloc[i - 1]

            if pd.isna(fma) or pd.isna(sma) or pd.isna(fma_prev) or pd.isna(sma_prev):
                continue

            cross_up = (fma_prev <= sma_prev) and (fma > sma)
            cross_down = (fma_prev >= sma_prev) and (fma < sma)

            if cross_up and current_side != "long":
                # Close any existing short
                if current_side == "short" and open_signal_idx is not None:
                    signals[-1]["exit_forced_at"] = i  # marker; not used by _simulate
                current_side = "long"
                open_signal_idx = i
                close = float(df_6h.iloc[i]["close"])
                signals.append({
                    "signal_id": f"mac_long_{i}",
                    "side": "long",
                    "entry_bar_idx": i,
                    "invalidation_price": close * 0.9,  # loose stop
                    "quality_score": 0.5,
                })
            elif cross_down and current_side != "short":
                if current_side == "long" and open_signal_idx is not None:
                    signals[-1]["exit_forced_at"] = i
                current_side = "short"
                open_signal_idx = i
                close = float(df_6h.iloc[i]["close"])
                signals.append({
                    "signal_id": f"mac_short_{i}",
                    "side": "short",
                    "entry_bar_idx": i,
                    "invalidation_price": close * 1.1,  # loose stop
                    "quality_score": 0.5,
                })

        trades = _simulate_trades_from_signals(signals, df_6h, config, dataset_version)
        equity_curve = build_equity_curve(trades, df_6h.index, config.initial_capital)

        summary = _build_baseline_summary(
            self.name, trades, equity_curve, config.initial_capital, dataset_version
        )
        return BaselineResult(
            baseline_name=self.name,
            trades=trades,
            equity_curve=equity_curve,
            summary=summary,
            dataset_version=dataset_version,
        )


# ── Baseline 3: Breakout ──────────────────────────────────────────────────────


@dataclass
class BreakoutBaseline:
    """N-bar high/low breakout baseline.

    Long when the close exceeds the highest close of the previous ``lookback``
    bars.  Short when the close falls below the lowest close of the previous
    ``lookback`` bars.  One position at a time.

    Parameters
    ----------
    lookback:
        Number of bars to compute the high/low channel.  Default 20.
    """

    lookback: int = 20
    name: str = "breakout"

    def run(
        self,
        df_6h: pd.DataFrame,
        config: BacktestConfig,
        dataset_version: str = "",
    ) -> BaselineResult:
        """Run the breakout baseline.

        Parameters
        ----------
        df_6h:
            6H OHLCV DataFrame for the test window, sorted by index.
        config:
            Backtest config (execution params and cost model).
        dataset_version:
            Dataset version string.

        Returns
        -------
        :class:`BaselineResult`
        """
        if df_6h.empty or "close" not in df_6h.columns:
            return BaselineResult(
                baseline_name=self.name,
                dataset_version=dataset_version,
                summary=_build_baseline_summary(
                    self.name, [], pd.Series(dtype=float), config.initial_capital, dataset_version
                ),
            )

        closes = df_6h["close"].astype(float)
        # Shift by 1 so at bar i we see the max/min of bars [i-lookback, i-1]
        # (no lookahead)
        rolling_high = closes.shift(1).rolling(self.lookback, min_periods=self.lookback).max()
        rolling_low = closes.shift(1).rolling(self.lookback, min_periods=self.lookback).min()

        signals: List[Dict[str, Any]] = []
        current_side: Optional[str] = None

        for i in range(self.lookback + 1, len(df_6h) - 1):
            rh = rolling_high.iloc[i]
            rl = rolling_low.iloc[i]
            close = float(closes.iloc[i])

            if pd.isna(rh) or pd.isna(rl):
                continue

            if close > rh and current_side != "long":
                current_side = "long"
                signals.append({
                    "signal_id": f"bo_long_{i}",
                    "side": "long",
                    "entry_bar_idx": i,
                    "invalidation_price": float(rl),  # exit if close drops below channel low
                    "quality_score": 0.5,
                })
            elif close < rl and current_side != "short":
                current_side = "short"
                signals.append({
                    "signal_id": f"bo_short_{i}",
                    "side": "short",
                    "entry_bar_idx": i,
                    "invalidation_price": float(rh),  # exit if close rises above channel high
                    "quality_score": 0.5,
                })

        trades = _simulate_trades_from_signals(signals, df_6h, config, dataset_version)
        equity_curve = build_equity_curve(trades, df_6h.index, config.initial_capital)

        summary = _build_baseline_summary(
            self.name, trades, equity_curve, config.initial_capital, dataset_version
        )
        return BaselineResult(
            baseline_name=self.name,
            trades=trades,
            equity_curve=equity_curve,
            summary=summary,
            dataset_version=dataset_version,
        )
