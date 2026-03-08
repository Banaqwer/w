"""
research/run_phase6_smoke.py

Phase 6 smoke run: Backtest engine + Walk-forward evaluation.

Runs a small, fast backtest on a recent slice of the processed datasets, then
optionally runs a short walk-forward to verify multi-window plumbing.

Scope: Phase 6 only (backtest + walk-forward).
No Phase 7+ logic is present.

Usage
-----
    python -m research.run_phase6_smoke
    python -m research.run_phase6_smoke --slice-days 180
    python -m research.run_phase6_smoke --output-dir reports/phase6/smoke
    python -m research.run_phase6_smoke --config configs/backtest.yaml
    python -m research.run_phase6_smoke --skip-walkforward

What it does
------------
1. Loads processed 1D and 6H datasets from data/processed/.
2. Slices both datasets to the most recent ``--slice-days`` calendar days.
3. Runs a single backtest window (train = first 2/3 of slice, test = last 1/3).
4. Writes:
   - ``reports/phase6/smoke/trades.csv``
   - ``reports/phase6/smoke/equity_curve.csv``
   - ``reports/phase6/smoke/summary.json``
5. Unless ``--skip-walkforward``, also runs a 2-window walk-forward on the
   slice and writes:
   - ``reports/phase6/smoke/walkforward_summary.json``
6. Prints a concise summary to stdout.

Determinism guarantee
---------------------
All operations are deterministic given fixed datasets and config.
No random state, no live data.

Performance warning
-------------------
Smoke results are NOT valid performance metrics.  The slice is recent
historical data which may be part of the model-building period.  Valid
performance metrics require a full walk-forward on the complete dataset.
See PROJECT_STATUS.md Phase 6 section.

References
----------
backtest/runner.py — BacktestConfig, run_backtest, write_trades, write_equity_curve, write_summary
backtest/walkforward.py — WalkForwardConfig, run_walk_forward
data/loader.py — load_processed, load_manifest
configs/backtest.yaml — default config
ASSUMPTIONS.md — Assumptions 31–38
PROJECT_STATUS.md — Phase 6 section
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backtest.runner import (
    BacktestConfig,
    run_backtest,
    write_equity_curve,
    write_summary,
    write_trades,
)
from backtest.walkforward import WalkForwardConfig, run_walk_forward
from data.loader import load_manifest, load_processed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase6_smoke")

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG_PATH = "configs/backtest.yaml"
_DEFAULT_OUTPUT_DIR = "reports/phase6/smoke"
_DEFAULT_SLICE_DAYS = 180


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _safe_load(version: str) -> Optional[pd.DataFrame]:
    try:
        df = load_processed(version)
        logger.info("Loaded %s: %d rows", version, len(df))
        return df
    except FileNotFoundError:
        logger.error("Dataset not found: %s", version)
        return None


def _safe_manifest(version: str) -> dict:
    try:
        return load_manifest(version)
    except FileNotFoundError:
        logger.warning("Manifest not found for %s — using empty manifest.", version)
        return {}


def _recent_slice(df: pd.DataFrame, slice_days: int) -> pd.DataFrame:
    """Return the most recent ``slice_days`` calendar days of ``df``.

    Handles both DatetimeIndex DataFrames and DataFrames with a ``timestamp``
    column (as produced by data/loader.py).
    """
    if df.empty:
        return df
    from backtest.runner import ensure_datetime_index
    df2 = ensure_datetime_index(df)
    df_sorted = df2.sort_index()
    cutoff = df_sorted.index[-1] - pd.Timedelta(days=slice_days)
    return df_sorted[df_sorted.index >= cutoff].copy()


# ── Main ──────────────────────────────────────────────────────────────────────


def main(
    config_path: str,
    output_dir: Path,
    slice_days: int,
    skip_walkforward: bool,
) -> None:
    _ensure_dir(output_dir)

    # ── Load config ───────────────────────────────────────────────────────
    try:
        bt_config = BacktestConfig.from_yaml(config_path)
        logger.info("Config loaded from: %s", config_path)
    except Exception as exc:
        logger.warning("Could not load config (%s); using defaults.", exc)
        bt_config = BacktestConfig()

    # ── Load datasets ─────────────────────────────────────────────────────
    df_1d_full = _safe_load(bt_config.version_1d)
    df_6h_full = _safe_load(bt_config.version_6h)

    if df_1d_full is None or df_6h_full is None:
        logger.error("Cannot run smoke: one or both datasets missing.")
        return

    manifest_1d = _safe_manifest(bt_config.version_1d)
    manifest_6h = _safe_manifest(bt_config.version_6h)

    # ── Slice to recent window ────────────────────────────────────────────
    df_1d = _recent_slice(df_1d_full, slice_days)
    df_6h = _recent_slice(df_6h_full, slice_days)

    logger.info(
        "Smoke slice: 1D=%d bars | 6H=%d bars (last %d days)",
        len(df_1d),
        len(df_6h),
        slice_days,
    )

    if df_1d.empty or df_6h.empty:
        logger.error("Smoke slice is empty — aborting.")
        return

    # ── Single backtest window ────────────────────────────────────────────
    # Train = first 2/3 of 1D slice; test = last 1/3 (by bar count)
    df_1d_sorted = df_1d.sort_index()
    n_1d = len(df_1d_sorted)
    split_idx = n_1d * 2 // 3
    if split_idx < 10:
        logger.warning("1D slice too short for meaningful split (%d bars); using all.", n_1d)
        split_idx = max(1, n_1d - 1)

    train_end = df_1d_sorted.index[split_idx - 1]
    test_start = df_1d_sorted.index[split_idx]
    test_end = df_1d_sorted.index[-1]

    logger.info(
        "Single backtest: train up to %s | test %s → %s",
        train_end.date(),
        test_start.date(),
        test_end.date(),
    )

    result = run_backtest(
        df_1d=df_1d_sorted,
        df_6h=df_6h,
        manifest_1d=manifest_1d,
        manifest_6h=manifest_6h,
        config=bt_config,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
        dataset_version=bt_config.version_1d,
    )

    # ── Write outputs ─────────────────────────────────────────────────────
    trades_path = output_dir / "trades"
    equity_path = output_dir / "equity_curve"
    summary_path = output_dir / "summary"

    write_trades(result.trades, trades_path, fmt="csv")
    write_equity_curve(result.equity_curve, equity_path)
    write_summary(result.summary, summary_path)

    _print_summary("Single Backtest (smoke)", result.summary, result.n_signals_generated)

    # ── Walk-forward (short) ──────────────────────────────────────────────
    if not skip_walkforward:
        wf_config = WalkForwardConfig(
            train_window_days=max(60, slice_days * 2 // 3),
            test_window_days=max(20, slice_days // 3),
            step_days=max(20, slice_days // 4),
            min_train_bars=30,
            min_test_bars=5,
        )

        logger.info(
            "Walk-forward: train=%d days | test=%d days | step=%d days",
            wf_config.train_window_days,
            wf_config.test_window_days,
            wf_config.step_days,
        )

        _, agg = run_walk_forward(
            df_1d=df_1d_sorted,
            df_6h=df_6h,
            manifest_1d=manifest_1d,
            manifest_6h=manifest_6h,
            bt_config=bt_config,
            wf_config=wf_config,
            dataset_version=bt_config.version_1d,
            output_dir=output_dir,
        )

        _print_wf_summary(agg)
    else:
        logger.info("Walk-forward skipped (--skip-walkforward).")

    print()
    print(
        "NOTE: Smoke metrics are NOT valid performance evidence. "
        "Run full walk-forward on complete dataset for valid results."
    )
    print()
    print("Output files:")
    print(f"  {output_dir}/trades.csv")
    print(f"  {output_dir}/equity_curve.csv")
    print(f"  {output_dir}/summary.json")
    if not skip_walkforward:
        print(f"  {output_dir}/walkforward_summary.json")
    print()


def _print_summary(label: str, summary: dict, n_signals: int) -> None:
    print()
    print(f"Phase 6 Smoke Run — {label}")
    print("=" * 60)
    print(f"  Signals generated       : {n_signals}")
    print(f"  Trades executed         : {summary.get('total_trades', 0)}")
    print(f"  Win rate                : {summary.get('win_rate', 0.0):.1%}")
    print(f"  Total net PnL           : {summary.get('total_net_pnl', 0.0):.2f}")
    print(f"  Total return            : {summary.get('total_return_pct', 0.0):.2%}")
    print(f"  Max drawdown            : {summary.get('max_drawdown_pct', 0.0):.2%}")
    print(f"  Sharpe-like (per-trade) : {summary.get('sharpe_like', 0.0):.3f}")
    print(f"  Avg R-multiple          : {summary.get('avg_r_multiple', 0.0):.3f}")
    print(f"  Expectancy (frac)       : {summary.get('expectancy', 0.0):.4f}")
    exit_counts = summary.get("exit_reason_counts", {})
    if exit_counts:
        print("  Exit reason breakdown:")
        for reason, count in sorted(exit_counts.items()):
            print(f"    {reason:<20}: {count}")


def _print_wf_summary(agg: dict) -> None:
    print()
    print("Phase 6 Walk-Forward Summary")
    print("=" * 60)
    print(f"  Windows evaluated       : {agg.get('n_windows', 0)}")
    print(f"  Windows with trades     : {agg.get('n_windows_with_trades', 0)}")
    print(f"  Total trades            : {agg.get('total_trades', 0)}")
    print(f"  Total net PnL           : {agg.get('total_net_pnl', 0.0):.2f}")
    print(f"  Avg win rate            : {agg.get('avg_win_rate', 0.0):.1%}")
    print(f"  Avg Sharpe-like         : {agg.get('avg_sharpe_like', 0.0):.3f}")
    print(f"  Avg R-multiple          : {agg.get('avg_r_multiple', 0.0):.3f}")
    print(f"  Consistency             : {agg.get('consistency_pct', 0.0):.1%}")
    print()
    print(f"  *** {agg.get('note', '')} ***")


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 6 smoke run: backtest engine + walk-forward."
    )
    p.add_argument(
        "--config",
        default=_DEFAULT_CONFIG_PATH,
        help=f"Path to backtest.yaml config (default: {_DEFAULT_CONFIG_PATH}).",
    )
    p.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {_DEFAULT_OUTPUT_DIR}).",
    )
    p.add_argument(
        "--slice-days",
        type=int,
        default=_DEFAULT_SLICE_DAYS,
        help=(
            f"Most recent calendar days to use as smoke slice "
            f"(default: {_DEFAULT_SLICE_DAYS})."
        ),
    )
    p.add_argument(
        "--skip-walkforward",
        action="store_true",
        default=False,
        help="Skip the walk-forward evaluation (run single backtest only).",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    main(
        config_path=args.config,
        output_dir=Path(args.output_dir),
        slice_days=args.slice_days,
        skip_walkforward=args.skip_walkforward,
    )
