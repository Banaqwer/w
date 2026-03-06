"""
data/ingest_from_raw.py

Ingest official raw OHLCV data from repo-committed files (no network required).

Reads the latest raw file from data/raw/coinbase_rest/<SYMBOL>/<TIMEFRAME>/
and produces official processed Parquet + manifest for the target timeframes.

When --timeframe 1H is used (the default and expected case), this script
produces all three official MVP datasets by resampling:

    1H raw → resample → 6H processed   (confirmation / execution dataset)
    1H raw → resample → 1D processed   (primary research dataset)
    1D processed → resample → 1W processed   (structural dataset)

Usage (from repo root):
    python -m data.ingest_from_raw \\
        --symbol COINBASE_BTCUSD --timeframe 1H \\
        --pull-date 2026-03-06 --overwrite

References
----------
DECISIONS.md      — 2026-03-04 acquisition method; 2026-03-05 6H policy
ASSUMPTIONS.md    — Assumption 17 (6H as official confirmation TF)
docs/data/data_spec.md — §16–18 (storage, naming, metadata)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "configs" / "default.yaml"

# Pandas resample frequency strings for each canonical project timeframe
_RESAMPLE_FREQ: dict[str, str] = {
    "6H": "6h",
    "1D": "D",
}

# Validation overrides for resampled output datasets.
# Missing-bar check is relaxed because isolated exchange-maintenance gaps
# in the 1H source can produce a single missing 6H bar; the 1D and 1W
# outputs are fully continuous but we keep a small allowance for safety.
_VALIDATION_OVERRIDE_1D: dict = {
    "fail_on_missing_bar": False,
    "max_allowed_missing_bars": 0,
}
_VALIDATION_OVERRIDE_6H: dict = {
    "fail_on_missing_bar": False,
    "max_allowed_missing_bars": 5,
}


# ── Public API ──────────────────────────────────────────────────────────────


def find_raw_file(
    symbol: str,
    timeframe: str,
    pull_date: Optional[str],
    raw_base: str,
) -> Path:
    """Return the path to the latest raw CSV (or parquet) file.

    Parameters
    ----------
    symbol:
        Path-safe symbol string, e.g. ``"COINBASE_BTCUSD"``.
    timeframe:
        Timeframe folder name (case-sensitive on disk), e.g. ``"1H"``.
    pull_date:
        ISO date string used to prefer dated files, e.g. ``"2026-03-06"``.
        If None, the lexicographically latest file is returned.
    raw_base:
        Root of the raw data tree, e.g. ``"data/raw/coinbase_rest"``.

    Raises
    ------
    FileNotFoundError
        If the directory or any matching file does not exist.
    """
    raw_dir = Path(raw_base) / symbol / timeframe
    if not raw_dir.exists():
        raise FileNotFoundError(
            f"Raw directory not found: {raw_dir}\n"
            "Place the raw 1H file at "
            f"data/raw/coinbase_rest/{symbol}/{timeframe}/"
        )

    candidates = sorted(raw_dir.glob("*.csv")) + sorted(raw_dir.glob("*.parquet"))
    if not candidates:
        raise FileNotFoundError(
            f"No raw CSV or parquet files found in {raw_dir}"
        )

    if pull_date:
        dated = [f for f in candidates if pull_date in f.name]
        if dated:
            return dated[-1]  # prefer latest matching pull-date

    return candidates[-1]  # fallback: lexicographically latest


def load_raw_file(path: Path) -> pd.DataFrame:
    """Load a raw OHLCV file (CSV or parquet) and return a normalised DataFrame.

    The returned DataFrame has ``timestamp`` as an ordinary column (UTC-aware
    datetime), sorted ascending, with columns in canonical OHLCV order.
    """
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
        # Some parquet files store timestamp as the index
        if "timestamp" not in df.columns:
            df = df.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    else:
        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Retain only canonical OHLCV columns present in the file
    canonical = ["timestamp", "open", "high", "low", "close", "volume"]
    df = df[[c for c in canonical if c in df.columns]]
    return df


def resample_ohlcv(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample an hourly OHLCV DataFrame to a coarser bar size.

    Parameters
    ----------
    df:
        Input DataFrame with ``timestamp`` as a column (UTC-aware).
    freq:
        Pandas resample frequency string, e.g. ``"6h"`` or ``"D"``.

    Returns
    -------
    Resampled DataFrame with ``timestamp`` as a column; bars with no data
    are dropped.
    """
    ohlcv_agg: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    present_agg = {k: v for k, v in ohlcv_agg.items() if k in df.columns}

    resampled = (
        df.set_index("timestamp")[list(present_agg.keys())]
        .resample(freq, label="left", closed="left")
        .agg(present_agg)
        .dropna(subset=["close"])
        .reset_index()
    )
    return resampled


def ingest_from_raw(
    symbol: str = "COINBASE_BTCUSD",
    timeframe: str = "1H",
    pull_date: Optional[str] = None,
    raw_base: str = "data/raw/coinbase_rest",
    processed_base: str = "data/processed",
    metadata_base: str = "data/metadata/extractions",
    overwrite: bool = False,
    config_path: Optional[Path] = None,
) -> dict:
    """Ingest from repo raw files and produce all official processed datasets.

    When *timeframe* is ``"1H"`` (the expected production case), this function
    produces four outputs:

    * ``6H``  — resampled from 1H; confirmation/execution dataset
    * ``1D``  — resampled from 1H; primary research dataset
    * ``1W``  — resampled from 1D; structural dataset

    Each output is a fully processed Parquet file + manifest JSON written
    under ``data/processed/<dataset_version>/``.

    Parameters
    ----------
    symbol:
        Path-safe symbol, e.g. ``"COINBASE_BTCUSD"``.
    timeframe:
        Source raw timeframe to read (``"1H"`` for the full resample chain).
    pull_date:
        ISO date used for version naming and to select the dated raw file.
        Defaults to today UTC.
    raw_base, processed_base, metadata_base:
        Storage root overrides (useful for testing).
    overwrite:
        If True, overwrite any existing processed datasets.
    config_path:
        Path to ``default.yaml``.  Defaults to ``configs/default.yaml``.

    Returns
    -------
    ``dict`` keyed by timeframe string (``"6H"``, ``"1D"``, ``"1W"``), each
    containing the result dict from :func:`data.ingestion.run_ingestion_pipeline`
    (or :func:`data.ingestion.resample_daily_to_weekly` for 1W).
    """
    from data.ingestion import run_ingestion_pipeline, resample_daily_to_weekly  # noqa: PLC0415

    cfg = _load_config(config_path or _CONFIG_PATH)

    if pull_date is None:
        pull_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    symbol_tv = cfg["market"]["symbol_tv"]
    atr_windows = cfg.get("derived_fields", {}).get("atr_windows", [14])

    # ── Step 1: locate and load 1H raw file ───────────────────────────────
    raw_path = find_raw_file(symbol, timeframe, pull_date, raw_base)
    logger.info("Loading raw %s file: %s", timeframe, raw_path)
    raw_df = load_raw_file(raw_path)
    logger.info("Loaded %d rows (%s → %s)",
                len(raw_df),
                raw_df["timestamp"].iloc[0].date(),
                raw_df["timestamp"].iloc[-1].date())

    results: dict = {}

    if timeframe == "1H":
        # ── Step 2a: resample 1H → 6H ─────────────────────────────────────
        logger.info("Resampling 1H → 6H …")
        df_6h = resample_ohlcv(raw_df, _RESAMPLE_FREQ["6H"])
        version_6h = f"proc_{symbol}_6H_UTC_{pull_date}_v1"
        results["6H"] = run_ingestion_pipeline(
            raw_df=df_6h,
            symbol_tv=symbol_tv,
            symbol_path=symbol,
            timeframe="6H",
            pull_date=pull_date,
            dataset_version=version_6h,
            atr_windows=atr_windows,
            raw_base=raw_base,
            processed_base=processed_base,
            metadata_base=metadata_base,
            extraction_method="resampled_from_1H_repo_raw",
            user_note=f"Resampled from 1H repo raw — Phase 1C — {pull_date}",
            overwrite=overwrite,
            validation_config=_VALIDATION_OVERRIDE_6H,
        )
        logger.info("6H produced: %s  (%d rows)",
                    version_6h, results["6H"]["validation_result"].row_count)

        # ── Step 2b: resample 1H → 1D ─────────────────────────────────────
        logger.info("Resampling 1H → 1D …")
        df_1d = resample_ohlcv(raw_df, _RESAMPLE_FREQ["1D"])
        version_1d = f"proc_{symbol}_1D_UTC_{pull_date}_v1"
        results["1D"] = run_ingestion_pipeline(
            raw_df=df_1d,
            symbol_tv=symbol_tv,
            symbol_path=symbol,
            timeframe="1D",
            pull_date=pull_date,
            dataset_version=version_1d,
            atr_windows=atr_windows,
            raw_base=raw_base,
            processed_base=processed_base,
            metadata_base=metadata_base,
            extraction_method="resampled_from_1H_repo_raw",
            user_note=f"Resampled from 1H repo raw — Phase 1C — {pull_date}",
            overwrite=overwrite,
            validation_config=_VALIDATION_OVERRIDE_1D,
        )
        logger.info("1D produced: %s  (%d rows)",
                    version_1d, results["1D"]["validation_result"].row_count)

        # ── Step 2c: resample 1D → 1W ─────────────────────────────────────
        logger.info("Resampling 1D → 1W …")
        version_1w = f"proc_{symbol}_1W_UTC_{pull_date}_v1"
        results["1W"] = resample_daily_to_weekly(
            daily_version=version_1d,
            pull_date=pull_date,
            weekly_version=version_1w,
            processed_base=processed_base,
            metadata_base=metadata_base,
            symbol_path=symbol,
            overwrite=overwrite,
        )
        logger.info("1W produced: %s  (%d rows)",
                    version_1w, results["1W"]["row_count"])

    else:
        # Direct ingestion for a single non-1H timeframe
        version = f"proc_{symbol}_{timeframe}_UTC_{pull_date}_v1"
        results[timeframe] = run_ingestion_pipeline(
            raw_df=raw_df,
            symbol_tv=symbol_tv,
            symbol_path=symbol,
            timeframe=timeframe,
            pull_date=pull_date,
            dataset_version=version,
            atr_windows=atr_windows,
            raw_base=raw_base,
            processed_base=processed_base,
            metadata_base=metadata_base,
            extraction_method="repo_raw_file",
            user_note=f"Ingested from repo raw — Phase 1C — {pull_date}",
            overwrite=overwrite,
        )

    return results


# ── Internal helpers ────────────────────────────────────────────────────────


def _load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ── CLI entry point ─────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Ingest official raw OHLCV data from repo-committed files and "
            "produce processed Parquet datasets + manifests. No network required."
        )
    )
    p.add_argument(
        "--symbol",
        default="COINBASE_BTCUSD",
        help="Path-safe symbol (default: COINBASE_BTCUSD).",
    )
    p.add_argument(
        "--timeframe",
        default="1H",
        help=(
            "Source raw timeframe to read (default: 1H). "
            "When 1H, also produces resampled 6H, 1D, and 1W datasets."
        ),
    )
    p.add_argument(
        "--pull-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Pull date for version naming and file selection (default: today UTC).",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing processed datasets.",
    )
    p.add_argument(
        "--raw-base",
        default="data/raw/coinbase_rest",
        metavar="DIR",
        help="Root of raw data tree (default: data/raw/coinbase_rest).",
    )
    p.add_argument(
        "--processed-base",
        default="data/processed",
        metavar="DIR",
        help="Root of processed data tree (default: data/processed).",
    )
    p.add_argument(
        "--metadata-base",
        default="data/metadata/extractions",
        metavar="DIR",
        help="Root of extraction metadata (default: data/metadata/extractions).",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        results = ingest_from_raw(
            symbol=args.symbol,
            timeframe=args.timeframe,
            pull_date=args.pull_date,
            raw_base=args.raw_base,
            processed_base=args.processed_base,
            metadata_base=args.metadata_base,
            overwrite=args.overwrite,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Ingestion failed: %s", exc)
        sys.exit(1)

    print("=== Phase 1C ingestion complete ===")
    for tf, result in results.items():
        if tf == "1W":
            print(f"  {tf}: {result['dataset_version']}  rows={result['row_count']}")
            print(f"       processed: {result['processed_path']}")
            print(f"       manifest:  {result['manifest_path']}")
        else:
            print(f"  {tf}: {result['dataset_version']}  rows={result['validation_result'].row_count}")
            print(f"       processed: {result['processed_path']}")
            print(f"       manifest:  {result['manifest_path']}")


if __name__ == "__main__":
    main()
