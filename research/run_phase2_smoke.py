"""
research/run_phase2_smoke.py

Phase 2 smoke-run script.

Loads the latest processed 1D and 6H datasets, runs origin selection and
impulse detection, and writes JSON output files to ``reports/phase2/``.

Usage
-----
From the repository root::

    python -m research.run_phase2_smoke

Options::

    --config   Path to YAML config (default: configs/default.yaml)
    --skip-6h  Skip the 6H dataset run entirely
    --base-path Path to data/processed (default: data/processed)

Outputs
-------
- ``reports/phase2/origins_<dataset_version>.json``
- ``reports/phase2/impulses_<dataset_version>.json``

Notes
-----
- 1D run is required.
- 6H run is optional but, when executed, checks ``missing_bar_count`` from the
  manifest and passes ``skip_on_gap=True`` to the impulse detector when > 0.
- No trading logic, no performance claims.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import yaml

# ── Ensure repo root is on sys.path ───────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data.loader import load_manifest, load_processed
from modules.impulse import Impulse, detect_impulses
from modules.origin_selection import Origin, select_origins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_phase2_smoke")

# ── Constants ──────────────────────────────────────────────────────────────

_DEFAULT_CONFIG = "configs/default.yaml"
_REPORTS_DIR = Path("reports/phase2")

# Pivot and zigzag parameters used in this smoke run
_PIVOT_N = 5
_ZIGZAG_PCT = 3.0
_MAX_LOOKAHEAD = 200
_REVERSAL_PCT = 20.0  # 20% pullback from running extreme ends the search


# ── Helpers ────────────────────────────────────────────────────────────────


def _load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _origins_to_records(origins: List[Origin]) -> List[Dict[str, Any]]:
    records = []
    for o in origins:
        d = {
            "origin_time": o.origin_time.isoformat(),
            "origin_price": o.origin_price,
            "bar_index": o.bar_index,
            "origin_type": o.origin_type,
            "detector_name": o.detector_name,
            "quality_score": round(o.quality_score, 6),
        }
        records.append(d)
    return records


def _impulses_to_records(impulses: List[Impulse]) -> List[Dict[str, Any]]:
    records = []
    for imp in impulses:
        d = {
            "impulse_id": imp.impulse_id,
            "origin_time": imp.origin_time.isoformat(),
            "origin_price": imp.origin_price,
            "extreme_time": imp.extreme_time.isoformat(),
            "extreme_price": imp.extreme_price,
            "origin_bar_index": imp.origin_bar_index,
            "extreme_bar_index": imp.extreme_bar_index,
            "delta_t": imp.delta_t,
            "delta_p": round(imp.delta_p, 6),
            "slope_raw": round(imp.slope_raw, 8),
            "slope_log": round(imp.slope_log, 10) if not pd.isna(imp.slope_log) else None,
            "direction": imp.direction,
            "quality_score": round(imp.quality_score, 6),
            "detector_name": imp.detector_name,
            "gap_in_window": imp.gap_in_window,
        }
        records.append(d)
    return records


def _run_dataset(
    dataset_version: str,
    base_path: str,
    skip_on_gap: bool,
    timeframe_label: str,
) -> Dict[str, Any]:
    """Run origin selection + impulse detection on one dataset version.

    Returns a summary dict with counts and file paths.
    """
    logger.info("=== Loading dataset: %s ===", dataset_version)
    df = load_processed(dataset_version, base_path=base_path)
    manifest = load_manifest(dataset_version, base_path=base_path)

    row_count = len(df)
    missing_bar_count = manifest.get("missing_bar_count", 0)
    atr_warmup = manifest.get("atr_warmup_rows", 14)

    logger.info(
        "  rows=%d  missing_bar_count=%d  skip_on_gap=%s",
        row_count,
        missing_bar_count,
        skip_on_gap,
    )

    # ── Sanity checks ────────────────────────────────────────────────────
    assert "bar_index" in df.columns, "bar_index column missing from processed dataset"
    assert "atr_14" in df.columns, "atr_14 column missing; coordinate system not applied"
    assert row_count > atr_warmup, "Dataset too short to produce any valid origins"

    # ── Origin selection (both methods) ─────────────────────────────────
    pivot_origins = select_origins(
        df,
        method="pivot",
        pivot_n=_PIVOT_N,
        atr_warmup_rows=atr_warmup,
    )
    zigzag_origins = select_origins(
        df,
        method="zigzag",
        threshold_pct=_ZIGZAG_PCT,
        atr_warmup_rows=atr_warmup,
    )

    # ── Impulse detection for each origin set ───────────────────────────
    pivot_impulses = detect_impulses(
        df,
        pivot_origins,
        max_lookahead_bars=_MAX_LOOKAHEAD,
        reversal_pct=_REVERSAL_PCT,
        skip_on_gap=skip_on_gap,
        atr_warmup_rows=atr_warmup,
    )
    zigzag_impulses = detect_impulses(
        df,
        zigzag_origins,
        max_lookahead_bars=_MAX_LOOKAHEAD,
        reversal_pct=_REVERSAL_PCT,
        skip_on_gap=skip_on_gap,
        atr_warmup_rows=atr_warmup,
    )

    all_origins = pivot_origins + zigzag_origins
    all_impulses = pivot_impulses + zigzag_impulses

    # ── Write outputs ────────────────────────────────────────────────────
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    origins_path = _REPORTS_DIR / f"origins_{dataset_version}.json"
    impulses_path = _REPORTS_DIR / f"impulses_{dataset_version}.json"

    origins_payload = {
        "dataset_version": dataset_version,
        "timeframe": timeframe_label,
        "missing_bar_count": missing_bar_count,
        "skip_on_gap": skip_on_gap,
        "pivot_n": _PIVOT_N,
        "zigzag_pct": _ZIGZAG_PCT,
        "pivot_origin_count": len(pivot_origins),
        "zigzag_origin_count": len(zigzag_origins),
        "origins": _origins_to_records(all_origins),
    }
    impulses_payload = {
        "dataset_version": dataset_version,
        "timeframe": timeframe_label,
        "missing_bar_count": missing_bar_count,
        "skip_on_gap": skip_on_gap,
        "max_lookahead_bars": _MAX_LOOKAHEAD,
        "reversal_pct": _REVERSAL_PCT,
        "pivot_impulse_count": len(pivot_impulses),
        "zigzag_impulse_count": len(zigzag_impulses),
        "impulses": _impulses_to_records(all_impulses),
    }

    with open(origins_path, "w", encoding="utf-8") as fh:
        json.dump(origins_payload, fh, indent=2)
    with open(impulses_path, "w", encoding="utf-8") as fh:
        json.dump(impulses_payload, fh, indent=2)

    logger.info("  pivot_origins=%d  zigzag_origins=%d", len(pivot_origins), len(zigzag_origins))
    logger.info("  pivot_impulses=%d  zigzag_impulses=%d", len(pivot_impulses), len(zigzag_impulses))
    logger.info("  Written: %s", origins_path)
    logger.info("  Written: %s", impulses_path)

    # ── Basic sanity assertions (no trading logic) ───────────────────────
    assert len(pivot_origins) > 0, "No pivot origins detected; check data or pivot_n parameter"
    assert len(zigzag_origins) > 0, "No zigzag origins detected; check data or threshold_pct"
    assert len(pivot_impulses) > 0, "No pivot impulses detected; check max_lookahead_bars or reversal_pct parameters"

    for imp in all_impulses:
        assert imp.delta_t >= 2, f"Impulse delta_t < 2: {imp.impulse_id}"
        assert imp.quality_score >= 0.0 and imp.quality_score <= 1.0, (
            f"quality_score out of range: {imp.impulse_id}"
        )
        assert imp.direction in ("up", "down"), f"Bad direction: {imp.impulse_id}"

    return {
        "dataset_version": dataset_version,
        "timeframe": timeframe_label,
        "row_count": row_count,
        "missing_bar_count": missing_bar_count,
        "pivot_origins": len(pivot_origins),
        "zigzag_origins": len(zigzag_origins),
        "pivot_impulses": len(pivot_impulses),
        "zigzag_impulses": len(zigzag_impulses),
        "origins_file": str(origins_path),
        "impulses_file": str(impulses_path),
    }


# ── Main ───────────────────────────────────────────────────────────────────


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2 smoke run: origin selection + impulse detection"
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        help="Path to YAML config file (default: configs/default.yaml)",
    )
    parser.add_argument(
        "--skip-6h",
        action="store_true",
        help="Skip the 6H dataset run",
    )
    parser.add_argument(
        "--base-path",
        default="data/processed",
        help="Root directory for processed datasets (default: data/processed)",
    )
    args = parser.parse_args(argv)

    config = _load_config(args.config)
    base_path = args.base_path

    version_1d = config["dataset"]["current_version"]
    version_6h = config["dataset"].get("version_6h")

    results = []

    # ── 1D run (required) ────────────────────────────────────────────────
    result_1d = _run_dataset(
        dataset_version=version_1d,
        base_path=base_path,
        skip_on_gap=False,  # 1D has 0 missing bars
        timeframe_label="1D",
    )
    results.append(result_1d)

    # ── 6H run (optional) ────────────────────────────────────────────────
    if not args.skip_6h and version_6h:
        manifest_6h = load_manifest(version_6h, base_path=base_path)
        missing_6h = manifest_6h.get("missing_bar_count", 0)
        skip_on_gap_6h = missing_6h > 0
        if missing_6h > 0:
            logger.info(
                "6H manifest reports %d missing bar(s); setting skip_on_gap=True",
                missing_6h,
            )
        result_6h = _run_dataset(
            dataset_version=version_6h,
            base_path=base_path,
            skip_on_gap=skip_on_gap_6h,
            timeframe_label="6H",
        )
        results.append(result_6h)
    elif args.skip_6h:
        logger.info("6H run skipped via --skip-6h flag")
    else:
        logger.warning("No version_6h found in config; skipping 6H run")

    # ── Summary ─────────────────────────────────────────────────────────
    logger.info("=== Phase 2 smoke run complete ===")
    for r in results:
        logger.info(
            "  [%s] %s | rows=%d | missing=%d | "
            "pivot_origins=%d zigzag_origins=%d | "
            "pivot_impulses=%d zigzag_impulses=%d",
            r["timeframe"],
            r["dataset_version"],
            r["row_count"],
            r["missing_bar_count"],
            r["pivot_origins"],
            r["zigzag_origins"],
            r["pivot_impulses"],
            r["zigzag_impulses"],
        )


if __name__ == "__main__":
    main()
