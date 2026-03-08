"""
research/run_phase6_full.py

Phase 6 — Full walk-forward runner.

Runs the complete walk-forward evaluation on the full processed datasets
specified in ``configs/backtest.yaml`` and writes results to
``reports/phase6/full/``.

Usage
-----
    py -3.12 -m research.run_phase6_full
    python -m research.run_phase6_full
    python -m research.run_phase6_full --config configs/backtest.yaml
    python -m research.run_phase6_full --output-dir reports/phase6/full

What it does
------------
1. Loads ``BacktestConfig`` and ``WalkForwardConfig`` from ``configs/backtest.yaml``.
2. Loads the processed 1D and 6H datasets named in the config
   (``dataset.version_1d`` and ``dataset.version_6h``).
3. Loads the manifests for both datasets.
4. Runs ``run_walk_forward(...)`` from ``backtest.walkforward`` over the full
   date range with the production window sizes (730/180/90 days by default).
5. Writes:
   - ``reports/phase6/full/walkforward_summary.json`` — per-window metrics + aggregate
6. Prints to stdout:
   - n_windows
   - n_windows_with_trades
   - total_trades
   - total_net_pnl
   - avg_max_drawdown_pct (average across windows)

Determinism guarantee
---------------------
All operations are deterministic given fixed datasets and config.
No random state, no live data.

Performance note
----------------
Walk-forward results are the **only** valid performance evidence.
Single-window backtest results must NOT be used to claim edge.
See PROJECT_STATUS.md Phase 6 section and ASSUMPTIONS.md Assumption 37.

References
----------
backtest/runner.py — BacktestConfig, run_backtest
backtest/walkforward.py — WalkForwardConfig, run_walk_forward
data/loader.py — load_processed, load_manifest
configs/backtest.yaml — default config
ASSUMPTIONS.md — Assumptions 31–38
PROJECT_STATUS.md — Phase 6 section
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backtest.runner import BacktestConfig
from backtest.walkforward import WalkForwardConfig, run_walk_forward
from data.loader import load_manifest, load_processed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase6_full")

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG_PATH = "configs/backtest.yaml"
_DEFAULT_OUTPUT_DIR = "reports/phase6/full"


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


# ── Main ──────────────────────────────────────────────────────────────────────


def main(
    config_path: str,
    output_dir: Path,
) -> None:
    _ensure_dir(output_dir)

    # ── Load config ───────────────────────────────────────────────────────
    try:
        bt_config = BacktestConfig.from_yaml(config_path)
        wf_config = WalkForwardConfig.from_yaml(config_path)
        logger.info("Config loaded from: %s", config_path)
    except Exception as exc:
        logger.warning("Could not load config (%s); using defaults.", exc)
        bt_config = BacktestConfig()
        wf_config = WalkForwardConfig()

    logger.info(
        "Walk-forward config: train=%d days | test=%d days | step=%d days",
        wf_config.train_window_days,
        wf_config.test_window_days,
        wf_config.step_days,
    )

    # ── Load datasets ─────────────────────────────────────────────────────
    df_1d = _safe_load(bt_config.version_1d)
    df_6h = _safe_load(bt_config.version_6h)

    if df_1d is None or df_6h is None:
        logger.error("Cannot run full walk-forward: one or both datasets missing.")
        sys.exit(1)

    manifest_1d = _safe_manifest(bt_config.version_1d)
    manifest_6h = _safe_manifest(bt_config.version_6h)

    # ── Run full walk-forward ─────────────────────────────────────────────
    logger.info(
        "Starting full walk-forward on %d 1D bars and %d 6H bars …",
        len(df_1d),
        len(df_6h),
    )

    _window_results, aggregate = run_walk_forward(
        df_1d=df_1d,
        df_6h=df_6h,
        manifest_1d=manifest_1d,
        manifest_6h=manifest_6h,
        bt_config=bt_config,
        wf_config=wf_config,
        dataset_version=bt_config.version_1d,
        output_dir=output_dir,
    )

    # ── Print summary ─────────────────────────────────────────────────────
    _print_summary(aggregate, output_dir)


def _print_summary(agg: dict, output_dir: Path) -> None:
    print()
    print("Phase 6 — Full Walk-Forward Results")
    print("=" * 60)
    print(f"  n_windows                : {agg.get('n_windows', 0)}")
    print(f"  n_windows_with_trades    : {agg.get('n_windows_with_trades', 0)}")
    print(f"  total_trades             : {agg.get('total_trades', 0)}")
    print(f"  total_net_pnl            : {agg.get('total_net_pnl', 0.0):.2f}")
    print(f"  max_drawdown_pct (avg)   : {agg.get('avg_max_drawdown_pct', 0.0):.4f}")
    print()
    print(f"Output: {output_dir}/walkforward_summary.json")
    print()
    note = agg.get("note", "")
    if note:
        print(f"  *** {note} ***")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 6 full walk-forward runner on complete datasets."
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
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    main(
        config_path=args.config,
        output_dir=Path(args.output_dir),
    )
