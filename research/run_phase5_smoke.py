"""
research/run_phase5_smoke.py

Phase 5 smoke run: Signal generation + Confirmation checks.

Loads Phase 4 projections/zones JSON, generates SignalCandidate objects,
runs confirmation checks on a deterministic recent window of 6H data, and
writes structured reports.

Scope: Phase 5 only (signal candidates + confirmation checks).
No Phase 6+ (backtest engine, PnL reporting, performance claims) logic present.

Usage
-----
    python -m research.run_phase5_smoke
    python -m research.run_phase5_smoke --phase4-dir reports/phase4
    python -m research.run_phase5_smoke --output-dir reports/phase5
    python -m research.run_phase5_smoke --dataset-version proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1
    python -m research.run_phase5_smoke --confirm-window 30
    python -m research.run_phase5_smoke --min-score-neutral 0.4

What it does
------------
1. Scans ``reports/phase4/`` for zones_<dataset_version>.json and
   projections_<dataset_version>.json files.
2. Loads the corresponding processed dataset and manifest from
   ``data/processed/<dataset_version>/``.
3. Reads ``missing_bar_count`` from the manifest.
4. Generates SignalCandidate objects from the zones + projections.
5. Selects a deterministic recent window from the 6H dataset
   (last ``--confirm-window`` bars; default 30).
6. Runs all confirmation checks on each signal against that window.
7. Writes:
   - ``reports/phase5/signals_<dataset_version>.json``
   - ``reports/phase5/confirmations_<dataset_version>.json``
8. Prints summary:
   - #zones
   - #signals produced
   - breakdown by bias
   - breakdown by score bucket (0–0.25, 0.25–0.5, 0.5–0.75, 0.75–1.0)
   - confirmation pass/fail counts per check

Gap policy
----------
Reads ``missing_bar_count`` from manifest.  When > 0:
- Logs the count.
- Signal generator appends ``strict_multi_candle`` to confirmations_required.
- Confirmation results note the gap in metadata.

Determinism guarantee
---------------------
The confirmation window is always the last ``N`` bars of the processed
dataset sorted by timestamp.  No live data, no random selection.

References
----------
signals/signal_types.py — SignalCandidate, ConfirmationResult
signals/signal_generation.py — generate_signals
signals/confirmations.py — run_all_confirmations
signals/projections.py — ConfluenceZone, Projection
data/loader.py — load_manifest, load_processed
PROJECT_STATUS.md — Phase 5 section
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data.loader import load_manifest, load_processed
from signals.confirmations import run_all_confirmations
from signals.projections import ConfluenceZone, Projection
from signals.signal_generation import generate_signals
from signals.signal_types import ConfirmationResult, SignalCandidate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_phase5_smoke")

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_PHASE4_DIR = "reports/phase4"
_DEFAULT_OUTPUT_DIR = "reports/phase5"
_DEFAULT_CONFIRM_WINDOW = 30  # number of recent 6H bars used for confirmation checks
_DEFAULT_MIN_SCORE_NEUTRAL = 0.5
_DEFAULT_INVALIDATION_BUFFER = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _safe_load_manifest(version: str, base_path: str = "data/processed") -> dict:
    try:
        return load_manifest(version, base_path=base_path)
    except FileNotFoundError:
        logger.warning("Manifest not found for %s.", version)
        return {}


def _safe_load_processed(
    version: str, base_path: str = "data/processed"
) -> Optional[pd.DataFrame]:
    try:
        df = load_processed(version, base_path=base_path)
        logger.info("Loaded dataset: %s (%d rows)", version, len(df))
        return df
    except FileNotFoundError:
        logger.warning("Dataset not found: %s — confirmation window unavailable.", version)
        return None


def _find_phase4_zone_files(phase4_dir: Path) -> list:
    return sorted(phase4_dir.glob("zones_*.json"))


def _extract_version_from_filename(path: Path, prefix: str) -> Optional[str]:
    """Extract dataset version from a filename like 'zones_<version>.json'."""
    stem = path.stem  # e.g. "zones_proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1"
    if not stem.startswith(prefix):
        return None
    return stem.removeprefix(prefix)


def _load_projections_json(path: Path) -> List[Projection]:
    """Load projections from a Phase 4 JSON file."""
    if not path.exists():
        logger.warning("Projections file not found: %s", path)
        return []
    raw = json.loads(path.read_text())
    projections: List[Projection] = []
    for d in raw:
        try:
            p = _dict_to_projection(d)
            projections.append(p)
        except Exception as exc:
            logger.debug("Skipping malformed projection: %s — %s", d.get("projection_id"), exc)
    return projections


def _load_zones_json(path: Path) -> List[ConfluenceZone]:
    """Load confluence zones from a Phase 4 JSON file."""
    if not path.exists():
        logger.warning("Zones file not found: %s", path)
        return []
    raw = json.loads(path.read_text())
    zones: List[ConfluenceZone] = []
    for d in raw:
        try:
            z = _dict_to_zone(d)
            zones.append(z)
        except Exception as exc:
            logger.debug("Skipping malformed zone: %s — %s", d.get("zone_id"), exc)
    return zones


def _dict_to_projection(d: dict) -> Projection:
    """Reconstruct a Projection from a JSON dict."""
    tb = d.get("time_band", [None, None])
    tb_lo = pd.Timestamp(tb[0]) if tb[0] is not None else None
    tb_hi = pd.Timestamp(tb[1]) if tb[1] is not None else None
    pb = d.get("price_band", [None, None])
    pt = d.get("projected_time")
    return Projection(
        projection_id=d["projection_id"],
        module_name=d["module_name"],
        source_id=d["source_id"],
        projected_time=pd.Timestamp(pt) if pt is not None else None,
        projected_price=d.get("projected_price"),
        time_band=(tb_lo, tb_hi),
        price_band=(pb[0], pb[1]),
        direction_hint=d["direction_hint"],
        raw_score=float(d["raw_score"]),
        metadata=d.get("metadata", {}),
    )


def _dict_to_zone(d: dict) -> ConfluenceZone:
    """Reconstruct a ConfluenceZone from a JSON dict."""
    tw = d.get("time_window")
    time_window = None
    if tw is not None:
        time_window = (pd.Timestamp(tw[0]), pd.Timestamp(tw[1]))
    pw = d.get("price_window")
    price_window = None
    if pw is not None:
        price_window = (float(pw[0]), float(pw[1]))
    return ConfluenceZone(
        zone_id=d["zone_id"],
        time_window=time_window,
        price_window=price_window,
        contributing_projection_ids=d.get("contributing_projection_ids", []),
        confluence_score=float(d["confluence_score"]),
        module_counts=d.get("module_counts", {}),
        notes=d.get("notes", ""),
    )


def _select_confirmation_window(
    df: pd.DataFrame, n_bars: int
) -> pd.DataFrame:
    """Return the last ``n_bars`` rows of ``df``, sorted by index (deterministic).

    The DataFrame must have a DatetimeIndex or a timestamp column.  The result
    is always the tail of the sorted dataset — no random sampling.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    # Ensure sorted by index (timestamp ascending)
    df_sorted = df.sort_index()
    return df_sorted.tail(n_bars).copy()


def _score_bucket(score: float) -> str:
    if score < 0.25:
        return "0.00–0.25"
    if score < 0.50:
        return "0.25–0.50"
    if score < 0.75:
        return "0.50–0.75"
    return "0.75–1.00"


# ── Main ──────────────────────────────────────────────────────────────────────


def main(
    phase4_dir: Path,
    output_dir: Path,
    target_version: Optional[str],
    confirm_window: int,
    min_score_neutral: float,
    invalidation_buffer: float,
) -> None:
    _ensure_dir(output_dir)

    zone_files = _find_phase4_zone_files(phase4_dir)
    if not zone_files:
        logger.error("No zones_*.json files found in %s", phase4_dir)
        return

    for zones_path in zone_files:
        version = _extract_version_from_filename(zones_path, "zones_")
        if version is None:
            logger.warning("Cannot parse version from: %s", zones_path.name)
            continue

        if target_version and version != target_version:
            continue

        logger.info("Processing dataset version: %s", version)

        # ── Load Phase 4 artifacts ────────────────────────────────────────────
        proj_path = zones_path.parent / f"projections_{version}.json"
        projections = _load_projections_json(proj_path)
        zones = _load_zones_json(zones_path)

        if not zones:
            logger.warning("No zones loaded for %s — skipping.", version)
            continue

        logger.info("Loaded %d projections, %d zones.", len(projections), len(zones))

        # ── Load manifest ────────────────────────────────────────────────────
        manifest = _safe_load_manifest(version)
        missing_bar_count = int(manifest.get("missing_bar_count", 0))
        if missing_bar_count > 0:
            logger.info(
                "Dataset %s has %d missing bar(s) — strict confirmations active.",
                version,
                missing_bar_count,
            )

        # ── Generate signals ──────────────────────────────────────────────────
        signals = generate_signals(
            zones=zones,
            projections=projections,
            dataset_version=version,
            manifest=manifest,
            invalidation_buffer=invalidation_buffer,
            min_score_for_neutral=min_score_neutral,
        )
        logger.info("Generated %d signal candidates.", len(signals))

        # ── Load 6H dataset for confirmation window ───────────────────────────
        df = _safe_load_processed(version)
        confirm_slice = _select_confirmation_window(df, confirm_window) if df is not None else pd.DataFrame()
        logger.info(
            "Confirmation window: %d bars (last %d of dataset).",
            len(confirm_slice),
            confirm_window,
        )

        # ── Run confirmation checks ───────────────────────────────────────────
        all_results: List[ConfirmationResult] = []
        for signal in signals:
            results = run_all_confirmations(
                signal=signal,
                ohlcv_slice=confirm_slice,
                missing_bar_count=missing_bar_count,
            )
            all_results.extend(results)

        # ── Write output files ────────────────────────────────────────────────
        signals_path = output_dir / f"signals_{version}.json"
        confirmations_path = output_dir / f"confirmations_{version}.json"

        signals_path.write_text(
            json.dumps([s.to_dict() for s in signals], indent=2, default=str)
        )
        confirmations_path.write_text(
            json.dumps([r.to_dict() for r in all_results], indent=2, default=str)
        )
        logger.info("Written: %s", signals_path)
        logger.info("Written: %s", confirmations_path)

        # ── Print summary ─────────────────────────────────────────────────────
        _print_summary(version, zones, signals, all_results, missing_bar_count)


def _print_summary(
    version: str,
    zones: List[ConfluenceZone],
    signals: List[SignalCandidate],
    results: List[ConfirmationResult],
    missing_bar_count: int,
) -> None:
    print()
    print("Phase 5 Smoke Run Summary")
    print("=" * 70)
    print(f"  Dataset version : {version}")
    print(f"  Missing bars    : {missing_bar_count}")
    print(f"  Zones loaded    : {len(zones)}")
    print(f"  Signals produced: {len(signals)}")
    print()

    # Bias breakdown
    bias_counts: Dict[str, int] = defaultdict(int)
    for s in signals:
        bias_counts[s.bias] += 1
    print("  Bias breakdown:")
    for bias in ("long", "short", "neutral"):
        print(f"    {bias:<8}: {bias_counts.get(bias, 0)}")
    print()

    # Score bucket breakdown
    bucket_counts: Dict[str, int] = defaultdict(int)
    for s in signals:
        bucket_counts[_score_bucket(s.quality_score)] += 1
    print("  Score bucket breakdown:")
    for bucket in ("0.75–1.00", "0.50–0.75", "0.25–0.50", "0.00–0.25"):
        print(f"    {bucket}: {bucket_counts.get(bucket, 0)}")
    print()

    # Confirmation pass/fail per check name
    if results:
        check_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
        for r in results:
            key = "pass" if r.passed else "fail"
            check_stats[r.check_name][key] += 1
        print("  Confirmation checks summary:")
        for cname, counts in sorted(check_stats.items()):
            total = counts["pass"] + counts["fail"]
            print(
                f"    {cname:<28}: {counts['pass']}/{total} passed"
            )
    else:
        print("  No confirmation results produced.")

    print()
    print("NOTE: Phase 6 backtest engine NOT started.")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 5 smoke run: Signal generation + Confirmation checks."
    )
    p.add_argument(
        "--phase4-dir",
        default=_DEFAULT_PHASE4_DIR,
        help=f"Directory containing Phase 4 zones/projections JSON (default: {_DEFAULT_PHASE4_DIR}).",
    )
    p.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Output directory for Phase 5 reports (default: {_DEFAULT_OUTPUT_DIR}).",
    )
    p.add_argument(
        "--dataset-version",
        default=None,
        help="Run only for this dataset version (default: all found in phase4-dir).",
    )
    p.add_argument(
        "--confirm-window",
        type=int,
        default=_DEFAULT_CONFIRM_WINDOW,
        help=(
            f"Number of recent bars to use as confirmation window "
            f"(default: {_DEFAULT_CONFIRM_WINDOW})."
        ),
    )
    p.add_argument(
        "--min-score-neutral",
        type=float,
        default=_DEFAULT_MIN_SCORE_NEUTRAL,
        help=(
            f"Minimum confluence_score to include neutral-bias signals "
            f"(default: {_DEFAULT_MIN_SCORE_NEUTRAL})."
        ),
    )
    p.add_argument(
        "--invalidation-buffer",
        type=float,
        default=_DEFAULT_INVALIDATION_BUFFER,
        help=(
            f"Extra price buffer applied to invalidation levels "
            f"(default: {_DEFAULT_INVALIDATION_BUFFER})."
        ),
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    main(
        phase4_dir=Path(args.phase4_dir),
        output_dir=Path(args.output_dir),
        target_version=args.dataset_version,
        confirm_window=args.confirm_window,
        min_score_neutral=args.min_score_neutral,
        invalidation_buffer=args.invalidation_buffer,
    )
