"""
research/run_phase3b_smoke.py

Integrated Phase 3B smoke run.

Runs all Phase 3B modules (adjusted angles, measured moves, JTTL, sqrt levels,
time counts) on a sample of Phase 2 impulses and origins, then writes results
to reports/phase3b/.

Scope: Phase 3B only.
No Phase 4+ (projections, confluence, signals, backtest) logic is present.

Usage
-----
    python -m research.run_phase3b_smoke
    python -m research.run_phase3b_smoke --phase2-dir reports/phase2
    python -m research.run_phase3b_smoke --output-dir reports/phase3b
    python -m research.run_phase3b_smoke --max-impulses 20 --max-origins 10

What it does
------------
1. Loads Phase 2 impulse and origin CSVs from ``reports/phase2/``.
2. Reads each dataset's manifest to get ``missing_bar_count``.
3. For a sample of impulses per file:
   a. Adjusted angles (raw + log modes).
   b. Measured moves (raw + log modes, default ratios).
   c. Time-count summaries (bar-index delta_t, windows).
4. For a sample of origins per file:
   a. JTTL lines.
   b. Sqrt levels.
5. Writes one JSON per dataset file to ``reports/phase3b/``.
6. Writes a concise text + JSON summary.

Gap policy
----------
Reads ``missing_bar_count`` from each dataset manifest (see DECISIONS.md
2026-03-06).  When > 0:
- Logs that the dataset has missing bars.
- Time-count output uses bar_index deltas (gap-safe by construction).
- All other module operations are unaffected (they use Impulse.delta_t,
  which is also bar-index based).

References
----------
modules/adjusted_angles.py
modules/measured_moves.py
modules/jttl.py
modules/sqrt_levels.py
modules/time_counts.py
PROJECT_STATUS.md — Phase 3B section
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.coordinate_system import get_angle_scale_basis
from data.loader import load_manifest, load_processed, list_processed_versions
from modules.adjusted_angles import compute_impulse_angles
from modules.jttl import compute_jttl
from modules.measured_moves import compute_measured_moves
from modules.sqrt_levels import sqrt_levels
from modules.time_counts import time_square_windows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase3b_smoke")


# ── Config defaults ───────────────────────────────────────────────────────────

_DEFAULT_RATIOS = [0.5, 1.0, 1.5, 2.0]
_DEFAULT_MULTIPLIERS = [0.5, 1.0, 1.5, 2.0]
_DEFAULT_JTTL_K = 2.0
_DEFAULT_JTTL_HORIZON = 365
_DEFAULT_SQRT_INCREMENTS = [0.25, 0.5, 0.75, 1.0]
_DEFAULT_SQRT_STEPS = 8


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _find_phase2_csvs(phase2_dir: Path, kind: str) -> list:
    """Return sorted list of Phase 2 CSVs of the given kind ('impulses' or 'origins')."""
    return sorted(phase2_dir.glob(f"{kind}_*.csv"))


def _parse_version_method(csv_path: Path) -> tuple:
    """Extract (version, method) from a Phase 2 CSV filename."""
    stem = csv_path.stem
    prefix = stem.split("_", 1)[0] + "_"  # 'impulses_' or 'origins_'
    rest = stem[len(prefix):]
    parts = rest.rsplit("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Cannot parse version/method from: {csv_path.name}")
    return parts[0], parts[1]


def _load_dataset_if_available(
    version: str, base_path: str = "data/processed"
) -> Optional[pd.DataFrame]:
    """Load a processed dataset silently; return None if unavailable."""
    try:
        df = load_processed(version, base_path=base_path)
        logger.info("Loaded dataset: %s (%d rows)", version, len(df))
        return df
    except FileNotFoundError:
        logger.warning("Dataset not found: %s — time resolution will be skipped.", version)
        return None


def _safe_load_manifest(version: str, base_path: str = "data/processed") -> dict:
    """Load manifest; return empty dict on failure."""
    try:
        return load_manifest(version, base_path=base_path)
    except FileNotFoundError:
        logger.warning("Manifest not found for %s.", version)
        return {}


# ── Module runners ────────────────────────────────────────────────────────────


def _run_angles_and_moves(
    impulses_df: pd.DataFrame,
    scale_basis: dict,
    max_impulses: int,
    ratios: List[float],
    multipliers: List[float],
    bar_to_time_map: Optional[dict],
) -> dict:
    """Run adjusted angles, measured moves, and time counts on a sample of impulses."""
    sample = impulses_df.head(max_impulses)
    impulse_dicts = sample.to_dict(orient="records")

    if not impulse_dicts:
        return {
            "n_impulses": 0,
            "angles_raw": [],
            "angles_log": [],
            "measured_moves_raw": [],
            "measured_moves_log": [],
            "time_windows": [],
        }

    # ── Adjusted angles ────────────────────────────────────────────────────
    angles_raw = compute_impulse_angles(impulse_dicts, scale_basis, price_mode="raw")
    angles_log = compute_impulse_angles(impulse_dicts, scale_basis, price_mode="log")

    # Build angle-family tag dict (impulse_id → family name) for measured moves.
    family_tags: Dict[str, str] = {
        a["impulse_id"]: a["angle_family"]
        for a in angles_raw
        if a.get("angle_family")
    }

    # ── Measured moves ─────────────────────────────────────────────────────
    mm_raw = compute_measured_moves(
        impulse_dicts,
        ratios=ratios,
        mode="raw",
        angle_family_tags=family_tags,
    )
    mm_log = compute_measured_moves(
        impulse_dicts,
        ratios=ratios,
        mode="log",
        angle_family_tags=family_tags,
    )

    # ── Time counts ────────────────────────────────────────────────────────
    all_windows = []
    for imp in impulse_dicts:
        windows = time_square_windows(
            imp,
            multipliers=multipliers,
            bar_to_time_map=bar_to_time_map or {},
        )
        all_windows.extend([w.to_dict() for w in windows])

    return {
        "n_impulses": len(sample),
        "angles_raw": [
            {k: v for k, v in a.items()
             if k in ("impulse_id", "angle_deg", "angle_normalized",
                      "angle_family", "angle_family_delta_deg")}
            for a in angles_raw
        ],
        "angles_log": [
            {k: v for k, v in a.items()
             if k in ("impulse_id", "angle_deg", "angle_normalized",
                      "angle_family", "angle_family_delta_deg")}
            for a in angles_log
        ],
        "measured_moves_raw_count": len(mm_raw),
        "measured_moves_log_count": len(mm_log),
        "measured_moves_raw_sample": [t.to_dict() for t in mm_raw[:5]],
        "measured_moves_log_sample": [t.to_dict() for t in mm_log[:5]],
        "time_windows_count": len(all_windows),
        "time_windows_sample": all_windows[:5],
    }


def _run_jttl_and_sqrt(
    origins_df: pd.DataFrame,
    max_origins: int,
    k: float,
    horizon_days: int,
    increments: List[float],
    steps: int,
) -> dict:
    """Run JTTL and sqrt levels on a sample of origins."""
    sample = origins_df.head(max_origins)
    results = []

    for _, row in sample.iterrows():
        t0 = pd.Timestamp(str(row["origin_time"]))
        if t0.tzinfo is None:
            t0 = t0.tz_localize("UTC")
        p0 = float(row["origin_price"])

        jttl = compute_jttl(t0, p0, k=k, horizon_days=horizon_days)
        levels = sqrt_levels(p0, increments=increments, steps=steps)

        results.append({
            "origin_time": str(t0),
            "origin_price": p0,
            "jttl": jttl.to_dict(),
            "sqrt_levels_count": len(levels),
            "sqrt_levels_sample": [lv.to_dict() for lv in levels[:4]],
        })

    return {
        "n_origins": len(sample),
        "results": results,
    }


# ── Core runner ───────────────────────────────────────────────────────────────


def run(
    phase2_dir: Path,
    output_dir: Path,
    max_impulses: int = 20,
    max_origins: int = 10,
    ratios: Optional[List[float]] = None,
    multipliers: Optional[List[float]] = None,
    jttl_k: float = _DEFAULT_JTTL_K,
    jttl_horizon_days: int = _DEFAULT_JTTL_HORIZON,
    sqrt_increments: Optional[List[float]] = None,
    sqrt_steps: int = _DEFAULT_SQRT_STEPS,
    data_base_path: str = "data/processed",
) -> dict:
    """Run integrated Phase 3B smoke on all Phase 2 impulse/origin files.

    Parameters
    ----------
    phase2_dir:
        Directory containing Phase 2 impulse and origin CSVs.
    output_dir:
        Directory to write Phase 3B output JSONs.
    max_impulses:
        Maximum impulses per Phase 2 file to process.
    max_origins:
        Maximum origins per Phase 2 file to process.
    ratios:
        Measured-move and JTTL ratios. Default [0.5, 1.0, 1.5, 2.0].
    multipliers:
        Time-count multipliers. Default [0.5, 1.0, 1.5, 2.0].
    jttl_k:
        JTTL k parameter. Default 2.0.
    jttl_horizon_days:
        JTTL horizon. Default 365 calendar days.
    sqrt_increments:
        Sqrt-level increments. Default [0.25, 0.5, 0.75, 1.0].
    sqrt_steps:
        Sqrt-level steps. Default 8.
    data_base_path:
        Path to processed datasets directory.

    Returns
    -------
    Summary dict.
    """
    if ratios is None:
        ratios = _DEFAULT_RATIOS
    if multipliers is None:
        multipliers = _DEFAULT_MULTIPLIERS
    if sqrt_increments is None:
        sqrt_increments = _DEFAULT_SQRT_INCREMENTS

    _ensure_dir(output_dir)

    all_run_summaries = []
    grand_impulse_count = 0
    grand_angle_count = 0
    grand_mm_raw_count = 0
    grand_mm_log_count = 0
    grand_window_count = 0
    grand_origin_count = 0

    impulse_csvs = _find_phase2_csvs(phase2_dir, "impulses")
    origin_csvs = _find_phase2_csvs(phase2_dir, "origins")

    # Build a lookup from (version, method) → origins CSV path.
    origin_csv_map: Dict[tuple, Path] = {}
    for ocsv in origin_csvs:
        try:
            v, m = _parse_version_method(ocsv)
            origin_csv_map[(v, m)] = ocsv
        except ValueError:
            continue

    if not impulse_csvs:
        logger.warning(
            "No Phase 2 impulse CSVs found in %s. "
            "Run research/run_phase2_smoke.py first.",
            phase2_dir,
        )

    for imp_csv in impulse_csvs:
        try:
            version, method = _parse_version_method(imp_csv)
        except ValueError as exc:
            logger.warning("Skipping %s: %s", imp_csv.name, exc)
            continue

        logger.info("=== %s | %s ===", version, method)

        # ── Load manifest for missing_bar_count ────────────────────────────
        manifest = _safe_load_manifest(version, base_path=data_base_path)
        missing_bar_count = int(manifest.get("missing_bar_count", 0))
        if missing_bar_count > 0:
            logger.info(
                "  manifest missing_bar_count=%d > 0; "
                "time counts use bar_index deltas (gap-safe).",
                missing_bar_count,
            )

        # ── Load impulses CSV ──────────────────────────────────────────────
        impulses_df = pd.read_csv(imp_csv)
        logger.info(
            "  Loaded %d impulses; processing first %d.",
            len(impulses_df),
            min(max_impulses, len(impulses_df)),
        )

        # ── Load dataset for scale basis and bar→time map ──────────────────
        df_dataset = _load_dataset_if_available(version, base_path=data_base_path)

        if df_dataset is not None and "atr_14" in df_dataset.columns:
            scale_basis = get_angle_scale_basis(df_dataset)
            logger.info(
                "  Scale basis: price_per_bar=%.4f (median ATR-14, %d rows)",
                scale_basis["price_per_bar"],
                scale_basis["rows_used"],
            )
            # Build bar→time map for time-count resolution.
            from modules.time_counts import build_bar_to_time_map
            bar_to_time_map = build_bar_to_time_map(df_dataset)
        else:
            # Fallback: compute a rough scale from impulses
            logger.warning(
                "  Dataset/ATR not available; using slope_raw-based fallback for scale basis."
            )
            if len(impulses_df) > 0:
                median_slope = float(impulses_df["slope_raw"].abs().median())
                fallback_ppb = max(median_slope, 1.0)
            else:
                fallback_ppb = 1000.0
            scale_basis = {
                "price_per_bar": fallback_ppb,
                "atr_column_used": "fallback_slope_raw",
                "rows_excluded_warmup": 0,
                "rows_used": len(impulses_df),
            }
            bar_to_time_map = None

        # ── Run angles + measured moves + time counts ──────────────────────
        result_am = _run_angles_and_moves(
            impulses_df=impulses_df,
            scale_basis=scale_basis,
            max_impulses=max_impulses,
            ratios=ratios,
            multipliers=multipliers,
            bar_to_time_map=bar_to_time_map,
        )

        # ── Run JTTL + sqrt levels on origins ──────────────────────────────
        origins_path = origin_csv_map.get((version, method))
        if origins_path is not None:
            origins_df = pd.read_csv(origins_path)
            logger.info(
                "  Loaded %d origins; processing first %d.",
                len(origins_df),
                min(max_origins, len(origins_df)),
            )
            result_jttl = _run_jttl_and_sqrt(
                origins_df=origins_df,
                max_origins=max_origins,
                k=jttl_k,
                horizon_days=jttl_horizon_days,
                increments=sqrt_increments,
                steps=sqrt_steps,
            )
        else:
            logger.warning("  No matching origins CSV for %s/%s.", version, method)
            result_jttl = {"n_origins": 0, "results": []}

        # ── Accumulate counts ──────────────────────────────────────────────
        n_imp = result_am["n_impulses"]
        n_angles = len(result_am["angles_raw"])
        n_mm_raw = result_am["measured_moves_raw_count"]
        n_mm_log = result_am["measured_moves_log_count"]
        n_windows = result_am["time_windows_count"]
        n_orig = result_jttl["n_origins"]

        grand_impulse_count += n_imp
        grand_angle_count += n_angles
        grand_mm_raw_count += n_mm_raw
        grand_mm_log_count += n_mm_log
        grand_window_count += n_windows
        grand_origin_count += n_orig

        # ── Write per-dataset JSON ─────────────────────────────────────────
        out_path = output_dir / f"phase3b_{version}_{method}.json"
        output_payload = {
            "version": version,
            "method": method,
            "missing_bar_count": missing_bar_count,
            "scale_basis": scale_basis,
            "angles_and_moves": result_am,
            "jttl_and_sqrt": result_jttl,
        }
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(output_payload, fh, indent=2, default=str)
        logger.info("  Wrote → %s", out_path)

        all_run_summaries.append({
            "source": f"{version}_{method}",
            "missing_bar_count": missing_bar_count,
            "n_impulses": n_imp,
            "n_angles": n_angles,
            "n_mm_raw": n_mm_raw,
            "n_mm_log": n_mm_log,
            "n_time_windows": n_windows,
            "n_origins": n_orig,
            "output": str(out_path),
        })

    # ── Grand summary ──────────────────────────────────────────────────────
    summary = {
        "phase": "3B",
        "scope": "adjusted_angles + measured_moves + time_counts + jttl + sqrt_levels",
        "ratios": ratios,
        "multipliers": multipliers,
        "jttl_k": jttl_k,
        "jttl_horizon_days": jttl_horizon_days,
        "sqrt_increments": sqrt_increments,
        "sqrt_steps": sqrt_steps,
        "grand_totals": {
            "impulses_processed": grand_impulse_count,
            "angles_computed": grand_angle_count,
            "mm_raw_targets": grand_mm_raw_count,
            "mm_log_targets": grand_mm_log_count,
            "time_windows": grand_window_count,
            "origins_processed": grand_origin_count,
        },
        "runs": all_run_summaries,
    }

    # ── Text summary ───────────────────────────────────────────────────────
    lines = ["Phase 3B Integrated Smoke Run Summary", "=" * 70, ""]
    lines.append(f"Measured-move ratios:   {ratios}")
    lines.append(f"Time-count multipliers: {multipliers}")
    lines.append(f"JTTL k:                 {jttl_k}")
    lines.append(f"JTTL horizon:           {jttl_horizon_days} calendar days")
    lines.append(f"Sqrt increments:        {sqrt_increments}")
    lines.append(f"Sqrt steps:             {sqrt_steps}")
    lines.append("")

    lines.append(
        f"{'Source':50s}  {'miss':>4s}  {'imp':>4s}  "
        f"{'ang':>4s}  {'mmR':>5s}  {'mmL':>5s}  {'win':>4s}  {'orig':>4s}"
    )
    lines.append("-" * 90)
    for r in all_run_summaries:
        lines.append(
            f"  {r['source']:48s}  {r['missing_bar_count']:>4d}  "
            f"{r['n_impulses']:>4d}  {r['n_angles']:>4d}  "
            f"{r['n_mm_raw']:>5d}  {r['n_mm_log']:>5d}  "
            f"{r['n_time_windows']:>4d}  {r['n_origins']:>4d}"
        )
    lines.append("-" * 90)
    gt = summary["grand_totals"]
    lines.append(
        f"  {'GRAND TOTALS':48s}        "
        f"{gt['impulses_processed']:>4d}  {gt['angles_computed']:>4d}  "
        f"{gt['mm_raw_targets']:>5d}  {gt['mm_log_targets']:>5d}  "
        f"{gt['time_windows']:>4d}  {gt['origins_processed']:>4d}"
    )
    lines.append("")
    lines.append("NOTE: Phase 4 (projections, confluence, signals, backtest) NOT started.")

    summary_text = "\n".join(lines)
    print(summary_text)

    txt_path = output_dir / "phase3b_smoke_summary.txt"
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(summary_text + "\n")
    logger.info("Summary (txt) → %s", txt_path)

    json_path = output_dir / "phase3b_smoke_summary.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    logger.info("Summary (json) → %s", json_path)

    logger.info("Phase 3B smoke run complete.")
    return summary


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> dict:
    parser = argparse.ArgumentParser(
        description="Phase 3B integrated smoke run: adjusted_angles + "
                    "measured_moves + time_counts + JTTL + sqrt_levels"
    )
    parser.add_argument(
        "--phase2-dir",
        default="reports/phase2",
        help="Directory with Phase 2 impulse/origin CSVs (default: reports/phase2)",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/phase3b",
        help="Output directory (default: reports/phase3b)",
    )
    parser.add_argument(
        "--max-impulses",
        type=int,
        default=20,
        help="Max impulses per Phase 2 file (default: 20)",
    )
    parser.add_argument(
        "--max-origins",
        type=int,
        default=10,
        help="Max origins per Phase 2 file (default: 10)",
    )
    parser.add_argument(
        "--jttl-k",
        type=float,
        default=2.0,
        help="JTTL k parameter (default: 2.0)",
    )
    parser.add_argument(
        "--jttl-horizon-days",
        type=int,
        default=365,
        help="JTTL horizon in calendar days (default: 365)",
    )
    parser.add_argument(
        "--sqrt-steps",
        type=int,
        default=8,
        help="Sqrt-level steps per increment (default: 8)",
    )
    parser.add_argument(
        "--data-base-path",
        default="data/processed",
        help="Path to processed datasets (default: data/processed)",
    )
    opts = parser.parse_args(args)

    return run(
        phase2_dir=Path(opts.phase2_dir),
        output_dir=Path(opts.output_dir),
        max_impulses=opts.max_impulses,
        max_origins=opts.max_origins,
        jttl_k=opts.jttl_k,
        jttl_horizon_days=opts.jttl_horizon_days,
        sqrt_steps=opts.sqrt_steps,
        data_base_path=opts.data_base_path,
    )


if __name__ == "__main__":
    main()
