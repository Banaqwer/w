"""
research/run_phase4_smoke.py

Phase 4 smoke run: Projection generation + Confluence engine.

Loads Phase 2 impulses and origins, runs all Phase 3→4 generators, clusters
projections into confluence zones, and writes reports.

Scope: Phase 4 only (projections + confluence).
No Phase 5+ (signals, execution, backtest) logic is present.

Usage
-----
    python -m research.run_phase4_smoke
    python -m research.run_phase4_smoke --phase2-dir reports/phase2
    python -m research.run_phase4_smoke --output-dir reports/phase4
    python -m research.run_phase4_smoke --max-impulses 30 --max-origins 10
    python -m research.run_phase4_smoke --dataset-version proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1

What it does
------------
1. Loads Phase 2 impulse CSVs from ``reports/phase2/``.
2. Reads each dataset's manifest to get ``missing_bar_count``.
3. Loads the processed dataset for bar-time resolution.
4. For each file (impulses):
   a. Runs ``measured_moves`` generator → Projections (price-only).
   b. Runs ``time_counts`` generator → Projections (time-only).
5. For each origin CSV:
   a. Runs ``jttl`` generator → Projections (time+price).
   b. Runs ``sqrt_levels`` generator → Projections (price-only).
6. Feeds all Projections into the confluence engine.
7. Writes:
   - ``reports/phase4/projections_<dataset_version>.json``
   - ``reports/phase4/zones_<dataset_version>.json``
8. Prints summary:
   - projection counts by generator
   - number of zones
   - top 10 zones by confluence_score (no trading interpretation)

Gap policy
----------
Reads ``missing_bar_count`` from each dataset manifest.  When > 0, logs the
gap count.  Time-count generator uses bar_index deltas (gap-safe by
construction; see DECISIONS.md 2026-03-06).

References
----------
signals/projections.py
signals/generators_measured_moves.py
signals/generators_jttl.py
signals/generators_sqrt_levels.py
signals/generators_time_counts.py
signals/confluence.py
modules/measured_moves.py
modules/jttl.py
modules/sqrt_levels.py
modules/time_counts.py
PROJECT_STATUS.md — Phase 4 section
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
from data.loader import load_manifest, load_processed
from modules.adjusted_angles import compute_impulse_angles
from modules.jttl import compute_jttl
from modules.measured_moves import compute_measured_moves
from modules.sqrt_levels import sqrt_levels
from modules.time_counts import build_bar_to_time_map, time_square_windows
from signals.confluence import build_confluence_zones
from signals.generators_angle_families import projections_from_angle_families
from signals.generators_jttl import projections_from_jttl_lines
from signals.generators_measured_moves import projections_from_measured_moves
from signals.generators_sqrt_levels import projections_from_sqrt_levels
from signals.generators_time_counts import projections_from_time_windows
from signals.projections import ConfluenceZone, Projection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase4_smoke")


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
    return sorted(phase2_dir.glob(f"{kind}_*.csv"))


def _parse_version_method(csv_path: Path) -> tuple:
    stem = csv_path.stem
    prefix = stem.split("_", 1)[0] + "_"
    rest = stem[len(prefix):]
    parts = rest.rsplit("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Cannot parse version/method from: {csv_path.name}")
    return parts[0], parts[1]


def _load_dataset_if_available(
    version: str, base_path: str = "data/processed"
) -> Optional[pd.DataFrame]:
    try:
        df = load_processed(version, base_path=base_path)
        logger.info("Loaded dataset: %s (%d rows)", version, len(df))
        return df
    except FileNotFoundError:
        logger.warning("Dataset not found: %s — bar-time resolution skipped.", version)
        return None


def _safe_load_manifest(version: str, base_path: str = "data/processed") -> dict:
    try:
        return load_manifest(version, base_path=base_path)
    except FileNotFoundError:
        logger.warning("Manifest not found for %s.", version)
        return {}


# ── Generator runners ─────────────────────────────────────────────────────────


def _run_measured_moves_projections(
    impulses_df: pd.DataFrame,
    max_impulses: int,
    ratios: List[float],
) -> List[Projection]:
    sample = impulses_df.head(max_impulses)
    impulse_dicts = sample.to_dict(orient="records")
    if not impulse_dicts:
        return []
    targets = compute_measured_moves(impulse_dicts, ratios=ratios, mode="raw")
    return projections_from_measured_moves(targets)


def _run_time_counts_projections(
    impulses_df: pd.DataFrame,
    max_impulses: int,
    multipliers: List[float],
    bar_to_time_map: Optional[dict],
    quality_scores: Optional[Dict[str, float]] = None,
) -> List[Projection]:
    sample = impulses_df.head(max_impulses)
    impulse_dicts = sample.to_dict(orient="records")
    if not impulse_dicts:
        return []
    all_windows = []
    for imp in impulse_dicts:
        windows = time_square_windows(
            imp,
            multipliers=multipliers,
            bar_to_time_map=bar_to_time_map or {},
        )
        all_windows.extend(windows)
    return projections_from_time_windows(
        all_windows,
        bar_to_time_map=bar_to_time_map,
        quality_scores=quality_scores,
    )


def _run_jttl_projections(
    origins_df: pd.DataFrame,
    max_origins: int,
    k: float,
    horizon_days: int,
) -> List[Projection]:
    sample = origins_df.head(max_origins)
    jttl_lines = []
    source_ids = []
    quality_scores_list = []

    for _, row in sample.iterrows():
        origin_time_raw = row.get("origin_time") or row.get("time")
        origin_price_raw = row.get("origin_price") or row.get("price")
        if origin_time_raw is None or origin_price_raw is None:
            continue
        try:
            origin_price = float(origin_price_raw)
            if origin_price <= 0:
                continue
            origin_time = pd.Timestamp(origin_time_raw)
            if origin_time.tzinfo is None:
                origin_time = origin_time.tz_localize("UTC")
            jl = compute_jttl(origin_time, origin_price, k=k, horizon_days=horizon_days)
            jttl_lines.append(jl)
            # Use index or bar_index as source_id
            bar_idx = row.get("bar_index", "")
            source_ids.append(f"jttl_origin_{bar_idx}")
            qs = row.get("quality_score", 0.5)
            quality_scores_list.append(float(qs) if qs is not None else 0.5)
        except Exception as exc:
            logger.debug("JTTL compute failed for origin: %s", exc)
            continue

    if not jttl_lines:
        return []
    return projections_from_jttl_lines(
        jttl_lines,
        quality_scores=quality_scores_list,
        source_ids=source_ids,
    )


def _run_sqrt_projections(
    origins_df: pd.DataFrame,
    max_origins: int,
    increments: List[float],
    steps: int,
) -> List[Projection]:
    sample = origins_df.head(max_origins)
    projections: List[Projection] = []

    for _, row in sample.iterrows():
        origin_price_raw = row.get("origin_price") or row.get("price")
        if origin_price_raw is None:
            continue
        try:
            origin_price = float(origin_price_raw)
            if origin_price <= 0:
                continue
            bar_idx = row.get("bar_index", "")
            source_id = f"sqrt_origin_{bar_idx}"
            levels = sqrt_levels(
                origin_price,
                increments=increments,
                steps=steps,
                direction="both",
            )
            projs = projections_from_sqrt_levels(
                levels,
                origin_price=origin_price,
                source_id=source_id,
            )
            projections.extend(projs)
        except Exception as exc:
            logger.debug("Sqrt levels failed for origin: %s", exc)
            continue

    return projections


def _run_angle_families_projections(
    impulses_df: pd.DataFrame,
    max_impulses: int,
    scale_basis: Dict[str, Any],
) -> List[Projection]:
    sample = impulses_df.head(max_impulses)
    impulse_dicts = sample.to_dict(orient="records")
    if not impulse_dicts:
        return []
    # Compute angles, then generate projections
    angle_records = compute_impulse_angles(impulse_dicts, scale_basis, price_mode="raw")
    return projections_from_angle_families(angle_records, scale_basis)


# ── Main ──────────────────────────────────────────────────────────────────────


def main(
    phase2_dir: Path,
    output_dir: Path,
    max_impulses: int,
    max_origins: int,
    ratios: List[float],
    multipliers: List[float],
    jttl_k: float,
    jttl_horizon: int,
    sqrt_increments: List[float],
    sqrt_steps: int,
    target_version: Optional[str],
) -> None:
    _ensure_dir(output_dir)

    impulse_csvs = _find_phase2_csvs(phase2_dir, "impulses")
    origins_csvs = _find_phase2_csvs(phase2_dir, "origins")

    if not impulse_csvs:
        logger.error("No impulse CSVs found in %s", phase2_dir)
        return

    # Build lookup: version → origins_df
    origins_lookup: Dict[str, pd.DataFrame] = {}
    for oc in origins_csvs:
        try:
            version, method = _parse_version_method(oc)
        except ValueError:
            continue
        key = f"{version}_{method}"
        origins_lookup[key] = pd.read_csv(oc)

    # Summary accumulators
    summary_rows: list = []
    all_projections: List[Projection] = []
    dataset_version_used: str = "unknown"

    for imp_csv in impulse_csvs:
        try:
            version, method = _parse_version_method(imp_csv)
        except ValueError:
            logger.warning("Skipping unrecognised CSV: %s", imp_csv.name)
            continue

        if target_version and version != target_version:
            continue

        dataset_version_used = version
        manifest = _safe_load_manifest(version)
        missing_bar_count = manifest.get("missing_bar_count", 0)
        if missing_bar_count > 0:
            logger.info(
                "Dataset %s has %d missing bar(s) — using bar_index deltas.",
                version,
                missing_bar_count,
            )

        impulses_df = pd.read_csv(imp_csv)
        if impulses_df.empty:
            logger.warning("Empty impulse CSV: %s", imp_csv.name)
            continue

        # Load dataset for bar-time resolution
        df = _load_dataset_if_available(version)
        bar_to_time_map: Optional[dict] = None
        scale_basis: Optional[Dict[str, Any]] = None
        if df is not None:
            bar_to_time_map = build_bar_to_time_map(df)
            try:
                scale_basis = get_angle_scale_basis(df)
            except Exception as exc:
                logger.debug("Scale basis computation failed: %s", exc)

        # Build quality score dict for time_counts
        quality_scores: Dict[str, float] = {}
        if "impulse_id" in impulses_df.columns and "quality_score" in impulses_df.columns:
            quality_scores = dict(
                zip(impulses_df["impulse_id"], impulses_df["quality_score"])
            )

        # ── Run generators ─────────────────────────────────────────────────

        mm_projs = _run_measured_moves_projections(impulses_df, max_impulses, ratios)
        tc_projs = _run_time_counts_projections(
            impulses_df, max_impulses, multipliers, bar_to_time_map, quality_scores
        )

        # Angle families generator (optional; requires scale_basis)
        af_projs: List[Projection] = []
        if scale_basis is not None:
            af_projs = _run_angle_families_projections(
                impulses_df, max_impulses, scale_basis
            )

        # Origins generators
        origins_key = f"{version}_{method}"
        origins_df = origins_lookup.get(origins_key, pd.DataFrame())

        jttl_projs = _run_jttl_projections(origins_df, max_origins, jttl_k, jttl_horizon)
        sqrt_projs = _run_sqrt_projections(origins_df, max_origins, sqrt_increments, sqrt_steps)

        file_projs = mm_projs + tc_projs + af_projs + jttl_projs + sqrt_projs
        all_projections.extend(file_projs)

        summary_rows.append({
            "source": f"{version}_{method}",
            "missing_bars": missing_bar_count,
            "mm_projections": len(mm_projs),
            "tc_projections": len(tc_projs),
            "af_projections": len(af_projs),
            "jttl_projections": len(jttl_projs),
            "sqrt_projections": len(sqrt_projs),
            "total_projections": len(file_projs),
        })

        logger.info(
            "%s_%s: mm=%d tc=%d af=%d jttl=%d sqrt=%d total=%d",
            version, method,
            len(mm_projs), len(tc_projs), len(af_projs),
            len(jttl_projs), len(sqrt_projs),
            len(file_projs),
        )

    if not all_projections:
        logger.warning("No projections generated; aborting.")
        return

    # ── Confluence ────────────────────────────────────────────────────────────
    logger.info("Running confluence engine on %d projections ...", len(all_projections))
    zones = build_confluence_zones(all_projections, min_cluster_size=1)
    logger.info("Confluence: %d zones produced.", len(zones))

    # ── Write outputs ─────────────────────────────────────────────────────────
    v_tag = target_version or dataset_version_used
    proj_path = output_dir / f"projections_{v_tag}.json"
    zones_path = output_dir / f"zones_{v_tag}.json"

    proj_dicts = [p.to_dict() for p in all_projections]
    zone_dicts = [z.to_dict() for z in zones]

    proj_path.write_text(json.dumps(proj_dicts, indent=2, default=str))
    zones_path.write_text(json.dumps(zone_dicts, indent=2, default=str))
    logger.info("Written: %s", proj_path)
    logger.info("Written: %s", zones_path)

    # ── Print summary ─────────────────────────────────────────────────────────
    _print_summary(summary_rows, all_projections, zones)


def _print_summary(
    summary_rows: list,
    projections: List[Projection],
    zones: List[ConfluenceZone],
) -> None:
    print()
    print("Phase 4 Smoke Run Summary")
    print("=" * 70)
    print()

    # Per-file breakdown
    print(
        f"{'Source':<55} {'miss':>5} {'mm':>6} {'tc':>6} {'af':>6} {'jttl':>6} {'sqrt':>6} {'tot':>6}"
    )
    print("-" * 100)
    tot_mm = tot_tc = tot_af = tot_jttl = tot_sqrt = 0
    for r in summary_rows:
        af_count = r.get("af_projections", 0)
        print(
            f"  {r['source']:<53} {r['missing_bars']:>5} "
            f"{r['mm_projections']:>6} {r['tc_projections']:>6} "
            f"{af_count:>6} "
            f"{r['jttl_projections']:>6} {r['sqrt_projections']:>6} "
            f"{r['total_projections']:>6}"
        )
        tot_mm += r["mm_projections"]
        tot_tc += r["tc_projections"]
        tot_af += af_count
        tot_jttl += r["jttl_projections"]
        tot_sqrt += r["sqrt_projections"]
    print("-" * 100)
    total_proj = len(projections)
    print(
        f"  {'GRAND TOTALS':<53} {'':>5} "
        f"{tot_mm:>6} {tot_tc:>6} {tot_af:>6} {tot_jttl:>6} {tot_sqrt:>6} {total_proj:>6}"
    )
    print()

    # Zone summary
    print(f"Total confluence zones: {len(zones)}")
    print()

    # Top 10 zones
    top = zones[:10]
    if top:
        print("Top 10 zones by confluence_score:")
        print(f"  {'zone_id':<18} {'score':>7} {'n_proj':>7} {'modules':<40} {'type'}")
        print("  " + "-" * 85)
        for z in top:
            mod_str = ", ".join(f"{k}:{v}" for k, v in sorted(z.module_counts.items()))
            zone_type = z.notes
            print(
                f"  {z.zone_id:<18} {z.confluence_score:>7.4f} "
                f"{len(z.contributing_projection_ids):>7}   "
                f"{mod_str:<40} {zone_type}"
            )
    print()
    print("NOTE: Phase 5 (confirmation, signals, execution, backtest) NOT started.")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 4 smoke run: Projection generation + Confluence engine."
    )
    p.add_argument(
        "--phase2-dir",
        default="reports/phase2",
        help="Directory containing Phase 2 impulse/origin CSVs (default: reports/phase2).",
    )
    p.add_argument(
        "--output-dir",
        default="reports/phase4",
        help="Output directory for Phase 4 reports (default: reports/phase4).",
    )
    p.add_argument(
        "--max-impulses",
        type=int,
        default=20,
        help="Maximum impulses to sample per file (default: 20).",
    )
    p.add_argument(
        "--max-origins",
        type=int,
        default=10,
        help="Maximum origins to sample per file (default: 10).",
    )
    p.add_argument(
        "--dataset-version",
        default=None,
        help="Run only for this dataset version (default: all).",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    main(
        phase2_dir=Path(args.phase2_dir),
        output_dir=Path(args.output_dir),
        max_impulses=args.max_impulses,
        max_origins=args.max_origins,
        ratios=_DEFAULT_RATIOS,
        multipliers=_DEFAULT_MULTIPLIERS,
        jttl_k=_DEFAULT_JTTL_K,
        jttl_horizon=_DEFAULT_JTTL_HORIZON,
        sqrt_increments=_DEFAULT_SQRT_INCREMENTS,
        sqrt_steps=_DEFAULT_SQRT_STEPS,
        target_version=args.dataset_version,
    )
