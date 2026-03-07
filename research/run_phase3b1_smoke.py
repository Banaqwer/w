"""
research/run_phase3b1_smoke.py

Phase 3B.1 smoke run: compute JTTL lines and square-root levels for
Phase 2 origins, and write results to reports/phase3b1/.

Usage
-----
    python -m research.run_phase3b1_smoke
    python -m research.run_phase3b1_smoke --origins-dir reports/phase2
    python -m research.run_phase3b1_smoke --output-dir reports/phase3b1
    python -m research.run_phase3b1_smoke --k 2.0 --horizon-days 365

What it does
------------
1. Loads Phase 2 origin CSVs from ``reports/phase2/``.
2. Applies hardcoded reference origins (origin_price=47.70 and
   origin_price=100.0) in addition to the dataset-loaded ones.
3. For each origin:
   - Computes a JTTL line via ``modules.jttl.compute_jttl``.
   - Computes sqrt levels via ``modules.sqrt_levels.sqrt_levels``.
4. Writes one JSON per origin set to ``reports/phase3b1/``.
5. Writes a human-readable and machine-readable summary.

Scope
-----
Phase 3B.1 only.  No Phase 4+ (projection, confluence, signals, backtest)
logic is present in this script.

References
----------
modules/jttl.py
modules/sqrt_levels.py
PROJECT_STATUS.md — Phase 3B.1 section
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.jttl import compute_jttl
from modules.sqrt_levels import sqrt_levels

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase3b1_smoke")


# ── Hardcoded reference origins ────────────────────────────────────────────────
# Used in addition to the loaded Phase 2 origins for known-value sanity checks.

_REFERENCE_ORIGINS = [
    {
        "origin_time": "2020-01-01 00:00:00+00:00",
        "origin_price": 47.70,
        "label": "ref_47_70",
    },
    {
        "origin_time": "2020-01-01 00:00:00+00:00",
        "origin_price": 100.0,
        "label": "ref_100",
    },
    {
        "origin_time": "2020-01-01 00:00:00+00:00",
        "origin_price": 10000.0,
        "label": "ref_10000",
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _find_origin_csvs(origins_dir: Path) -> list:
    csvs = sorted(origins_dir.glob("origins_*.csv"))
    if not csvs:
        logger.warning(
            "No Phase 2 origin CSVs found in %s. "
            "Run research/run_phase2_smoke.py first.",
            origins_dir,
        )
    return csvs


def _parse_version_and_method(csv_path: Path) -> tuple:
    """Extract (version, method) from a Phase 2 origins CSV filename."""
    stem = csv_path.stem  # e.g. "origins_proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1_pivot"
    assert stem.startswith("origins_"), f"Unexpected CSV name: {csv_path.name}"
    rest = stem[len("origins_"):]
    parts = rest.rsplit("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Cannot parse version/method from: {csv_path.name}")
    return parts[0], parts[1]


def _process_origin(
    origin_time_str: str,
    origin_price: float,
    label: str,
    k: float,
    horizon_days: int,
    increments: List[float],
    steps: int,
) -> dict:
    """Compute JTTL + sqrt levels for one origin; return a result dict."""
    t0 = pd.Timestamp(origin_time_str)
    if t0.tzinfo is None:
        t0 = t0.tz_localize("UTC")

    jttl = compute_jttl(t0, origin_price, k=k, horizon_days=horizon_days)
    levels = sqrt_levels(origin_price, increments=increments, steps=steps)

    return {
        "label": label,
        "origin_time": str(t0),
        "origin_price": origin_price,
        "jttl": jttl.to_dict(),
        "sqrt_levels": [lv.to_dict() for lv in levels],
    }


# ── Core runner ───────────────────────────────────────────────────────────────


def run(
    origins_dir: Path,
    output_dir: Path,
    k: float = 2.0,
    horizon_days: int = 365,
    increments: List[float] | None = None,
    steps: int = 8,
    max_origins_per_file: int = 10,
) -> dict:
    """Run Phase 3B.1 smoke on all Phase 2 origin files + reference origins.

    Parameters
    ----------
    origins_dir:
        Directory containing Phase 2 origin CSVs.
    output_dir:
        Directory to write Phase 3B.1 output JSONs.
    k:
        JTTL sqrt-space increment. Default 2.0.
    horizon_days:
        JTTL horizon in calendar days. Default 365.
    increments:
        Sqrt-level increment list. Defaults to [0.25, 0.5, 0.75, 1.0].
    steps:
        Steps per increment for sqrt levels. Default 8.
    max_origins_per_file:
        Maximum origins to process per Phase 2 CSV (to keep output small).

    Returns
    -------
    Summary dict.
    """
    if increments is None:
        increments = [0.25, 0.5, 0.75, 1.0]

    _ensure_dir(output_dir)
    all_results = []

    # ── Reference origins (hardcoded) ──────────────────────────────────────
    logger.info("Processing %d reference origins.", len(_REFERENCE_ORIGINS))
    ref_results = []
    for ref in _REFERENCE_ORIGINS:
        r = _process_origin(
            ref["origin_time"],
            ref["origin_price"],
            ref["label"],
            k=k,
            horizon_days=horizon_days,
            increments=increments,
            steps=steps,
        )
        ref_results.append(r)
        logger.info(
            "  %s: p0=%.2f → p1=%.4f (JTTL), %d sqrt levels",
            ref["label"],
            ref["origin_price"],
            r["jttl"]["p1"],
            len(r["sqrt_levels"]),
        )

    ref_out = output_dir / "reference_origins_jttl_sqrt.json"
    with open(ref_out, "w", encoding="utf-8") as fh:
        json.dump(ref_results, fh, indent=2, default=str)
    logger.info("Reference origins → %s", ref_out)
    all_results.append(
        {
            "source": "reference",
            "count": len(ref_results),
            "output": str(ref_out),
        }
    )

    # ── Phase 2 dataset origins ────────────────────────────────────────────
    csvs = _find_origin_csvs(origins_dir)
    for csv_path in csvs:
        version, method = _parse_version_and_method(csv_path)
        logger.info("=== %s | %s ===", version, method)

        df = pd.read_csv(csv_path)
        sample = df.head(max_origins_per_file)
        logger.info(
            "  Loaded %d origins; processing first %d.",
            len(df),
            len(sample),
        )

        dataset_results = []
        for _, row in sample.iterrows():
            label = f"{method}_{int(row.get('bar_index', 0))}"
            r = _process_origin(
                str(row["origin_time"]),
                float(row["origin_price"]),
                label=label,
                k=k,
                horizon_days=horizon_days,
                increments=increments,
                steps=steps,
            )
            dataset_results.append(r)

        out_path = output_dir / f"origins_jttl_sqrt_{version}_{method}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(dataset_results, fh, indent=2, default=str)
        logger.info("  Wrote → %s", out_path)

        # quick inline sample for the summary
        if dataset_results:
            first = dataset_results[0]
            logger.info(
                "  First origin: p0=%.2f k=%.1f p1=%.4f horizon_days=%d basis=%s",
                first["origin_price"],
                first["jttl"]["k"],
                first["jttl"]["p1"],
                first["jttl"]["horizon_days"],
                first["jttl"]["basis"],
            )

        all_results.append(
            {
                "source": f"{version}_{method}",
                "count": len(dataset_results),
                "output": str(out_path),
            }
        )

    # ── Summary ───────────────────────────────────────────────────────────
    summary = {
        "phase": "3B.1",
        "scope": "jttl + sqrt_levels",
        "k": k,
        "horizon_days": horizon_days,
        "increments": increments,
        "steps": steps,
        "max_origins_per_file": max_origins_per_file,
        "runs": all_results,
    }

    # Text summary
    lines = ["Phase 3B.1 Smoke Run Summary", "=" * 70, ""]
    lines.append(f"JTTL k:          {k}")
    lines.append(f"JTTL horizon:    {horizon_days} calendar days")
    lines.append(f"Sqrt increments: {increments}")
    lines.append(f"Sqrt steps:      {steps}")
    lines.append("")

    # Print reference origin table
    lines.append("Reference origins:")
    lines.append(f"  {'label':15s}  {'p0':>10s}  {'p1 (JTTL)':>12s}  {'# levels':>8s}")
    lines.append("  " + "-" * 55)
    for r in ref_results:
        lines.append(
            f"  {r['label']:15s}  {r['origin_price']:>10.2f}  "
            f"{r['jttl']['p1']:>12.4f}  {len(r['sqrt_levels']):>8d}"
        )
    lines.append("")

    for run_info in all_results:
        lines.append(f"Source:  {run_info['source']}")
        lines.append(f"Count:   {run_info['count']}")
        lines.append(f"Output:  {run_info['output']}")
        lines.append("-" * 70)

    summary_text = "\n".join(lines)
    print(summary_text)

    txt_path = output_dir / "phase3b1_smoke_summary.txt"
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(summary_text + "\n")
    logger.info("Summary (txt) → %s", txt_path)

    json_path = output_dir / "phase3b1_smoke_summary.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    logger.info("Summary (json) → %s", json_path)

    logger.info("Phase 3B.1 smoke run complete.")
    return summary


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> dict:
    parser = argparse.ArgumentParser(
        description="Phase 3B.1 smoke run: JTTL + sqrt levels"
    )
    parser.add_argument(
        "--origins-dir",
        default="reports/phase2",
        help="Directory with Phase 2 origin CSVs (default: reports/phase2)",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/phase3b1",
        help="Output directory (default: reports/phase3b1)",
    )
    parser.add_argument(
        "--k",
        type=float,
        default=2.0,
        help="JTTL k parameter (default: 2.0)",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=365,
        help="JTTL horizon in calendar days (default: 365)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=8,
        help="Sqrt-level steps per increment (default: 8)",
    )
    parser.add_argument(
        "--max-origins",
        type=int,
        default=10,
        help="Max origins per Phase 2 CSV to process (default: 10)",
    )
    opts = parser.parse_args(args)

    return run(
        origins_dir=Path(opts.origins_dir),
        output_dir=Path(opts.output_dir),
        k=opts.k,
        horizon_days=opts.horizon_days,
        steps=opts.steps,
        max_origins_per_file=opts.max_origins,
    )


if __name__ == "__main__":
    main()
