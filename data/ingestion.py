"""
data/ingestion.py

Raw-to-processed ingestion pipeline.

Steps (as defined in docs/phase0_builder_output.md §Section 4):
  1. Accept a raw OHLCV DataFrame (from MCP extraction or CSV load).
  2. Write the raw file (or skip if already saved).
  3. Write extraction metadata JSON sidecar.
  4. Run validation (data/validation.py).
  5. Compute all derived fields (core/coordinate_system.py).
  6. Write the processed Parquet file.
  7. Write the dataset manifest JSON.

All path conventions follow DECISIONS.md and data_spec.md §16–17.

References
----------
docs/phase0_builder_output.md — Section 4 (MCP extraction workflow)
docs/data/data_spec.md        — §16 (storage paths), §17 (naming), §18 (metadata)
DECISIONS.md                  — data storage policy
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.coordinate_system import build_coordinate_system
from data.validation import DataValidationError, ValidationResult, validate_dataset

logger = logging.getLogger(__name__)

# ── Public API ─────────────────────────────────────────────────────────────


def run_ingestion_pipeline(
    raw_df: pd.DataFrame,
    symbol_tv: str,
    symbol_path: str,
    timeframe: str,
    pull_date: str,
    dataset_version: str,
    atr_windows: Optional[List[int]] = None,
    raw_base: str = "data/raw/coinbase_rest",
    processed_base: str = "data/processed",
    metadata_base: str = "data/metadata/extractions",
    validation_config: Optional[dict] = None,
    extraction_method: str = "coinbase_rest_ccxt",
    mcp_tool_name: str = "",
    user_note: str = "",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Run the full raw → processed ingestion pipeline.

    Parameters
    ----------
    raw_df:
        DataFrame from MCP extraction.  Must have at minimum:
        ``timestamp``, ``open``, ``high``, ``low``, ``close``.
    symbol_tv:
        TradingView symbol string (e.g. ``"COINBASE:BTCUSD"``).
    symbol_path:
        Path-safe symbol (e.g. ``"COINBASE_BTCUSD"``).
    timeframe:
        Timeframe string (e.g. ``"1D"``, ``"6H"``).
    pull_date:
        ISO date of extraction (e.g. ``"2026-03-03"``).
    dataset_version:
        Processed dataset version string
        (e.g. ``"proc_COINBASE_BTCUSD_1D_UTC_2026-03-03_v1"``).
    atr_windows:
        ATR windows to compute.  Defaults to ``[14]``.
    raw_base, processed_base, metadata_base:
        Override default storage roots.
    validation_config:
        Override validation settings (see ``data/validation.py``).
    extraction_method, mcp_tool_name, user_note:
        Fields written into the extraction metadata JSON.
    overwrite:
        If False (default), raise if the processed dataset already exists.

    Returns
    -------
    ``dict`` with keys:
    - ``raw_path``: Path of saved raw CSV
    - ``metadata_path``: Path of extraction metadata JSON
    - ``processed_path``: Path of processed Parquet file
    - ``manifest_path``: Path of dataset manifest JSON
    - ``validation_result``: :class:`ValidationResult` object
    - ``dataset_version``: version string passed in
    """
    if atr_windows is None:
        atr_windows = [14]

    extraction_ts = datetime.now(timezone.utc)

    # ── Step 1: Normalise timestamps ──────────────────────────────────────
    df = _normalise_input(raw_df)

    # ── Step 2: Save raw file ─────────────────────────────────────────────
    raw_path = _write_raw(df, symbol_path, timeframe, pull_date, raw_base)

    # ── Step 3: Compute checksum ──────────────────────────────────────────
    checksum = _sha256_file(raw_path)

    # ── Step 4: Write extraction metadata ─────────────────────────────────
    metadata_path = _write_extraction_metadata(
        df=df,
        symbol_tv=symbol_tv,
        symbol_path=symbol_path,
        timeframe=timeframe,
        pull_date=pull_date,
        extraction_ts=extraction_ts,
        extraction_method=extraction_method,
        mcp_tool_name=mcp_tool_name,
        raw_file_path=str(raw_path),
        checksum=checksum,
        user_note=user_note,
        metadata_base=metadata_base,
    )

    # ── Step 5: Validate ──────────────────────────────────────────────────
    validation_result = _run_validation(
        df=df,
        symbol_tv=symbol_tv,
        timeframe=timeframe,
        extraction_ts=extraction_ts,
        validation_config=validation_config,
        metadata_base=metadata_base,
        symbol_path=symbol_path,
        pull_date=pull_date,
    )

    # ── Step 6: Compute derived fields ────────────────────────────────────
    df = build_coordinate_system(df, atr_windows)

    # ── Step 7: Write processed Parquet ───────────────────────────────────
    processed_path = _write_processed(
        df=df,
        dataset_version=dataset_version,
        processed_base=processed_base,
        overwrite=overwrite,
    )

    # ── Step 8: Write manifest ────────────────────────────────────────────
    atr_warmup_rows = max(atr_windows) if atr_windows else 14
    derived_fields = _list_derived_fields(df, atr_windows)

    # Extract missing-bar info from validation result
    missing_bar_count = 0
    missing_bar_details: List[str] = []
    if validation_result.missing_bars:
        missing_bar_details = list(validation_result.missing_bars)
        missing_bar_count = sum(
            int(m.split("~")[1].split(" ")[0]) for m in missing_bar_details
        )

    # Determine missing-bar policy description
    _val_defaults = {
        "fail_on_missing_bar": True,
        "max_allowed_missing_bars": 0,
    }
    if validation_config:
        _val_defaults.update(validation_config)
    if _val_defaults["fail_on_missing_bar"] and _val_defaults["max_allowed_missing_bars"] == 0:
        missing_bar_policy = "strict"
    else:
        missing_bar_policy = (
            f"relaxed (fail_on_missing_bar={_val_defaults['fail_on_missing_bar']}, "
            f"max_allowed={_val_defaults['max_allowed_missing_bars']})"
        )

    manifest_path = _write_manifest(
        dataset_version=dataset_version,
        raw_file_path=str(raw_path),
        metadata_file_path=str(metadata_path),
        row_count_raw=len(raw_df),
        row_count_processed=len(df),
        derived_fields=derived_fields,
        atr_warmup_rows=atr_warmup_rows,
        epoch_timestamp=str(df["timestamp"].iloc[0]),
        produced_at=extraction_ts,
        processed_base=processed_base,
        start_timestamp=str(df["timestamp"].iloc[0]),
        end_timestamp=str(df["timestamp"].iloc[-1]),
        missing_bar_count=missing_bar_count,
        missing_bar_policy=missing_bar_policy,
        missing_bar_details=missing_bar_details,
    )

    logger.info(
        "Ingestion complete: version=%s  rows=%d  processed=%s",
        dataset_version,
        len(df),
        processed_path,
    )

    return {
        "raw_path": raw_path,
        "metadata_path": metadata_path,
        "processed_path": processed_path,
        "manifest_path": manifest_path,
        "validation_result": validation_result,
        "dataset_version": dataset_version,
    }


def resample_daily_to_weekly(
    daily_version: str,
    pull_date: str,
    weekly_version: Optional[str] = None,
    processed_base: str = "data/processed",
    metadata_base: str = "data/metadata/extractions",
    symbol_path: str = "COINBASE_BTCUSD",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Produce a weekly OHLCV dataset by resampling a processed daily dataset.

    Per ``configs/default.yaml`` (``acquisition.method_weekly: resample_from_1D``),
    weekly bars are derived from the daily processed Parquet, not pulled directly
    from the exchange.  The weekly bar boundary is Monday 00:00 UTC.

    Parameters
    ----------
    daily_version:
        Version string for the existing daily processed dataset, e.g.
        ``"proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1"``.
    pull_date:
        ISO date string (e.g. ``"2026-03-04"``); used for file naming.
    weekly_version:
        Version string for the weekly output dataset.  Defaults to deriving
        from *daily_version* by replacing ``_1D_`` with ``_1W_``.
    processed_base:
        Root directory for processed datasets.
    metadata_base:
        Root directory for extraction metadata.
    symbol_path:
        Path-safe symbol string.
    overwrite:
        Whether to overwrite an existing weekly processed dataset.

    Returns
    -------
    Dict with keys: ``processed_path``, ``manifest_path``, ``dataset_version``,
    ``row_count``.
    """
    produced_at = datetime.now(timezone.utc)

    # Load daily processed Parquet
    daily_dir = Path(processed_base) / daily_version
    daily_parquet = daily_dir / f"{daily_version}.parquet"
    if not daily_parquet.exists():
        raise FileNotFoundError(
            f"Daily processed dataset not found: {daily_parquet}"
        )

    daily_df = pd.read_parquet(daily_parquet)

    # Ensure timestamp is a UTC DatetimeIndex for resampling
    if "timestamp" in daily_df.columns:
        daily_df = daily_df.set_index("timestamp")
    daily_df.index = pd.to_datetime(daily_df.index, utc=True)

    # Weekly OHLCV resampling — boundary: Monday 00:00 UTC (label=left, closed=left)
    ohlcv_agg: Dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    weekly_df = (
        daily_df[list(ohlcv_agg.keys())]
        .resample("W-MON", label="left", closed="left")
        .agg(ohlcv_agg)
        .dropna(subset=["close"])
        .reset_index()
    )
    weekly_df = weekly_df.rename(columns={"index": "timestamp"})

    # Derive weekly version string
    if weekly_version is None:
        weekly_version = daily_version.replace("_1D_", "_1W_")

    # Write processed weekly Parquet
    weekly_dir = Path(processed_base) / weekly_version
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly_parquet = weekly_dir / f"{weekly_version}.parquet"
    if weekly_parquet.exists() and not overwrite:
        raise FileExistsError(
            f"Weekly dataset already exists: {weekly_parquet}. "
            "Pass overwrite=True to replace."
        )
    weekly_df.to_parquet(weekly_parquet, index=False)
    logger.info("Weekly Parquet written: %s (%d rows)", weekly_parquet, len(weekly_df))

    # Write weekly manifest
    w_start = str(weekly_df["timestamp"].iloc[0]) if len(weekly_df) else ""
    w_end = str(weekly_df["timestamp"].iloc[-1]) if len(weekly_df) else ""
    manifest_path = _write_manifest(
        dataset_version=weekly_version,
        raw_file_path=str(daily_parquet),
        metadata_file_path="resampled_from_daily",
        row_count_raw=len(daily_df),
        row_count_processed=len(weekly_df),
        derived_fields=[],
        atr_warmup_rows=0,
        epoch_timestamp=w_start,
        produced_at=produced_at,
        processed_base=processed_base,
        start_timestamp=w_start,
        end_timestamp=w_end,
        missing_bar_count=0,
        missing_bar_policy="not_applicable (resampled from daily)",
    )

    logger.info(
        "Weekly resample complete: version=%s  rows=%d",
        weekly_version,
        len(weekly_df),
    )

    return {
        "processed_path": weekly_parquet,
        "manifest_path": manifest_path,
        "dataset_version": weekly_version,
        "row_count": len(weekly_df),
    }


# ── Internal helpers ───────────────────────────────────────────────────────


def _normalise_input(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with timestamp normalised to UTC datetime64[ns]."""
    df = df.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _write_raw(
    df: pd.DataFrame,
    symbol_path: str,
    timeframe: str,
    pull_date: str,
    raw_base: str,
) -> Path:
    raw_dir = Path(raw_base) / symbol_path / timeframe
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cbrest_{symbol_path}_{timeframe}_UTC_{pull_date}.csv"
    raw_path = raw_dir / filename
    df.to_csv(raw_path, index=False)
    logger.debug("Raw file written: %s (%d rows)", raw_path, len(df))
    return raw_path


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _write_extraction_metadata(
    df: pd.DataFrame,
    symbol_tv: str,
    symbol_path: str,
    timeframe: str,
    pull_date: str,
    extraction_ts: datetime,
    extraction_method: str,
    mcp_tool_name: str,
    raw_file_path: str,
    checksum: str,
    user_note: str,
    metadata_base: str,
) -> Path:
    meta_dir = Path(metadata_base)
    meta_dir.mkdir(parents=True, exist_ok=True)

    filename = f"cbrest_{symbol_path}_{timeframe}_UTC_{pull_date}.json"
    meta_path = meta_dir / filename

    first_ts = str(df["timestamp"].iloc[0]) if len(df) else ""
    last_ts = str(df["timestamp"].iloc[-1]) if len(df) else ""

    metadata = {
        "extraction_timestamp": extraction_ts.isoformat(),
        "tradingview_symbol": symbol_tv,
        "timeframe": timeframe,
        "timezone_assumption": "UTC",
        "bar_count": len(df),
        "first_bar_timestamp": first_ts,
        "last_bar_timestamp": last_ts,
        "extraction_method": extraction_method,
        "mcp_server": "tradingview-mcp",
        "mcp_tool_name": mcp_tool_name,
        "raw_file_path": raw_file_path,
        "checksum_sha256": checksum,
        "user_note": user_note,
    }

    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    logger.debug("Extraction metadata written: %s", meta_path)
    return meta_path


def _run_validation(
    df: pd.DataFrame,
    symbol_tv: str,
    timeframe: str,
    extraction_ts: datetime,
    validation_config: Optional[dict],
    metadata_base: str,
    symbol_path: str,
    pull_date: str,
) -> ValidationResult:
    try:
        result = validate_dataset(
            df,
            symbol=symbol_tv,
            timeframe=timeframe,
            extraction_timestamp=pd.Timestamp(extraction_ts),
            config=validation_config,
        )
        logger.info("Validation passed: %s rows", result.row_count)
        return result
    except DataValidationError as exc:
        _write_failure_report(
            error=str(exc),
            symbol_path=symbol_path,
            timeframe=timeframe,
            pull_date=pull_date,
            metadata_base=metadata_base,
        )
        raise


def _write_failure_report(
    error: str,
    symbol_path: str,
    timeframe: str,
    pull_date: str,
    metadata_base: str,
) -> None:
    meta_dir = Path(metadata_base)
    meta_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cbrest_{symbol_path}_{timeframe}_UTC_{pull_date}_FAILED.json"
    fail_path = meta_dir / filename
    report = {
        "status": "FAILED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
    with open(fail_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    logger.error("Validation failure report written: %s", fail_path)


def _write_processed(
    df: pd.DataFrame,
    dataset_version: str,
    processed_base: str,
    overwrite: bool,
) -> Path:
    version_dir = Path(processed_base) / dataset_version
    version_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = version_dir / f"{dataset_version}.parquet"

    if parquet_path.exists() and not overwrite:
        raise FileExistsError(
            f"Processed dataset already exists: {parquet_path}. "
            "Pass overwrite=True to replace."
        )

    table = pa.Table.from_pandas(df)
    pq.write_table(table, parquet_path)
    logger.debug("Processed Parquet written: %s (%d rows)", parquet_path, len(df))
    return parquet_path


def _list_derived_fields(df: pd.DataFrame, atr_windows: List[int]) -> List[str]:
    base = ["bar_index", "calendar_day_index", "trading_day_index",
            "log_close", "hl_range", "true_range"]
    atr_cols = [f"atr_{w}" for w in atr_windows if f"atr_{w}" in df.columns]
    return base + atr_cols


def _write_manifest(
    dataset_version: str,
    raw_file_path: str,
    metadata_file_path: str,
    row_count_raw: int,
    row_count_processed: int,
    derived_fields: List[str],
    atr_warmup_rows: int,
    epoch_timestamp: str,
    produced_at: datetime,
    processed_base: str,
    start_timestamp: str = "",
    end_timestamp: str = "",
    missing_bar_count: int = 0,
    missing_bar_policy: str = "strict",
    missing_bar_details: Optional[List[str]] = None,
) -> Path:
    version_dir = Path(processed_base) / dataset_version
    manifest_path = version_dir / f"{dataset_version}_manifest.json"

    manifest: Dict[str, Any] = {
        "dataset_version": dataset_version,
        "source_raw_file": raw_file_path,
        "source_metadata": metadata_file_path,
        "validation_passed": True,
        "row_count_raw": row_count_raw,
        "row_count_processed": row_count_processed,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "derived_fields": derived_fields,
        "coordinate_system_version": "v1",
        "atr_warmup_rows": atr_warmup_rows,
        "bar_index_epoch_timestamp": epoch_timestamp,
        "missing_bar_count": missing_bar_count,
        "missing_bar_policy": missing_bar_policy,
        "missing_bar_details": missing_bar_details or [],
        "produced_at": produced_at.isoformat(),
    }

    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    logger.debug("Manifest written: %s", manifest_path)
    return manifest_path
