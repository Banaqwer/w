"""
backtest/walkforward.py

Phase 6 — Walk-forward evaluation.

Splits a time series into sequential (train, test) windows and runs the
backtest runner on each window.  Collects per-window metrics and writes a
consolidated summary report.

Walk-forward window construction
----------------------------------
Given:
- ``train_window_days``: length of each training window in calendar days
- ``test_window_days``: length of each test window in calendar days
- ``step_days``: step between window start times

Windows are generated as::

    for each step i:
        train_start = data_start + i * step_days
        train_end   = train_start + train_window_days
        test_start  = train_end
        test_end    = test_start + test_window_days
        if test_end > data_end: stop

All boundaries are snapped to the nearest available bar timestamp (see
:func:`_snap_to_index`).

Windows with fewer than ``min_train_bars`` 1D bars or ``min_test_bars`` 1D bars
are skipped.

Output
------
- ``reports/phase6/walkforward_summary.json`` — per-window metrics + aggregate
  statistics.

Performance note
----------------
Walk-forward results are the **only** valid performance evidence.  Single-window
backtest results are indicative only and must NOT be used to claim edge.
See PROJECT_STATUS.md Phase 6 section and ASSUMPTIONS.md Assumption 37.

References
----------
backtest/runner.py — BacktestConfig, BacktestResult, run_backtest
ASSUMPTIONS.md — Assumptions 31–38
CLAUDE.md — Phase 6 goal
PROJECT_STATUS.md — Phase 6 section
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtest.runner import BacktestConfig, BacktestResult, run_backtest

logger = logging.getLogger(__name__)


# ── Walk-forward config ───────────────────────────────────────────────────────


@dataclass
class WalkForwardConfig:
    """Walk-forward window parameters.

    All time windows are in calendar days.  The actual number of bars in each
    window depends on the dataset's bar density.
    """

    train_window_days: int = 730     # ≈ 2 years of 1D bars
    test_window_days: int = 180      # ≈ 6 months
    step_days: int = 90              # ≈ 3 months
    min_train_bars: int = 300        # skip if fewer 1D bars
    min_test_bars: int = 30          # skip if fewer 1D bars in test

    @classmethod
    def from_yaml(cls, path: str = "configs/backtest.yaml") -> "WalkForwardConfig":
        """Load walk-forward config from YAML."""
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        wf = raw.get("walkforward", {})
        return cls(
            train_window_days=int(wf.get("train_window_days", cls.train_window_days)),
            test_window_days=int(wf.get("test_window_days", cls.test_window_days)),
            step_days=int(wf.get("step_days", cls.step_days)),
            min_train_bars=int(wf.get("min_train_bars", cls.min_train_bars)),
            min_test_bars=int(wf.get("min_test_bars", cls.min_test_bars)),
        )


# ── Window types ──────────────────────────────────────────────────────────────


@dataclass
class WalkForwardWindow:
    """One walk-forward split (train + test boundaries).

    All timestamps are inclusive bounds.
    """

    window_index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    n_train_bars: int = 0
    n_test_bars: int = 0

    def to_dict(self) -> dict:
        return {
            "window_index": self.window_index,
            "train_start": str(self.train_start),
            "train_end": str(self.train_end),
            "test_start": str(self.test_start),
            "test_end": str(self.test_end),
            "n_train_bars": self.n_train_bars,
            "n_test_bars": self.n_test_bars,
        }


@dataclass
class WalkForwardWindowResult:
    """Metrics for a single walk-forward window."""

    window: WalkForwardWindow
    summary: Dict[str, Any] = field(default_factory=dict)
    n_trades: int = 0

    def to_dict(self) -> dict:
        d = self.window.to_dict()
        d["summary"] = self.summary
        d["n_trades"] = self.n_trades
        return d


# ── Window construction ───────────────────────────────────────────────────────


def _snap_to_index(
    ts: pd.Timestamp,
    index: pd.DatetimeIndex,
    direction: str = "nearest",
) -> pd.Timestamp:
    """Snap a timestamp to the nearest available index value.

    Parameters
    ----------
    ts:
        Target timestamp.
    index:
        Sorted DatetimeIndex to snap to.
    direction:
        ``"nearest"`` (default), ``"forward"`` (first index >= ts), or
        ``"backward"`` (last index <= ts).

    Returns
    -------
    Nearest available timestamp in ``index``.  Returns ``ts`` unchanged if
    ``index`` is empty.
    """
    if index.empty:
        return ts
    if direction == "forward":
        mask = index >= ts
        if mask.any():
            return index[mask][0]
        return index[-1]
    if direction == "backward":
        mask = index <= ts
        if mask.any():
            return index[mask][-1]
        return index[0]
    # nearest
    pos = index.searchsorted(ts)
    pos = min(pos, len(index) - 1)
    if pos > 0 and abs(index[pos] - ts) > abs(index[pos - 1] - ts):
        pos -= 1
    return index[pos]


def build_walkforward_windows(
    df_1d_index: pd.DatetimeIndex,
    wf_config: WalkForwardConfig,
) -> List[WalkForwardWindow]:
    """Build walk-forward window list from a 1D bar index.

    Parameters
    ----------
    df_1d_index:
        Sorted DatetimeIndex of all 1D bars.
    wf_config:
        Walk-forward configuration.

    Returns
    -------
    List of :class:`WalkForwardWindow` objects in chronological order.
    """
    if df_1d_index.empty:
        return []

    data_start = df_1d_index[0]
    data_end = df_1d_index[-1]

    train_td = pd.Timedelta(days=wf_config.train_window_days)
    test_td = pd.Timedelta(days=wf_config.test_window_days)
    step_td = pd.Timedelta(days=wf_config.step_days)

    windows: List[WalkForwardWindow] = []
    window_index = 0
    cursor = data_start

    while True:
        train_start = cursor
        train_end_raw = cursor + train_td
        test_start_raw = train_end_raw
        test_end_raw = test_start_raw + test_td

        if test_end_raw > data_end:
            break

        # Snap to actual bar timestamps
        train_start_snap = _snap_to_index(train_start, df_1d_index, "forward")
        train_end_snap = _snap_to_index(train_end_raw, df_1d_index, "backward")
        test_start_snap = _snap_to_index(test_start_raw, df_1d_index, "forward")
        test_end_snap = _snap_to_index(test_end_raw, df_1d_index, "backward")

        # Count bars
        n_train = int(
            ((df_1d_index >= train_start_snap) & (df_1d_index <= train_end_snap)).sum()
        )
        n_test = int(
            ((df_1d_index >= test_start_snap) & (df_1d_index <= test_end_snap)).sum()
        )

        if n_train >= wf_config.min_train_bars and n_test >= wf_config.min_test_bars:
            windows.append(
                WalkForwardWindow(
                    window_index=window_index,
                    train_start=train_start_snap,
                    train_end=train_end_snap,
                    test_start=test_start_snap,
                    test_end=test_end_snap,
                    n_train_bars=n_train,
                    n_test_bars=n_test,
                )
            )
            window_index += 1
        else:
            logger.debug(
                "Skipping window %d: train=%d bars, test=%d bars (minimums: %d, %d)",
                window_index,
                n_train,
                n_test,
                wf_config.min_train_bars,
                wf_config.min_test_bars,
            )

        cursor = cursor + step_td

    return windows


# ── Aggregate metrics ─────────────────────────────────────────────────────────


def aggregate_walkforward_metrics(
    window_results: List[WalkForwardWindowResult],
) -> dict:
    """Compute aggregate statistics across all walk-forward windows.

    Parameters
    ----------
    window_results:
        List of per-window results.

    Returns
    -------
    Dict with aggregate metrics:
    - ``n_windows``: total windows evaluated
    - ``n_windows_with_trades``: windows that produced at least one trade
    - ``total_trades``: sum of all trades across windows
    - ``total_net_pnl``: sum of net PnL across windows
    - ``avg_win_rate``: mean win rate across windows (equal weight)
    - ``avg_expectancy``: mean expectancy across windows
    - ``avg_sharpe_like``: mean Sharpe-like across windows
    - ``avg_r_multiple``: mean R-multiple across windows
    - ``avg_max_drawdown_pct``: mean max drawdown pct across windows
    - ``min_win_rate``: worst win rate
    - ``max_win_rate``: best win rate
    - ``consistency_pct``: fraction of windows with positive total_net_pnl

    Notes
    -----
    These metrics are only valid after the full walk-forward completes.
    See ASSUMPTIONS.md Assumption 37 and PROJECT_STATUS.md Phase 6 section.
    """
    n = len(window_results)
    if n == 0:
        return {
            "n_windows": 0,
            "n_windows_with_trades": 0,
            "total_trades": 0,
            "total_net_pnl": 0.0,
            "avg_win_rate": 0.0,
            "avg_expectancy": 0.0,
            "avg_sharpe_like": 0.0,
            "avg_r_multiple": 0.0,
            "avg_max_drawdown_pct": 0.0,
            "min_win_rate": 0.0,
            "max_win_rate": 0.0,
            "consistency_pct": 0.0,
            "note": "No windows evaluated.",
        }

    summaries = [wr.summary for wr in window_results]

    total_trades = sum(s.get("total_trades", 0) for s in summaries)
    n_with_trades = sum(1 for s in summaries if s.get("total_trades", 0) > 0)
    total_net_pnl = sum(s.get("total_net_pnl", 0.0) for s in summaries)

    win_rates = [s.get("win_rate", 0.0) for s in summaries if s.get("total_trades", 0) > 0]
    expectancies = [s.get("expectancy", 0.0) for s in summaries if s.get("total_trades", 0) > 0]
    sharpes = [s.get("sharpe_like", 0.0) for s in summaries if s.get("total_trades", 0) > 0]
    r_mults = [s.get("avg_r_multiple", 0.0) for s in summaries if s.get("total_trades", 0) > 0]
    drawdowns = [s.get("max_drawdown_pct", 0.0) for s in summaries]

    positive_windows = sum(1 for s in summaries if s.get("total_net_pnl", 0.0) > 0)

    def _safe_mean(lst: list) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return {
        "n_windows": n,
        "n_windows_with_trades": n_with_trades,
        "total_trades": total_trades,
        "total_net_pnl": total_net_pnl,
        "avg_win_rate": _safe_mean(win_rates),
        "avg_expectancy": _safe_mean(expectancies),
        "avg_sharpe_like": _safe_mean(sharpes),
        "avg_r_multiple": _safe_mean(r_mults),
        "avg_max_drawdown_pct": _safe_mean(drawdowns),
        "min_win_rate": min(win_rates) if win_rates else 0.0,
        "max_win_rate": max(win_rates) if win_rates else 0.0,
        "consistency_pct": positive_windows / n,
        "note": (
            "IMPORTANT: Performance metrics are only valid after walk-forward completes. "
            "See PROJECT_STATUS.md Phase 6 section and ASSUMPTIONS.md Assumption 37."
        ),
    }


# ── Main walk-forward runner ──────────────────────────────────────────────────


def run_walk_forward(
    df_1d: pd.DataFrame,
    df_6h: pd.DataFrame,
    manifest_1d: dict,
    manifest_6h: dict,
    bt_config: BacktestConfig,
    wf_config: WalkForwardConfig,
    dataset_version: str = "",
    output_dir: Optional[Path] = None,
) -> Tuple[List[WalkForwardWindowResult], dict]:
    """Run the full walk-forward evaluation.

    Parameters
    ----------
    df_1d:
        Full 1D processed DataFrame.
    df_6h:
        Full 6H processed DataFrame.
    manifest_1d:
        Manifest for the 1D dataset.
    manifest_6h:
        Manifest for the 6H dataset.
    bt_config:
        Backtest configuration.
    wf_config:
        Walk-forward window configuration.
    dataset_version:
        Version string for provenance.
    output_dir:
        If provided, write ``walkforward_summary.json`` here.

    Returns
    -------
    Tuple of (list of WalkForwardWindowResult, aggregate metrics dict).
    """
    from backtest.runner import ensure_datetime_index
    df_1d_sorted = ensure_datetime_index(df_1d).sort_index()
    df_6h_sorted = ensure_datetime_index(df_6h).sort_index()

    windows = build_walkforward_windows(df_1d_sorted.index, wf_config)
    logger.info("Walk-forward: %d windows to evaluate.", len(windows))

    window_results: List[WalkForwardWindowResult] = []

    for win in windows:
        logger.info(
            "Window %d: train [%s → %s] | test [%s → %s]",
            win.window_index,
            win.train_start.date(),
            win.train_end.date(),
            win.test_start.date(),
            win.test_end.date(),
        )

        result: BacktestResult = run_backtest(
            df_1d=df_1d_sorted,
            df_6h=df_6h_sorted,
            manifest_1d=manifest_1d,
            manifest_6h=manifest_6h,
            config=bt_config,
            train_end=win.train_end,
            test_start=win.test_start,
            test_end=win.test_end,
            dataset_version=dataset_version,
        )

        window_results.append(
            WalkForwardWindowResult(
                window=win,
                summary=result.summary,
                n_trades=len(result.trades),
            )
        )

    aggregate = aggregate_walkforward_metrics(window_results)
    logger.info(
        "Walk-forward complete: %d windows, %d total trades, net PnL=%.2f",
        aggregate["n_windows"],
        aggregate["total_trades"],
        aggregate["total_net_pnl"],
    )

    if output_dir is not None:
        _write_walkforward_summary(window_results, aggregate, output_dir, dataset_version)

    return window_results, aggregate


def _write_walkforward_summary(
    window_results: List[WalkForwardWindowResult],
    aggregate: dict,
    output_dir: Path,
    dataset_version: str,
) -> None:
    """Write walkforward_summary.json to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "walkforward_summary.json"

    payload = {
        "dataset_version": dataset_version,
        "aggregate": aggregate,
        "windows": [wr.to_dict() for wr in window_results],
    }

    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)

    logger.info("Walk-forward summary written to: %s", summary_path)
