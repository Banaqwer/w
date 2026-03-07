"""
research/run_phase3_smoke.py

Phase 3 smoke run: loads Phase 2 impulse outputs, computes adjusted angles,
and writes results to reports/phase3/.

Usage
-----
    python -m research.run_phase3_smoke
    python -m research.run_phase3_smoke --config configs/default.yaml
    python -m research.run_phase3_smoke --phase2-dir reports/phase2 --output-dir reports/phase3

Inputs
------
- Phase 2 impulse CSVs:  reports/phase2/impulses_{version}_{method}.csv
- Processed datasets:    data/processed/{version}/ (for scale_basis via atr_14)
- Dataset manifests:     data/processed/{version}/*_manifest.json

Outputs
-------
    reports/phase3/impulses_with_angles_{version}_{method}.json
    reports/phase3/phase3_smoke_summary.json   (machine-readable)
    reports/phase3/phase3_smoke_summary.txt    (human-readable)

Gap policy
----------
Angle computations use ``delta_t`` (bar-index delta) from the stored Impulse
data, not raw timestamps.  This is gap-safe for the 6H dataset
(missing_bar_count=1).  The manifest ``missing_bar_count`` is checked before
running 6H analysis and logged.  No impulses are skipped due to gaps at this
stage (gaps were already handled in Phase 2 detection).

References
----------
ASSUMPTIONS.md — Assumptions 14, 21, 22
DECISIONS.md   — 2026-03-07 Phase 3 gap policy
modules/adjusted_angles.py
core/coordinate_system.get_angle_scale_basis()
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.coordinate_system import get_angle_scale_basis
from data.loader import load_manifest, load_processed
from modules.adjusted_angles import (
    compute_impulse_angles,
    get_angle_families,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase3_smoke")


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _find_phase2_impulse_csvs(phase2_dir: Path) -> list:
    """Return all Phase 2 impulse CSV paths found in phase2_dir."""
    csvs = sorted(phase2_dir.glob("impulses_*.csv"))
    if not csvs:
        logger.warning(
            "No Phase 2 impulse CSVs found in %s. "
            "Run research/run_phase2_smoke.py first.",
            phase2_dir,
        )
    return csvs


def _parse_version_and_method(csv_path: Path) -> tuple[str, str]:
    """Extract (version, method) from a Phase 2 impulse CSV filename.

    Expected naming: ``impulses_{version}_{method}.csv``
    Method is the last ``_``-delimited token before ``.csv``.
    Version is everything between ``impulses_`` and the last ``_{method}``.
    """
    stem = csv_path.stem  # e.g. "impulses_proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1_pivot"
    assert stem.startswith("impulses_"), f"Unexpected CSV name: {csv_path.name}"
    rest = stem[len("impulses_"):]
    # Method is the last token
    parts = rest.rsplit("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Cannot parse version/method from filename: {csv_path.name}")
    version, method = parts
    return version, method


def _build_angle_histogram(
    records: list,
    family_field: str = "angle_family",
) -> dict:
    """Build a frequency count of angle families from a list of angle records."""
    counts: dict[str, int] = {}
    for r in records:
        family = r.get(family_field) or "unclassified"
        counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# ── Core runner ───────────────────────────────────────────────────────────────


def run_on_dataset_method(
    version: str,
    method: str,
    impulse_csv: Path,
    output_dir: Path,
    base_path: str = "data/processed",
    price_mode: str = "raw",
    family_tolerance_deg: float = 5.0,
) -> dict:
    """Compute adjusted angles for one Phase 2 impulse CSV.

    Parameters
    ----------
    version:
        Processed dataset version string.
    method:
        Origin detection method (e.g. ``"pivot"`` or ``"zigzag"``).
    impulse_csv:
        Path to the Phase 2 impulse CSV for this version/method.
    output_dir:
        Where to write the output JSON.
    base_path:
        Root directory for processed datasets (for loading scale_basis).
    price_mode:
        ``"raw"`` (default) or ``"log"``.
    family_tolerance_deg:
        Angle family bucketing tolerance in degrees.

    Returns
    -------
    Summary dict.
    """
    logger.info("=== %s | %s ===", version, method)

    # ── Load manifest and check gap status ────────────────────────────────
    manifest = load_manifest(version, base_path=base_path)
    missing_bar_count = manifest.get("missing_bar_count", 0)

    if missing_bar_count > 0:
        logger.info(
            "Dataset %s has missing_bar_count=%d. "
            "Phase 3 angle computation uses bar_index deltas (gap-safe). "
            "No impulses are skipped at this stage; gaps were handled in Phase 2.",
            version,
            missing_bar_count,
        )
    else:
        logger.info("Dataset %s: missing_bar_count=0 (no gaps).", version)

    # ── Load processed dataset for scale_basis ────────────────────────────
    df = load_processed(version, base_path=base_path)
    atr_warmup_rows = manifest.get("atr_warmup_rows", 14)
    scale_basis = get_angle_scale_basis(df, atr_warmup_rows=atr_warmup_rows)
    logger.info(
        "Scale basis: price_per_bar=%.4f (median ATR-14 over %d rows)",
        scale_basis["price_per_bar"],
        scale_basis["rows_used"],
    )

    # ── Load Phase 2 impulse CSV ──────────────────────────────────────────
    impulse_df = pd.read_csv(impulse_csv)
    impulse_records = impulse_df.to_dict(orient="records")
    logger.info("Loaded %d impulses from %s", len(impulse_records), impulse_csv)

    # ── Compute angles ────────────────────────────────────────────────────
    angle_records = compute_impulse_angles(
        impulse_records,
        scale_basis,
        price_mode=price_mode,
        family_tolerance_deg=family_tolerance_deg,
    )
    logger.info("Computed angles for %d impulse(s).", len(angle_records))

    # ── Write JSON output ─────────────────────────────────────────────────
    out_path = output_dir / f"impulses_with_angles_{version}_{method}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(angle_records, fh, indent=2, default=str)
    logger.info("Wrote → %s", out_path)

    # ── Angle family histogram ─────────────────────────────────────────────
    histogram = _build_angle_histogram(angle_records)

    return {
        "version": version,
        "method": method,
        "missing_bar_count": missing_bar_count,
        "price_mode": price_mode,
        "impulses_input": len(impulse_records),
        "impulses_with_angles": len(angle_records),
        "scale_basis_price_per_bar": scale_basis["price_per_bar"],
        "angle_family_histogram": histogram,
        "output_json": str(out_path),
    }


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> list:
    """Run Phase 3 smoke run and return list of result dicts."""
    parser = argparse.ArgumentParser(
        description="Phase 3 smoke run: compute adjusted angles for Phase 2 impulses"
    )
    parser.add_argument(
        "--config",
        default="configs/default.yaml",
        help="Path to config YAML (default: configs/default.yaml)",
    )
    parser.add_argument(
        "--base-path",
        default="data/processed",
        help="Base path for processed datasets (default: data/processed)",
    )
    parser.add_argument(
        "--phase2-dir",
        default="reports/phase2",
        help="Directory containing Phase 2 impulse CSVs (default: reports/phase2)",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/phase3",
        help="Output directory for Phase 3 reports (default: reports/phase3)",
    )
    parser.add_argument(
        "--price-mode",
        default="raw",
        choices=["raw", "log"],
        help="Angle price mode: raw or log (default: raw)",
    )
    opts = parser.parse_args(args)

    _load_config(opts.config)   # validate config is loadable
    phase2_dir = Path(opts.phase2_dir)
    output_dir = Path(opts.output_dir)
    _ensure_dir(output_dir)

    # ── Discover Phase 2 impulse CSVs ─────────────────────────────────────
    csvs = _find_phase2_impulse_csvs(phase2_dir)
    if not csvs:
        logger.error("No Phase 2 impulse CSVs found; aborting Phase 3 smoke run.")
        return []

    results = []
    for csv_path in csvs:
        version, method = _parse_version_and_method(csv_path)
        result = run_on_dataset_method(
            version=version,
            method=method,
            impulse_csv=csv_path,
            output_dir=output_dir,
            base_path=opts.base_path,
            price_mode=opts.price_mode,
        )
        results.append(result)

    # ── Print text summary ─────────────────────────────────────────────────
    families = get_angle_families()
    family_order = [f["name"] for f in families] + ["unclassified"]

    summary_lines = ["Phase 3 Smoke Run Summary", "=" * 70, ""]
    for r in results:
        summary_lines.append(f"Dataset:         {r['version']}")
        summary_lines.append(f"Method:          {r['method']}")
        summary_lines.append(f"Missing bars:    {r['missing_bar_count']}")
        summary_lines.append(f"Price mode:      {r['price_mode']}")
        summary_lines.append(f"Impulses input:  {r['impulses_input']}")
        summary_lines.append(f"Angles computed: {r['impulses_with_angles']}")
        summary_lines.append(f"Scale (ppb):     {r['scale_basis_price_per_bar']:.4f}")
        summary_lines.append("Angle family histogram:")
        hist = r["angle_family_histogram"]
        total = sum(hist.values())
        for fname in family_order:
            if fname in hist:
                pct = 100.0 * hist[fname] / total if total > 0 else 0.0
                summary_lines.append(f"  {fname:12s}: {hist[fname]:5d}  ({pct:5.1f}%)")
        unclassified = hist.get("unclassified", 0)
        if "unclassified" not in [f for f in hist if f in family_order]:
            pct = 100.0 * unclassified / total if total > 0 else 0.0
            summary_lines.append(f"  {'unclassified':12s}: {unclassified:5d}  ({pct:5.1f}%)")
        summary_lines.append(f"Output:          {r['output_json']}")
        summary_lines.append("-" * 70)

    summary_text = "\n".join(summary_lines)
    print(summary_text)

    # ── Write plain-text summary ───────────────────────────────────────────
    txt_path = output_dir / "phase3_smoke_summary.txt"
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(summary_text + "\n")
    logger.info("Summary (txt) → %s", txt_path)

    # ── Write JSON summary ─────────────────────────────────────────────────
    json_path = output_dir / "phase3_smoke_summary.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=str)
    logger.info("Summary (json) → %s", json_path)

    logger.info(
        "Phase 3 smoke run complete. %d run(s) finished.", len(results)
    )
    return results


if __name__ == "__main__":
    main()
