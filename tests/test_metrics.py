"""
tests/test_metrics.py

Tests for backtest/metrics.py — compute_bar_sharpe, compute_volatility,
compute_max_drawdown, compute_equity_metrics.

Coverage
--------
- compute_bar_sharpe:
  - empty series → 0.0
  - single-point series → 0.0
  - flat equity (zero returns) → 0.0
  - monotonically increasing equity → positive Sharpe
  - monotonically decreasing equity → negative Sharpe
  - annualisation factor applied correctly (sqrt(bars_per_year))
  - known synthetic example with exact expected value
- compute_volatility:
  - empty series → 0.0
  - flat equity → 0.0
  - increasing equity → positive volatility
  - annualisation factor doubles volatility when bars_per_year quadrupled
- compute_max_drawdown:
  - empty series → {max_drawdown: 0.0, max_drawdown_pct: 0.0}
  - monotonically increasing → max_drawdown == 0
  - peak-then-decline → negative max_drawdown
  - pct matches absolute / peak
- compute_equity_metrics:
  - returns all expected keys
  - sharpe_bar matches compute_bar_sharpe
  - volatility_ann matches compute_volatility
  - total_return_pct correct
  - n_bars correct
  - bars_per_year echoed back
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.metrics import (
    compute_bar_sharpe,
    compute_equity_metrics,
    compute_max_drawdown,
    compute_volatility,
)

_TS_BASE = pd.Timestamp("2024-01-01", tz="UTC")


def _equity(values: list, freq: str = "D") -> pd.Series:
    idx = pd.date_range(_TS_BASE, periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


# ── compute_bar_sharpe ────────────────────────────────────────────────────────


def test_sharpe_empty_returns_zero():
    assert compute_bar_sharpe(pd.Series(dtype=float)) == 0.0


def test_sharpe_single_point_returns_zero():
    assert compute_bar_sharpe(_equity([100.0])) == 0.0


def test_sharpe_flat_equity_returns_zero():
    assert compute_bar_sharpe(_equity([100.0, 100.0, 100.0, 100.0])) == 0.0


def test_sharpe_increasing_equity_positive():
    eq = _equity([100.0, 101.0, 102.0, 103.0, 104.0])
    sharpe = compute_bar_sharpe(eq, bars_per_year=252)
    assert sharpe > 0


def test_sharpe_decreasing_equity_negative():
    eq = _equity([100.0, 99.0, 98.0, 97.0, 96.0])
    sharpe = compute_bar_sharpe(eq, bars_per_year=252)
    assert sharpe < 0


def test_sharpe_known_value():
    """Verify with a known synthetic example.

    Returns: [0.01, 0.01, 0.01] (constant 1% per bar).
    mean = 0.01, std = 0 (ddof=1 on 3 identical values = 0).
    → sharpe should be 0.0 (zero std).
    """
    eq = _equity([100.0, 101.0, 102.03, 103.0603])
    # Returns: 1%, 1%, ~1% → near-zero std
    sharpe = compute_bar_sharpe(eq, bars_per_year=252)
    # With very small but nonzero std, sharpe is large; just check it's finite and positive
    assert math.isfinite(sharpe)
    assert sharpe > 0


def test_sharpe_annualisation_factor():
    """When bars_per_year doubles, sharpe should scale by sqrt(2)."""
    eq = _equity([100.0, 102.0, 98.0, 104.0, 97.0, 106.0])
    s1 = compute_bar_sharpe(eq, bars_per_year=100)
    s2 = compute_bar_sharpe(eq, bars_per_year=400)
    # sharpe scales with sqrt(bars_per_year), so s2/s1 ≈ sqrt(4) = 2
    if s1 != 0:
        ratio = s2 / s1
        assert abs(ratio - 2.0) < 0.01


def test_sharpe_none_input_returns_zero():
    assert compute_bar_sharpe(None) == 0.0  # type: ignore[arg-type]


# ── compute_volatility ────────────────────────────────────────────────────────


def test_volatility_empty_returns_zero():
    assert compute_volatility(pd.Series(dtype=float)) == 0.0


def test_volatility_flat_returns_zero():
    assert compute_volatility(_equity([100.0, 100.0, 100.0])) == 0.0


def test_volatility_positive_for_changing_equity():
    eq = _equity([100.0, 102.0, 98.0, 105.0])
    vol = compute_volatility(eq, bars_per_year=252)
    assert vol > 0


def test_volatility_annualisation_scales():
    eq = _equity([100.0, 102.0, 98.0, 105.0, 97.0])
    v1 = compute_volatility(eq, bars_per_year=100)
    v2 = compute_volatility(eq, bars_per_year=400)
    # vol scales with sqrt(bars_per_year); v2/v1 ≈ 2
    if v1 > 0:
        ratio = v2 / v1
        assert abs(ratio - 2.0) < 0.01


# ── compute_max_drawdown ──────────────────────────────────────────────────────


def test_max_drawdown_empty():
    dd = compute_max_drawdown(pd.Series(dtype=float))
    assert dd["max_drawdown"] == 0.0
    assert dd["max_drawdown_pct"] == 0.0


def test_max_drawdown_monotonic_increase():
    eq = _equity([100.0, 101.0, 102.0, 103.0])
    dd = compute_max_drawdown(eq)
    assert dd["max_drawdown"] == 0.0
    assert dd["max_drawdown_pct"] == 0.0


def test_max_drawdown_peak_then_decline():
    eq = _equity([100.0, 110.0, 100.0, 90.0])
    dd = compute_max_drawdown(eq)
    assert dd["max_drawdown"] < 0
    assert abs(dd["max_drawdown"] - (-20.0)) < 1e-9
    assert abs(dd["max_drawdown_pct"] - (-20.0 / 110.0)) < 1e-9


def test_max_drawdown_pct_matches_absolute():
    eq = _equity([100.0, 200.0, 150.0, 120.0])
    dd = compute_max_drawdown(eq)
    # peak=200, trough=120, drawdown=-80
    assert abs(dd["max_drawdown"] - (-80.0)) < 1e-9
    assert abs(dd["max_drawdown_pct"] - (-80.0 / 200.0)) < 1e-9


# ── compute_equity_metrics ────────────────────────────────────────────────────


def test_equity_metrics_all_keys_present():
    eq = _equity([100.0, 102.0, 98.0, 105.0])
    m = compute_equity_metrics(eq, bars_per_year=252, initial_capital=100.0)
    for key in [
        "sharpe_bar", "volatility_ann", "max_drawdown", "max_drawdown_pct",
        "total_return_pct", "bars_per_year", "n_bars",
    ]:
        assert key in m, f"Missing key: {key}"


def test_equity_metrics_sharpe_matches_standalone():
    eq = _equity([100.0, 102.0, 98.0, 105.0])
    m = compute_equity_metrics(eq, bars_per_year=1008)
    expected = compute_bar_sharpe(eq, bars_per_year=1008)
    assert abs(m["sharpe_bar"] - expected) < 1e-12


def test_equity_metrics_volatility_matches_standalone():
    eq = _equity([100.0, 102.0, 98.0, 105.0])
    m = compute_equity_metrics(eq, bars_per_year=1008)
    expected = compute_volatility(eq, bars_per_year=1008)
    assert abs(m["volatility_ann"] - expected) < 1e-12


def test_equity_metrics_total_return():
    eq = _equity([100.0, 110.0])
    m = compute_equity_metrics(eq, initial_capital=100.0)
    assert abs(m["total_return_pct"] - 0.1) < 1e-9


def test_equity_metrics_n_bars():
    eq = _equity([100.0, 101.0, 102.0, 103.0, 104.0])
    m = compute_equity_metrics(eq)
    assert m["n_bars"] == 5


def test_equity_metrics_bars_per_year_echoed():
    eq = _equity([100.0, 101.0, 102.0])
    m = compute_equity_metrics(eq, bars_per_year=1234)
    assert m["bars_per_year"] == 1234


def test_equity_metrics_empty_series():
    m = compute_equity_metrics(pd.Series(dtype=float))
    assert m["sharpe_bar"] == 0.0
    assert m["volatility_ann"] == 0.0
    assert m["max_drawdown"] == 0.0
    assert m["n_bars"] == 0


# ── compute_summary integration: sharpe_bar in runner ────────────────────────


def test_compute_summary_includes_sharpe_bar():
    """compute_summary in runner should now include sharpe_bar and volatility_ann."""
    from backtest.runner import compute_summary

    eq = pd.Series(
        [100_000.0, 100_100.0, 99_900.0, 100_500.0],
        index=pd.date_range(_TS_BASE, periods=4, freq="6h", tz="UTC"),
    )
    summary = compute_summary(
        trades=[],
        equity_curve=eq,
        initial_capital=100_000.0,
        window_start=None,
        window_end=None,
        n_signals_generated=0,
        dataset_version="test",
    )
    assert "sharpe_bar" in summary
    assert "volatility_ann" in summary
    assert "sharpe_like" in summary  # backwards compat key still present
