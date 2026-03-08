"""
backtest/metrics.py

Phase 7 — Bar-frequency equity-curve metrics.

Provides pure functions for computing performance metrics directly from the
equity curve time series at a defined bar frequency.  This replaces the
per-trade Sharpe approximation (ASSUMPTIONS.md Assumption 35, retired in Phase 7).

Bar-frequency Sharpe
--------------------
Given an equity curve *E* sampled at timestamps *t_0, t_1, ..., t_N*:

    daily_return_i = (E_i - E_{i-1}) / E_{i-1}

The annualised Sharpe ratio is:

    sharpe_bar = mean(daily_return) / std(daily_return, ddof=1) * sqrt(bars_per_year)

For a 1D equity curve: ``bars_per_year = 252`` (trading days).
For a 6H equity curve: ``bars_per_year = 252 * 4 = 1008``.

The annualisation factor is documented in every output so results can always
be traced back to the raw bar frequency.

Design rules
------------
- Pure functions: same inputs → same outputs.
- Returns ``0.0`` (not NaN) for degenerate inputs (empty, single point, zero std).
- Volatility is expressed as annualised standard deviation of returns (%).
- Max drawdown already in :func:`backtest.runner.compute_summary`; included here
  as a standalone utility for use by baselines.

References
----------
ASSUMPTIONS.md — Assumption 35 (retired Phase 7), Assumption 39 (Phase 7 bar Sharpe)
PROJECT_STATUS.md — Phase 7 section
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

# Default annualisation factors
_BARS_PER_YEAR_1D = 252
_BARS_PER_YEAR_6H = 252 * 4  # 1008


# ── Public API ────────────────────────────────────────────────────────────────


def compute_bar_sharpe(
    equity_curve: pd.Series,
    bars_per_year: int = _BARS_PER_YEAR_1D,
) -> float:
    """Compute annualised bar-frequency Sharpe ratio from an equity curve.

    Uses percentage returns between consecutive equity points.

    Parameters
    ----------
    equity_curve:
        Time-indexed Series of equity values.  Must contain at least 2 points.
        Values must be positive (equity > 0).
    bars_per_year:
        Annualisation factor.  Use 252 for daily bars, 1008 for 6H bars.
        Defaults to 252 (daily).

    Returns
    -------
    Annualised Sharpe ratio (float).  Returns ``0.0`` if fewer than 2 points,
    all returns are zero, or standard deviation is zero.
    """
    if equity_curve is None or len(equity_curve) < 2:
        return 0.0

    returns = equity_curve.pct_change().dropna()
    if returns.empty:
        return 0.0

    mean_r = float(returns.mean())
    std_r = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0

    if std_r == 0.0:
        return 0.0

    return (mean_r / std_r) * math.sqrt(bars_per_year)


def compute_volatility(
    equity_curve: pd.Series,
    bars_per_year: int = _BARS_PER_YEAR_1D,
) -> float:
    """Compute annualised return volatility from an equity curve.

    Parameters
    ----------
    equity_curve:
        Time-indexed Series of equity values.
    bars_per_year:
        Annualisation factor (see :func:`compute_bar_sharpe`).

    Returns
    -------
    Annualised volatility as a decimal fraction (e.g., 0.20 = 20% per year).
    Returns ``0.0`` for degenerate inputs.
    """
    if equity_curve is None or len(equity_curve) < 2:
        return 0.0

    returns = equity_curve.pct_change().dropna()
    if returns.empty:
        return 0.0

    std_r = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    return std_r * math.sqrt(bars_per_year)


def compute_max_drawdown(equity_curve: pd.Series) -> dict:
    """Compute maximum peak-to-trough drawdown from an equity curve.

    Parameters
    ----------
    equity_curve:
        Time-indexed Series of equity values.

    Returns
    -------
    Dict with keys:
    - ``max_drawdown``: absolute peak-to-trough decline (negative float)
    - ``max_drawdown_pct``: drawdown as fraction of peak (negative float)
    """
    if equity_curve is None or equity_curve.empty:
        return {"max_drawdown": 0.0, "max_drawdown_pct": 0.0}

    peak = equity_curve.expanding().max()
    drawdown = equity_curve - peak
    max_dd = float(drawdown.min())
    idx_min = drawdown.idxmin()
    peak_at_trough = float(peak[idx_min]) if idx_min is not None else float(peak.iloc[-1])
    max_dd_pct = max_dd / peak_at_trough if peak_at_trough > 0 else 0.0

    return {"max_drawdown": max_dd, "max_drawdown_pct": max_dd_pct}


def compute_equity_metrics(
    equity_curve: pd.Series,
    bars_per_year: int = _BARS_PER_YEAR_1D,
    initial_capital: Optional[float] = None,
) -> dict:
    """Compute all bar-frequency equity metrics in one call.

    Parameters
    ----------
    equity_curve:
        Time-indexed Series of equity values.
    bars_per_year:
        Annualisation factor (see :func:`compute_bar_sharpe`).
    initial_capital:
        Starting equity for total-return calculation.  If ``None``, uses the
        first equity curve value.

    Returns
    -------
    Dict with keys:
    - ``sharpe_bar``: annualised bar-frequency Sharpe ratio
    - ``volatility_ann``: annualised return volatility (decimal)
    - ``max_drawdown``: absolute peak-to-trough decline
    - ``max_drawdown_pct``: drawdown as fraction of peak
    - ``total_return_pct``: (final - initial) / initial
    - ``bars_per_year``: annualisation factor used (for audit)
    - ``n_bars``: number of equity curve points
    """
    sharpe = compute_bar_sharpe(equity_curve, bars_per_year)
    vol = compute_volatility(equity_curve, bars_per_year)
    dd = compute_max_drawdown(equity_curve)

    n_bars = len(equity_curve) if equity_curve is not None else 0
    total_return = 0.0
    if equity_curve is not None and not equity_curve.empty:
        start = initial_capital if initial_capital is not None else float(equity_curve.iloc[0])
        end = float(equity_curve.iloc[-1])
        total_return = (end - start) / start if start > 0 else 0.0

    return {
        "sharpe_bar": sharpe,
        "volatility_ann": vol,
        "max_drawdown": dd["max_drawdown"],
        "max_drawdown_pct": dd["max_drawdown_pct"],
        "total_return_pct": total_return,
        "bars_per_year": bars_per_year,
        "n_bars": n_bars,
    }
