"""
research/run_phase2_smoke.py

Phase 2 smoke run: loads the official processed dataset(s), runs origin
selection and impulse detection, and writes results to reports/phase2/.

Usage
-----
    python -m research.run_phase2_smoke
    python -m research.run_phase2_smoke --config configs/default.yaml
    python -m research.run_phase2_smoke --base-path data/processed --output-dir reports/phase2

Outputs
-------
    reports/phase2/origins_{version}_{method}.csv
    reports/phase2/impulses_{version}_{method}.csv
    reports/phase2/phase2_smoke_summary.json   (machine-readable)
    reports/phase2/phase2_smoke_summary.txt    (human-readable)

Gap policy
----------
For the 6H dataset the manifest ``missing_bar_count`` is read automatically.
If ``missing_bar_count > 0``, ``skip_on_gap=True`` is passed to
:func:`~modules.impulse.detect_impulses` so that impulses spanning the gap are
silently skipped (DECISIONS.md 2026-03-06 / ASSUMPTIONS.md Assumption 18).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data.loader import load_manifest, load_processed
from modules.impulse import detect_impulses, impulses_to_dataframe
from modules.origin_selection import origins_to_dataframe, select_origins

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase2_smoke")


# ── Internal helpers ─────────────────────────────────────────────────────────


def _load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ── Core runner ──────────────────────────────────────────────────────────────


def run_on_dataset(
    version: str,
    method: str,
    method_kwargs: dict,
    max_bars: int,
    skip_on_gap: bool,
    output_dir: Path,
    base_path: str = "data/processed",
) -> dict:
    """Run origin selection and impulse detection for one dataset/method pair.

    Parameters
    ----------
    version:
        Processed dataset version string.
    method:
        Origin detection method (``"pivot"`` or ``"zigzag"``).
    method_kwargs:
        Keyword arguments forwarded to :func:`~modules.origin_selection.select_origins`.
    max_bars:
        Forward window size for impulse detection.
    skip_on_gap:
        Whether to skip impulses crossing a missing-bar gap.
    output_dir:
        Directory where CSV outputs are written.
    base_path:
        Root directory for processed datasets.

    Returns
    -------
    Summary dict with counts and output file paths.
    """
    logger.info("=== Dataset: %s | Method: %s ===", version, method)

    df = load_processed(version, base_path=base_path)
    manifest = load_manifest(version, base_path=base_path)
    missing_bar_count = manifest.get("missing_bar_count", 0)

    logger.info(
        "Loaded %d rows. missing_bar_count=%d skip_on_gap=%s",
        len(df),
        missing_bar_count,
        skip_on_gap,
    )

    if missing_bar_count > 0 and not skip_on_gap:
        logger.warning(
            "Dataset %s has %d missing bar(s) but skip_on_gap=False. "
            "Impulses crossing the gap will be included.",
            version,
            missing_bar_count,
        )

    # ── Origin selection ──────────────────────────────────────────────────
    origins = select_origins(df, method=method, **method_kwargs)
    origins_df = origins_to_dataframe(origins)

    origin_csv = output_dir / f"origins_{version}_{method}.csv"
    origins_df.to_csv(origin_csv, index=False)
    logger.info("Origins: %d  →  %s", len(origins), origin_csv)

    # ── Impulse detection ─────────────────────────────────────────────────
    impulses = detect_impulses(
        df, origins, max_bars=max_bars, skip_on_gap=skip_on_gap
    )
    impulses_df = impulses_to_dataframe(impulses)

    impulse_csv = output_dir / f"impulses_{version}_{method}.csv"
    impulses_df.to_csv(impulse_csv, index=False)
    logger.info("Impulses: %d  →  %s", len(impulses), impulse_csv)

    return {
        "version": version,
        "method": method,
        "rows": len(df),
        "missing_bar_count": missing_bar_count,
        "skip_on_gap": skip_on_gap,
        "origins_count": len(origins),
        "impulses_count": len(impulses),
        "origin_csv": str(origin_csv),
        "impulse_csv": str(impulse_csv),
    }


# ── Entry point ──────────────────────────────────────────────────────────────


def main(args=None) -> list:
    """Run Phase 2 smoke run and return list of result dicts."""
    parser = argparse.ArgumentParser(
        description="Phase 2 smoke run: origin selection + impulse detection"
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
        "--output-dir",
        default="reports/phase2",
        help="Output directory for Phase 2 reports (default: reports/phase2)",
    )
    opts = parser.parse_args(args)

    config = _load_config(opts.config)
    output_dir = Path(opts.output_dir)
    _ensure_dir(output_dir)

    version_1d = config["dataset"]["current_version"]
    version_6h = config["dataset"].get("version_6h")

    results = []

    # ── 1D dataset (required) ─────────────────────────────────────────────
    logger.info("--- 1D dataset ---")
    for method, kwargs in [
        ("pivot", {"n_bars": 5}),
        ("zigzag", {"reversal_pct": 20.0}),
    ]:
        result = run_on_dataset(
            version=version_1d,
            method=method,
            method_kwargs=kwargs,
            max_bars=200,
            skip_on_gap=False,
            output_dir=output_dir,
            base_path=opts.base_path,
        )
        results.append(result)

    # ── 6H dataset (optional) ─────────────────────────────────────────────
    if version_6h:
        logger.info("--- 6H dataset ---")
        manifest_6h = load_manifest(version_6h, base_path=opts.base_path)
        missing_bars_6h = manifest_6h.get("missing_bar_count", 0)
        skip_6h = missing_bars_6h > 0

        logger.info(
            "6H manifest: missing_bar_count=%d → skip_on_gap=%s",
            missing_bars_6h,
            skip_6h,
        )

        for method, kwargs in [
            ("pivot", {"n_bars": 5}),
            ("zigzag", {"reversal_pct": 5.0}),
        ]:
            result = run_on_dataset(
                version=version_6h,
                method=method,
                method_kwargs=kwargs,
                max_bars=200,
                skip_on_gap=skip_6h,
                output_dir=output_dir,
                base_path=opts.base_path,
            )
            results.append(result)

    # ── Write plain-text summary ──────────────────────────────────────────
    summary_path = output_dir / "phase2_smoke_summary.txt"
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write("Phase 2 Smoke Run Summary\n")
        fh.write("=" * 60 + "\n\n")
        for r in results:
            fh.write(f"Dataset:        {r['version']}\n")
            fh.write(f"Method:         {r['method']}\n")
            fh.write(f"Rows:           {r['rows']}\n")
            fh.write(f"Missing bars:   {r['missing_bar_count']}\n")
            fh.write(f"skip_on_gap:    {r['skip_on_gap']}\n")
            fh.write(f"Origins:        {r['origins_count']}\n")
            fh.write(f"Impulses:       {r['impulses_count']}\n")
            fh.write(f"Origins CSV:    {r['origin_csv']}\n")
            fh.write(f"Impulses CSV:   {r['impulse_csv']}\n")
            fh.write("-" * 60 + "\n")

    logger.info("Summary (txt) → %s", summary_path)

    # ── Write JSON summary (machine-readable artifact) ────────────────────
    json_path = output_dir / "phase2_smoke_summary.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=str)

    logger.info("Summary (json) → %s", json_path)
    logger.info(
        "Phase 2 smoke run complete. %d run(s) finished.", len(results)
    )

    return results


if __name__ == "__main__":
    main()
