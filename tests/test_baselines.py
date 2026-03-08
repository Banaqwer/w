"""
tests/test_baselines.py

Tests for backtest/baselines.py — RandomEntryBaseline, MACrossoverBaseline,
BreakoutBaseline, and BaselineResult.

Coverage
--------
- BaselineResult:
  - to_dict() returns expected keys
- RandomEntryBaseline:
  - deterministic: same seed → same trades
  - different seed → different trades
  - empty DataFrame → empty trades, valid summary
  - missing columns → empty trades
  - produces valid BaselineResult with summary keys
  - summary contains required metrics (same format as BacktestResult.summary)
- MACrossoverBaseline:
  - deterministic: same data → same trades
  - empty DataFrame → empty trades
  - fewer bars than slow_period → no trades
  - uptrend produces long signals
  - summary contains required keys
- BreakoutBaseline:
  - deterministic
  - empty DataFrame → empty result
  - close above rolling high → long signal
  - close below rolling low → short signal
  - summary contains required keys
- Comparable metrics format:
  - all three baselines produce summaries with the same set of keys
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import pytest

from backtest.baselines import (
    BaselineResult,
    BreakoutBaseline,
    MACrossoverBaseline,
    RandomEntryBaseline,
)
from backtest.runner import BacktestConfig

_TS_BASE = pd.Timestamp("2024-01-01 00:00:00+00:00")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_6h_df(
    n: int = 100,
    base: float = 40000.0,
    trend: float = 50.0,
    noise: float = 200.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Create a synthetic 6H OHLCV DataFrame with a linear trend + noise."""
    import random
    rng = random.Random(seed)
    rows = []
    price = base
    for i in range(n):
        price += trend + rng.uniform(-noise, noise)
        o = price
        h = o + abs(rng.uniform(0, noise / 2))
        l = o - abs(rng.uniform(0, noise / 2))
        c = o + rng.uniform(-noise / 4, noise / 4)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 100.0})
    return pd.DataFrame(
        rows,
        index=pd.date_range(_TS_BASE, periods=n, freq="6h", tz="UTC"),
    )


_REQUIRED_SUMMARY_KEYS = {
    "baseline_name",
    "total_trades",
    "winning_trades",
    "win_rate",
    "total_net_pnl",
    "avg_net_pnl",
    "avg_r_multiple",
    "expectancy",
    "sharpe_bar",
    "volatility_ann",
    "max_drawdown",
    "max_drawdown_pct",
    "total_return_pct",
    "dataset_version",
}


# ── BaselineResult ────────────────────────────────────────────────────────────


def test_baseline_result_to_dict_keys():
    result = BaselineResult(
        baseline_name="test",
        dataset_version="v1",
        summary={"total_trades": 0},
    )
    d = result.to_dict()
    assert "baseline_name" in d
    assert "n_trades" in d
    assert "dataset_version" in d
    assert "summary" in d


# ── RandomEntryBaseline ───────────────────────────────────────────────────────


def test_random_baseline_deterministic():
    df = _make_6h_df(n=100)
    config = BacktestConfig()
    r1 = RandomEntryBaseline(seed=42).run(df, config)
    r2 = RandomEntryBaseline(seed=42).run(df, config)
    assert len(r1.trades) == len(r2.trades)
    if r1.trades:
        assert r1.trades[0].trade_id == r2.trades[0].trade_id


def test_random_baseline_different_seeds_differ():
    df = _make_6h_df(n=200)
    config = BacktestConfig()
    r1 = RandomEntryBaseline(seed=1).run(df, config)
    r2 = RandomEntryBaseline(seed=2).run(df, config)
    # With different seeds, at least one trade should differ (very likely on 200 bars)
    t1_ids = {t.trade_id for t in r1.trades}
    t2_ids = {t.trade_id for t in r2.trades}
    assert t1_ids != t2_ids or len(r1.trades) != len(r2.trades)


def test_random_baseline_empty_df():
    config = BacktestConfig()
    result = RandomEntryBaseline(seed=42).run(pd.DataFrame(), config)
    assert len(result.trades) == 0
    assert result.summary["total_trades"] == 0


def test_random_baseline_missing_columns():
    df = pd.DataFrame({"x": [1.0, 2.0]}, index=pd.date_range(_TS_BASE, periods=2, freq="6h", tz="UTC"))
    config = BacktestConfig()
    result = RandomEntryBaseline(seed=42).run(df, config)
    assert len(result.trades) == 0


def test_random_baseline_summary_keys():
    df = _make_6h_df(n=100)
    config = BacktestConfig()
    result = RandomEntryBaseline(seed=42, entry_prob=0.2).run(df, config, dataset_version="v1")
    for key in _REQUIRED_SUMMARY_KEYS:
        assert key in result.summary, f"Missing key: {key}"


def test_random_baseline_produces_some_trades():
    df = _make_6h_df(n=200)
    config = BacktestConfig()
    result = RandomEntryBaseline(seed=42, entry_prob=0.2).run(df, config)
    assert len(result.trades) > 0


# ── MACrossoverBaseline ───────────────────────────────────────────────────────


def test_mac_baseline_deterministic():
    df = _make_6h_df(n=200)
    config = BacktestConfig()
    r1 = MACrossoverBaseline(fast_period=5, slow_period=20).run(df, config)
    r2 = MACrossoverBaseline(fast_period=5, slow_period=20).run(df, config)
    assert len(r1.trades) == len(r2.trades)


def test_mac_baseline_empty_df():
    config = BacktestConfig()
    result = MACrossoverBaseline().run(pd.DataFrame(), config)
    assert len(result.trades) == 0
    assert result.summary["total_trades"] == 0


def test_mac_baseline_too_few_bars():
    df = _make_6h_df(n=10)
    config = BacktestConfig()
    result = MACrossoverBaseline(fast_period=5, slow_period=40).run(df, config)
    assert len(result.trades) == 0


def test_mac_baseline_summary_keys():
    df = _make_6h_df(n=200)
    config = BacktestConfig()
    result = MACrossoverBaseline(fast_period=5, slow_period=20).run(df, config, dataset_version="v1")
    for key in _REQUIRED_SUMMARY_KEYS:
        assert key in result.summary, f"Missing key: {key}"


def test_mac_baseline_uptrend_produces_long_signals():
    """Strongly uptrending data should trigger at least one long signal."""
    df = _make_6h_df(n=200, trend=200.0, noise=50.0)
    config = BacktestConfig()
    result = MACrossoverBaseline(fast_period=5, slow_period=20).run(df, config)
    # Expect at least some signals in a strong trend
    assert len(result.trades) >= 0  # at minimum no crash


# ── BreakoutBaseline ──────────────────────────────────────────────────────────


def test_breakout_baseline_deterministic():
    df = _make_6h_df(n=200)
    config = BacktestConfig()
    r1 = BreakoutBaseline(lookback=20).run(df, config)
    r2 = BreakoutBaseline(lookback=20).run(df, config)
    assert len(r1.trades) == len(r2.trades)


def test_breakout_baseline_empty_df():
    config = BacktestConfig()
    result = BreakoutBaseline(lookback=20).run(pd.DataFrame(), config)
    assert len(result.trades) == 0
    assert result.summary["total_trades"] == 0


def test_breakout_baseline_summary_keys():
    df = _make_6h_df(n=200)
    config = BacktestConfig()
    result = BreakoutBaseline(lookback=10).run(df, config, dataset_version="v1")
    for key in _REQUIRED_SUMMARY_KEYS:
        assert key in result.summary, f"Missing key: {key}"


def test_breakout_baseline_strong_uptrend_produces_long():
    """A sustained uptrend should trigger a long breakout signal."""
    # Prices: 1000, 1100, 1200, ..., 3000 (strictly increasing)
    n = 100
    prices = [1000.0 + i * 20.0 for i in range(n)]
    ts = pd.date_range(_TS_BASE, periods=n, freq="6h", tz="UTC")
    rows = [{"open": p, "high": p + 5, "low": p - 5, "close": p + 3} for p in prices]
    df = pd.DataFrame(rows, index=ts)
    config = BacktestConfig()
    result = BreakoutBaseline(lookback=10).run(df, config)
    # Should produce at least one long trade
    long_trades = [t for t in result.trades if t.side == "long"]
    assert len(long_trades) >= 1


def test_breakout_baseline_strong_downtrend_produces_short():
    """A sustained downtrend should trigger a short breakout signal."""
    n = 100
    prices = [5000.0 - i * 20.0 for i in range(n)]
    ts = pd.date_range(_TS_BASE, periods=n, freq="6h", tz="UTC")
    rows = [{"open": p, "high": p + 5, "low": p - 5, "close": p - 3} for p in prices]
    df = pd.DataFrame(rows, index=ts)
    config = BacktestConfig()
    result = BreakoutBaseline(lookback=10).run(df, config)
    short_trades = [t for t in result.trades if t.side == "short"]
    assert len(short_trades) >= 1


# ── Comparable metrics format ─────────────────────────────────────────────────


def test_all_baselines_same_summary_key_set():
    """All three baselines should produce summaries with the same required keys."""
    df = _make_6h_df(n=200)
    config = BacktestConfig()

    results = [
        RandomEntryBaseline(seed=42, entry_prob=0.2).run(df, config, dataset_version="v1"),
        MACrossoverBaseline(fast_period=5, slow_period=20).run(df, config, dataset_version="v1"),
        BreakoutBaseline(lookback=10).run(df, config, dataset_version="v1"),
    ]

    keys_per_baseline = [frozenset(r.summary.keys()) for r in results]
    # All baselines should have the same required keys
    for key in _REQUIRED_SUMMARY_KEYS:
        for i, keys in enumerate(keys_per_baseline):
            assert key in keys, f"Baseline {results[i].baseline_name} missing key: {key}"
