"""
research/run_phase7_experiments.py

Phase 7 — Experiment tracking and parameter sweep scaffold.

Runs the Jenkins backtest (with confirmation gating) and the three baseline
strategies over a configurable set of parameter variants (grid sweep).  Each
run produces a structured record written to ``reports/phase7/``.

Run record format
-----------------
Each run record is a JSON file containing:
- ``run_id``: deterministic identifier (config hash prefix + timestamp)
- ``config_hash``: SHA-256 of the config dict (hex, first 12 chars)
- ``git_commit``: HEAD commit SHA (``"unknown"`` if git unavailable)
- ``dataset_version``: dataset version string
- ``params``: the full parameter dict for this run variant
- ``strategy_summary``: Jenkins strategy summary dict
- ``baseline_summaries``: dict of baseline_name → summary dict
- ``output_paths``: dict of output file paths written
- ``timestamp_utc``: ISO-8601 UTC timestamp of the run

Grid sweep
----------
The sweep is defined by ``PARAM_GRID`` at the top of this file.  Every
combination of parameters is run sequentially.  Total runs = product of
all list lengths.  Parameter names map to ``BacktestConfig`` or
``WalkForwardConfig`` fields.

Example grid (default):
    band_width_pct: [0.01, 0.02]
    confirmation_lookback: [5, 10]
    → 4 runs

Usage
-----
    python -m research.run_phase7_experiments
    python -m research.run_phase7_experiments --output-dir reports/phase7
    python -m research.run_phase7_experiments --config configs/backtest.yaml
    python -m research.run_phase7_experiments --skip-baselines
    python -m research.run_phase7_experiments --skip-walkforward

Output files
------------
Under ``output_dir/``:
- ``run_{run_id}/strategy_summary.json``
- ``run_{run_id}/run_record.json``
- ``run_{run_id}/baseline_{name}_summary.json``
- ``experiment_index.json`` — list of all run records (appended each run)

Determinism
-----------
All runs are deterministic.  Given fixed datasets, config, and grid, the
output is reproducible.

References
----------
backtest/runner.py — BacktestConfig, run_backtest
backtest/walkforward.py — WalkForwardConfig, run_walk_forward
backtest/baselines.py — RandomEntryBaseline, MACrossoverBaseline, BreakoutBaseline
backtest/metrics.py — compute_equity_metrics
data/loader.py — load_processed, load_manifest
ASSUMPTIONS.md — Phase 7 section
PROJECT_STATUS.md — Phase 7 section
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backtest.baselines import BreakoutBaseline, MACrossoverBaseline, RandomEntryBaseline
from backtest.runner import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
    write_equity_curve,
    write_summary,
    write_trades,
)
from backtest.walkforward import WalkForwardConfig, run_walk_forward

logger = logging.getLogger(__name__)

# ── Default parameter grid ────────────────────────────────────────────────────
# Each key maps to a list of values.  All combinations are swept.
# To run a single "default" configuration, set each list to a single value.

PARAM_GRID: Dict[str, List[Any]] = {
    # BacktestConfig fields
    "confirmation_lookback": [5, 10],
    "use_confirmation_gating": [True],
    # add more parameters here to extend the sweep, e.g.:
    # "fraction": [0.005, 0.01],
    # "max_hold_bars": [100, 200],
}


# ── Git helpers ───────────────────────────────────────────────────────────────


def _get_git_commit() -> str:
    """Return the current HEAD commit SHA, or 'unknown'."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ── Config hash ───────────────────────────────────────────────────────────────


def _config_hash(params: dict) -> str:
    """Return first 12 chars of SHA-256 of the JSON-serialised params dict."""
    blob = json.dumps(params, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


# ── Grid expansion ────────────────────────────────────────────────────────────


def expand_grid(grid: Dict[str, List[Any]]) -> Iterator[Dict[str, Any]]:
    """Yield all parameter combinations from ``grid``."""
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    for combo in product(*values):
        yield dict(zip(keys, combo))


# ── Per-run helpers ───────────────────────────────────────────────────────────


def _apply_params_to_config(base_config: BacktestConfig, params: dict) -> BacktestConfig:
    """Return a new BacktestConfig with fields overridden by ``params``."""
    import dataclasses
    overrides = {k: v for k, v in params.items() if hasattr(base_config, k)}
    return dataclasses.replace(base_config, **overrides)


def _run_baselines(
    df_6h: pd.DataFrame,
    config: BacktestConfig,
    dataset_version: str,
) -> Dict[str, dict]:
    """Run all three baselines and return summary dicts keyed by name."""
    summaries: Dict[str, dict] = {}

    for baseline in [
        RandomEntryBaseline(seed=42, entry_prob=0.05),
        MACrossoverBaseline(fast_period=10, slow_period=40),
        BreakoutBaseline(lookback=20),
    ]:
        try:
            result = baseline.run(df_6h, config, dataset_version)
            summaries[baseline.name] = result.summary
        except Exception as exc:
            logger.warning("Baseline %s failed: %s", baseline.name, exc)
            summaries[baseline.name] = {"error": str(exc)}

    return summaries


def run_single_experiment(
    df_1d: pd.DataFrame,
    df_6h: pd.DataFrame,
    manifest_1d: dict,
    manifest_6h: dict,
    dataset_version: str,
    params: dict,
    base_bt_config: BacktestConfig,
    wf_config: WalkForwardConfig,
    output_dir: Path,
    git_commit: str,
    run_baselines: bool = True,
    run_walkforward: bool = True,
) -> dict:
    """Run a single experiment variant and write outputs.

    Returns
    -------
    Run record dict (also written as ``run_record.json``).
    """
    from backtest.runner import ensure_datetime_index

    config = _apply_params_to_config(base_bt_config, params)
    chash = _config_hash(params)
    ts_utc = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"{chash}_{ts_utc}"

    run_dir = output_dir / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Experiment run_id=%s params=%s", run_id, params)

    # ── Strategy: walk-forward or single window ───────────────────────────
    strategy_summary: dict = {}
    output_paths: dict = {}

    df_1d_sorted = ensure_datetime_index(df_1d).sort_index()
    df_6h_sorted = ensure_datetime_index(df_6h).sort_index()

    if run_walkforward and not df_1d_sorted.empty:
        try:
            window_results, aggregate = run_walk_forward(
                df_1d=df_1d_sorted,
                df_6h=df_6h_sorted,
                manifest_1d=manifest_1d,
                manifest_6h=manifest_6h,
                bt_config=config,
                wf_config=wf_config,
                dataset_version=dataset_version,
                output_dir=run_dir,
            )
            strategy_summary = aggregate
            output_paths["walkforward_summary"] = str(run_dir / "walkforward_summary.json")
        except Exception as exc:
            logger.warning("Walk-forward failed: %s", exc)
            strategy_summary = {"error": str(exc)}
    else:
        # Single window: use last 1/3 of data as test
        if not df_1d_sorted.empty:
            n = len(df_1d_sorted)
            train_end = df_1d_sorted.index[int(n * 2 / 3)]
            test_start = df_1d_sorted.index[int(n * 2 / 3)]
            test_end = df_1d_sorted.index[-1]
            try:
                result = run_backtest(
                    df_1d=df_1d_sorted,
                    df_6h=df_6h_sorted,
                    manifest_1d=manifest_1d,
                    manifest_6h=manifest_6h,
                    config=config,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    dataset_version=dataset_version,
                )
                strategy_summary = result.summary
                summary_path = run_dir / "strategy_summary.json"
                write_summary(result.summary, summary_path)
                output_paths["strategy_summary"] = str(summary_path)
            except Exception as exc:
                logger.warning("Single-window backtest failed: %s", exc)
                strategy_summary = {"error": str(exc)}

    # ── Baselines ─────────────────────────────────────────────────────────
    baseline_summaries: dict = {}
    if run_baselines and not df_6h_sorted.empty:
        # Use entire 6H data for baselines (they have no training window)
        baseline_summaries = _run_baselines(df_6h_sorted, config, dataset_version)
        for bname, bsummary in baseline_summaries.items():
            bpath = run_dir / f"baseline_{bname}_summary.json"
            with open(bpath, "w", encoding="utf-8") as fh:
                json.dump(bsummary, fh, indent=2, default=str)
            output_paths[f"baseline_{bname}"] = str(bpath)

    # ── Run record ────────────────────────────────────────────────────────
    record = {
        "run_id": run_id,
        "config_hash": chash,
        "git_commit": git_commit,
        "dataset_version": dataset_version,
        "params": params,
        "strategy_summary": strategy_summary,
        "baseline_summaries": baseline_summaries,
        "output_paths": output_paths,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }

    record_path = run_dir / "run_record.json"
    with open(record_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, default=str)
    logger.info("Run record written to: %s", record_path)

    return record


def run_experiment_sweep(
    df_1d: pd.DataFrame,
    df_6h: pd.DataFrame,
    manifest_1d: dict,
    manifest_6h: dict,
    dataset_version: str,
    param_grid: Dict[str, List[Any]],
    base_bt_config: BacktestConfig,
    wf_config: WalkForwardConfig,
    output_dir: Path,
    run_baselines: bool = True,
    run_walkforward: bool = True,
) -> List[dict]:
    """Run all parameter combinations and return the list of run records.

    Writes an ``experiment_index.json`` summary to ``output_dir``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    git_commit = _get_git_commit()
    records: List[dict] = []

    combos = list(expand_grid(param_grid))
    logger.info("Experiment sweep: %d combinations to run.", len(combos))

    for i, params in enumerate(combos, start=1):
        logger.info("--- Run %d/%d: %s ---", i, len(combos), params)
        record = run_single_experiment(
            df_1d=df_1d,
            df_6h=df_6h,
            manifest_1d=manifest_1d,
            manifest_6h=manifest_6h,
            dataset_version=dataset_version,
            params=params,
            base_bt_config=base_bt_config,
            wf_config=wf_config,
            output_dir=output_dir,
            git_commit=git_commit,
            run_baselines=run_baselines,
            run_walkforward=run_walkforward,
        )
        records.append(record)

    # Write experiment index
    index_path = output_dir / "experiment_index.json"
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"n_runs": len(records), "git_commit": git_commit, "runs": records},
            fh,
            indent=2,
            default=str,
        )
    logger.info("Experiment index written to: %s", index_path)

    return records


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 7 experiment runner: parameter sweep + baselines."
    )
    p.add_argument("--config", default="configs/backtest.yaml", help="Backtest config YAML path.")
    p.add_argument(
        "--output-dir", default="reports/phase7", help="Output directory for all runs."
    )
    p.add_argument(
        "--skip-baselines", action="store_true", help="Skip baseline strategy runs."
    )
    p.add_argument(
        "--skip-walkforward",
        action="store_true",
        help="Skip walk-forward; run a single window instead.",
    )
    p.add_argument(
        "--slice-days",
        type=int,
        default=0,
        help="If >0, use only the most recent N calendar days of data.",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    """Entry point for ``python -m research.run_phase7_experiments``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = _parse_args(argv)
    output_dir = Path(args.output_dir)

    # ── Load data ─────────────────────────────────────────────────────────
    try:
        from data.loader import load_manifest, load_processed

        bt_config = BacktestConfig.from_yaml(args.config)
        wf_config = WalkForwardConfig.from_yaml(args.config)

        df_1d = load_processed(bt_config.version_1d)
        df_6h = load_processed(bt_config.version_6h)
        manifest_1d = load_manifest(bt_config.version_1d)
        manifest_6h = load_manifest(bt_config.version_6h)
        dataset_version = bt_config.version_1d

    except Exception as exc:
        logger.error("Failed to load data: %s", exc)
        logger.error("Ensure processed datasets exist (run data ingestion first).")
        sys.exit(1)

    # ── Optional slice ────────────────────────────────────────────────────
    if args.slice_days > 0:
        from backtest.runner import ensure_datetime_index

        df_1d = ensure_datetime_index(df_1d).sort_index()
        df_6h = ensure_datetime_index(df_6h).sort_index()
        if not df_1d.empty:
            cutoff = df_1d.index[-1] - pd.Timedelta(days=args.slice_days)
            df_1d = df_1d[df_1d.index >= cutoff]
            df_6h = df_6h[df_6h.index >= cutoff]
            logger.info(
                "Sliced to last %d days: 1D=%d bars, 6H=%d bars",
                args.slice_days, len(df_1d), len(df_6h),
            )

    # ── Run sweep ─────────────────────────────────────────────────────────
    records = run_experiment_sweep(
        df_1d=df_1d,
        df_6h=df_6h,
        manifest_1d=manifest_1d,
        manifest_6h=manifest_6h,
        dataset_version=dataset_version,
        param_grid=PARAM_GRID,
        base_bt_config=bt_config,
        wf_config=wf_config,
        output_dir=output_dir,
        run_baselines=not args.skip_baselines,
        run_walkforward=not args.skip_walkforward,
    )

    # ── Print summary ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Phase 7 experiment sweep complete: {len(records)} run(s)")
    print(f"Output directory: {output_dir.resolve()}")
    print(f"{'='*60}")
    for rec in records:
        strat = rec.get("strategy_summary", {})
        n_trades = strat.get("total_trades", strat.get("n_windows_with_trades", "?"))
        net_pnl = strat.get("total_net_pnl", "?")
        sharpe = strat.get("sharpe_bar", strat.get("avg_sharpe_like", "?"))
        print(
            f"  run_id={rec['run_id']}  params={rec['params']}  "
            f"trades={n_trades}  net_pnl={net_pnl}  sharpe_bar={sharpe}"
        )
    print(f"\nIndex: {output_dir / 'experiment_index.json'}")


if __name__ == "__main__":
    main()
