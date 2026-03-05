"""
tests/test_ingestion.py

Tests for data/ingestion.py — end-to-end pipeline from raw input to
processed dataset.  Uses synthetic 100-row OHLCV DataFrames injected as mock
raw extractions.  No live MCP connection required.

Coverage:
- raw file is written and readable
- extraction metadata JSON schema completeness
- validation integration (pass case + fail case)
- coordinate system fields present in processed output
- processed Parquet file is readable and matches expected schema
- dataset manifest JSON completeness and format conformance
- dataset version string format conformance
- overwrite=False raises on second run
- overwrite=True replaces existing
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from data.ingestion import run_ingestion_pipeline
from data.validation import DataValidationError


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def synthetic_df() -> pd.DataFrame:
    """100-row clean daily OHLCV DataFrame."""
    n = 100
    dates = pd.date_range(start="2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open":  [1000.0 + i for i in range(n)],
            "high":  [1050.0 + i for i in range(n)],
            "low":   [950.0 + i for i in range(n)],
            "close": [1020.0 + i for i in range(n)],
            "volume": [5000.0 + i * 10 for i in range(n)],
        }
    )


@pytest.fixture()
def pipeline_args(tmp_path: Path) -> dict:
    """Keyword arguments pointing storage paths to tmp_path."""
    return {
        "symbol_tv": "COINBASE:BTCUSD",
        "symbol_path": "COINBASE_BTCUSD",
        "timeframe": "1D",
        "pull_date": "2024-04-10",
        "dataset_version": "proc_COINBASE_BTCUSD_1D_UTC_2024-04-10_v1",
        "atr_windows": [14],
        "raw_base": str(tmp_path / "raw/coinbase_rest"),
        "processed_base": str(tmp_path / "processed"),
        "metadata_base": str(tmp_path / "metadata/extractions"),
        "extraction_method": "coinbase_rest_ccxt",
        "mcp_tool_name": "",
        "user_note": "synthetic test run",
    }

@pytest.fixture()
def synthetic_df_6h() -> pd.DataFrame:
    """100-row clean 6H OHLCV DataFrame."""
    n = 100
    dates = pd.date_range(start="2024-01-01", periods=n, freq="6h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open":  [1000.0 + i for i in range(n)],
            "high":  [1050.0 + i for i in range(n)],
            "low":   [950.0 + i for i in range(n)],
            "close": [1020.0 + i for i in range(n)],
            "volume": [5000.0 + i * 10 for i in range(n)],
        }
    )


@pytest.fixture()
def pipeline_args_6h(tmp_path: Path) -> dict:
    """Keyword arguments for a 6H ingestion pipeline run."""
    return {
        "symbol_tv": "COINBASE:BTCUSD",
        "symbol_path": "COINBASE_BTCUSD",
        "timeframe": "6H",
        "pull_date": "2024-04-10",
        "dataset_version": "proc_COINBASE_BTCUSD_6H_UTC_2024-04-10_v1",
        "atr_windows": [14],
        "raw_base": str(tmp_path / "raw/coinbase_rest"),
        "processed_base": str(tmp_path / "processed"),
        "metadata_base": str(tmp_path / "metadata/extractions"),
        "extraction_method": "coinbase_rest_ccxt",
        "mcp_tool_name": "",
        "user_note": "synthetic 6H test run",
    }



def test_pipeline_returns_expected_keys(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    for key in ("raw_path", "metadata_path", "processed_path",
                "manifest_path", "validation_result", "dataset_version"):
        assert key in result, f"Missing key: {key}"


def test_raw_file_written(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    assert Path(result["raw_path"]).exists()


def test_raw_file_readable_as_csv(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    loaded = pd.read_csv(result["raw_path"])
    assert len(loaded) == 100


def test_extraction_metadata_written(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    assert Path(result["metadata_path"]).exists()


def test_extraction_metadata_schema(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    with open(result["metadata_path"]) as fh:
        meta = json.load(fh)

    required_keys = [
        "extraction_timestamp", "tradingview_symbol", "timeframe",
        "timezone_assumption", "bar_count", "first_bar_timestamp",
        "last_bar_timestamp", "extraction_method", "mcp_server",
        "mcp_tool_name", "raw_file_path", "checksum_sha256",
    ]
    for key in required_keys:
        assert key in meta, f"Metadata missing key: {key}"


def test_extraction_metadata_values(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    with open(result["metadata_path"]) as fh:
        meta = json.load(fh)

    assert meta["tradingview_symbol"] == "COINBASE:BTCUSD"
    assert meta["timeframe"] == "1D"
    assert meta["timezone_assumption"] == "UTC"
    assert meta["bar_count"] == 100
    assert meta["mcp_server"] == "tradingview-mcp"


def test_processed_parquet_written(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    assert Path(result["processed_path"]).exists()


def test_processed_parquet_readable(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    df = pd.read_parquet(result["processed_path"])
    assert len(df) == 100


def test_processed_has_coordinate_system_columns(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    df = pd.read_parquet(result["processed_path"])
    required = [
        "bar_index", "calendar_day_index", "trading_day_index",
        "log_close", "hl_range", "true_range", "atr_14",
    ]
    for col in required:
        assert col in df.columns, f"Processed dataset missing column: {col}"


def test_processed_bar_index_starts_at_zero(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    df = pd.read_parquet(result["processed_path"])
    assert df["bar_index"].iloc[0] == 0


def test_manifest_written(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    assert Path(result["manifest_path"]).exists()


def test_manifest_schema(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    with open(result["manifest_path"]) as fh:
        manifest = json.load(fh)

    required_keys = [
        "dataset_version", "source_raw_file", "source_metadata",
        "validation_passed", "row_count_raw", "row_count_processed",
        "derived_fields", "coordinate_system_version",
        "atr_warmup_rows", "bar_index_epoch_timestamp", "produced_at",
    ]
    for key in required_keys:
        assert key in manifest, f"Manifest missing key: {key}"


def test_manifest_validation_passed_is_true(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    with open(result["manifest_path"]) as fh:
        manifest = json.load(fh)
    assert manifest["validation_passed"] is True


def test_dataset_version_format(synthetic_df, pipeline_args):
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args)
    version = result["dataset_version"]
    pattern = r"^proc_[A-Z]+_[A-Z]+_[A-Z0-9]+_UTC_\d{4}-\d{2}-\d{2}_v\d+$"
    assert re.match(pattern, version), (
        f"Version string '{version}' does not match expected pattern."
    )


# ── Overwrite control ──────────────────────────────────────────────────────


def test_overwrite_false_raises_on_second_run(synthetic_df, pipeline_args):
    run_ingestion_pipeline(synthetic_df, **pipeline_args)
    with pytest.raises(FileExistsError):
        run_ingestion_pipeline(synthetic_df, **pipeline_args, overwrite=False)


def test_overwrite_true_replaces_existing(synthetic_df, pipeline_args):
    run_ingestion_pipeline(synthetic_df, **pipeline_args)
    result = run_ingestion_pipeline(synthetic_df, **pipeline_args, overwrite=True)
    assert Path(result["processed_path"]).exists()


# ── Validation failure ─────────────────────────────────────────────────────


def test_validation_fail_case_raises(synthetic_df, pipeline_args):
    bad_df = synthetic_df.copy()
    bad_df.loc[5, "high"] = 10.0  # high < low → OHLC violation

    with pytest.raises(DataValidationError):
        run_ingestion_pipeline(bad_df, **pipeline_args)


def test_validation_fail_writes_failure_report(synthetic_df, pipeline_args, tmp_path):
    bad_df = synthetic_df.copy()
    bad_df.loc[5, "high"] = 10.0

    try:
        run_ingestion_pipeline(bad_df, **pipeline_args)
    except DataValidationError:
        pass

    meta_dir = Path(pipeline_args["metadata_base"])
    fail_files = list(meta_dir.glob("*_FAILED.json"))
    assert len(fail_files) == 1


# ── 6H timeframe tests (official confirmation TF per 2026-03-05 policy) ───


def test_6h_pipeline_returns_expected_keys(synthetic_df_6h, pipeline_args_6h):
    result = run_ingestion_pipeline(synthetic_df_6h, **pipeline_args_6h)
    for key in ("raw_path", "metadata_path", "processed_path",
                "manifest_path", "validation_result", "dataset_version"):
        assert key in result, f"Missing key: {key}"


def test_6h_raw_file_naming(synthetic_df_6h, pipeline_args_6h):
    result = run_ingestion_pipeline(synthetic_df_6h, **pipeline_args_6h)
    raw_path = str(result["raw_path"])
    assert "6H" in raw_path, f"Expected '6H' in raw path: {raw_path}"
    assert "cbrest_COINBASE_BTCUSD_6H_UTC_2024-04-10.csv" in raw_path


def test_6h_dataset_version_format(synthetic_df_6h, pipeline_args_6h):
    result = run_ingestion_pipeline(synthetic_df_6h, **pipeline_args_6h)
    version = result["dataset_version"]
    assert version == "proc_COINBASE_BTCUSD_6H_UTC_2024-04-10_v1"


def test_6h_processed_parquet_readable(synthetic_df_6h, pipeline_args_6h):
    result = run_ingestion_pipeline(synthetic_df_6h, **pipeline_args_6h)
    df = pd.read_parquet(result["processed_path"])
    assert len(df) == 100
