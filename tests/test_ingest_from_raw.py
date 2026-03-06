"""
tests/test_ingest_from_raw.py

Tests for data/ingest_from_raw.py — Phase 1C ingestion from repo raw files.

Coverage:
- find_raw_file locates CSV and parquet files correctly
- find_raw_file raises FileNotFoundError for missing directory
- find_raw_file raises FileNotFoundError for empty directory
- find_raw_file prefers pull-date-matching file when multiple exist
- load_raw_file handles CSV with timestamp column
- load_raw_file handles parquet with timestamp as index
- load_raw_file returns canonical column order
- resample_ohlcv produces correct bar counts for 6H and 1D
- resample_ohlcv 1D bars are UTC-day-aligned (00:00 UTC)
- resample_ohlcv 6H bars are aligned to 00:00/06:00/12:00/18:00 UTC
- ingest_from_raw (1H) produces 6H, 1D, 1W results
- ingest_from_raw (1H) all three processed Parquet files exist
- ingest_from_raw (1H) all three manifest files exist and pass validation
- ingest_from_raw (1H) dataset version strings match naming convention
- ingest_from_raw overwrite=False raises on second run
- ingest_from_raw overwrite=True replaces existing
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from data.ingest_from_raw import (
    find_raw_file,
    ingest_from_raw,
    load_raw_file,
    resample_ohlcv,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def hourly_df() -> pd.DataFrame:
    """Synthetic clean 24-hour (168 × 24 = 4032 bars) 1H OHLCV DataFrame."""
    n = 168 * 24  # 168 days × 24 h = 4032 bars
    dates = pd.date_range(start="2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open":  [1000.0 + i * 0.1 for i in range(n)],
            "high":  [1050.0 + i * 0.1 for i in range(n)],
            "low":   [950.0 + i * 0.1 for i in range(n)],
            "close": [1020.0 + i * 0.1 for i in range(n)],
            "volume": [100.0 + i * 0.01 for i in range(n)],
        }
    )


@pytest.fixture()
def raw_csv_file(tmp_path: Path, hourly_df: pd.DataFrame) -> Path:
    """Write a synthetic 1H CSV into a canonical raw directory."""
    raw_dir = tmp_path / "raw" / "COINBASE_BTCUSD" / "1H"
    raw_dir.mkdir(parents=True)
    csv_path = raw_dir / "cbrest_COINBASE_BTCUSD_1H_UTC_2024-06-01.csv"
    hourly_df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture()
def raw_parquet_file(tmp_path: Path, hourly_df: pd.DataFrame) -> Path:
    """Write a synthetic 1H parquet (timestamp as index) into raw directory."""
    raw_dir = tmp_path / "raw" / "COINBASE_BTCUSD" / "1H"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pq_path = raw_dir / "cbrest_COINBASE_BTCUSD_1H_UTC_2024-06-02.parquet"
    df_idx = hourly_df.set_index("timestamp")
    df_idx.to_parquet(pq_path)
    return pq_path


# ── find_raw_file ──────────────────────────────────────────────────────────


def test_find_raw_file_returns_csv(tmp_path, raw_csv_file):
    raw_base = str(tmp_path / "raw")
    result = find_raw_file("COINBASE_BTCUSD", "1H", "2024-06-01", raw_base)
    assert result == raw_csv_file


def test_find_raw_file_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Raw directory not found"):
        find_raw_file("COINBASE_BTCUSD", "1H", None, str(tmp_path / "raw"))


def test_find_raw_file_empty_directory_raises(tmp_path):
    raw_dir = tmp_path / "raw" / "COINBASE_BTCUSD" / "1H"
    raw_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="No raw CSV or parquet files found"):
        find_raw_file("COINBASE_BTCUSD", "1H", None, str(tmp_path / "raw"))


def test_find_raw_file_prefers_pull_date_match(tmp_path, hourly_df):
    raw_dir = tmp_path / "raw" / "COINBASE_BTCUSD" / "1H"
    raw_dir.mkdir(parents=True)
    for date in ("2024-05-01", "2024-06-01", "2024-07-01"):
        p = raw_dir / f"cbrest_COINBASE_BTCUSD_1H_UTC_{date}.csv"
        hourly_df.to_csv(p, index=False)
    result = find_raw_file("COINBASE_BTCUSD", "1H", "2024-06-01", str(tmp_path / "raw"))
    assert "2024-06-01" in result.name


def test_find_raw_file_latest_fallback(tmp_path, hourly_df):
    raw_dir = tmp_path / "raw" / "COINBASE_BTCUSD" / "1H"
    raw_dir.mkdir(parents=True)
    for date in ("2024-05-01", "2024-06-01"):
        p = raw_dir / f"cbrest_COINBASE_BTCUSD_1H_UTC_{date}.csv"
        hourly_df.to_csv(p, index=False)
    # No pull_date match — returns lexicographically latest CSV
    result = find_raw_file("COINBASE_BTCUSD", "1H", None, str(tmp_path / "raw"))
    assert "2024-06-01" in result.name


# ── load_raw_file ──────────────────────────────────────────────────────────


def test_load_raw_file_csv(raw_csv_file, hourly_df):
    df = load_raw_file(raw_csv_file)
    assert len(df) == len(hourly_df)
    assert "timestamp" in df.columns
    assert df["timestamp"].dtype.tz is not None  # UTC-aware


def test_load_raw_file_parquet_with_index(raw_parquet_file, hourly_df):
    df = load_raw_file(raw_parquet_file)
    assert len(df) == len(hourly_df)
    assert "timestamp" in df.columns
    assert df["timestamp"].dtype.tz is not None


def test_load_raw_file_canonical_column_order(raw_csv_file):
    df = load_raw_file(raw_csv_file)
    assert list(df.columns[:6]) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_load_raw_file_sorted_ascending(raw_csv_file, hourly_df):
    # Shuffle the CSV then reload
    shuffled = hourly_df.sample(frac=1, random_state=0)
    shuffled.to_csv(raw_csv_file, index=False)
    df = load_raw_file(raw_csv_file)
    assert df["timestamp"].is_monotonic_increasing


# ── resample_ohlcv ─────────────────────────────────────────────────────────


def test_resample_ohlcv_1d_row_count(hourly_df):
    df_1d = resample_ohlcv(hourly_df, "D")
    # 168 complete UTC days → 168 bars
    assert len(df_1d) == 168


def test_resample_ohlcv_1d_aligned_midnight(hourly_df):
    df_1d = resample_ohlcv(hourly_df, "D")
    hours = df_1d["timestamp"].dt.hour.unique()
    assert list(hours) == [0], f"1D bars not at 00:00 UTC: {hours}"


def test_resample_ohlcv_6h_row_count(hourly_df):
    df_6h = resample_ohlcv(hourly_df, "6h")
    # 168 days × 4 bars/day = 672 bars
    assert len(df_6h) == 672


def test_resample_ohlcv_6h_aligned_to_grid(hourly_df):
    df_6h = resample_ohlcv(hourly_df, "6h")
    hours = sorted(df_6h["timestamp"].dt.hour.unique().tolist())
    assert hours == [0, 6, 12, 18], f"6H bars not on 6h grid: {hours}"


def test_resample_ohlcv_high_gte_low(hourly_df):
    df_1d = resample_ohlcv(hourly_df, "D")
    assert (df_1d["high"] >= df_1d["low"]).all()


def test_resample_ohlcv_volume_sum(hourly_df):
    df_1d = resample_ohlcv(hourly_df, "D")
    # Each day aggregates 24 hourly volumes
    expected_first_day_vol = hourly_df["volume"].iloc[:24].sum()
    assert abs(df_1d["volume"].iloc[0] - expected_first_day_vol) < 1e-6


# ── ingest_from_raw (integration) ─────────────────────────────────────────


@pytest.fixture()
def ingest_args(tmp_path: Path, raw_csv_file: Path) -> dict:
    """Minimal kwargs for ingest_from_raw pointing at tmp_path storage."""
    return {
        "symbol": "COINBASE_BTCUSD",
        "timeframe": "1H",
        "pull_date": "2024-06-01",
        "raw_base": str(raw_csv_file.parent.parent.parent),
        "processed_base": str(tmp_path / "processed"),
        "metadata_base": str(tmp_path / "metadata"),
        "overwrite": False,
    }


def test_ingest_from_raw_returns_three_timeframes(ingest_args):
    results = ingest_from_raw(**ingest_args)
    assert set(results.keys()) == {"6H", "1D", "1W"}


def test_ingest_from_raw_processed_parquets_exist(ingest_args):
    results = ingest_from_raw(**ingest_args)
    for tf in ("6H", "1D"):
        path = Path(results[tf]["processed_path"])
        assert path.exists(), f"Processed parquet missing for {tf}: {path}"
    path_1w = Path(results["1W"]["processed_path"])
    assert path_1w.exists(), f"Processed parquet missing for 1W: {path_1w}"


def test_ingest_from_raw_manifests_exist_and_pass(ingest_args):
    results = ingest_from_raw(**ingest_args)
    for tf in ("6H", "1D"):
        mfst_path = Path(results[tf]["manifest_path"])
        assert mfst_path.exists()
        with open(mfst_path) as fh:
            mfst = json.load(fh)
        assert mfst["validation_passed"] is True, f"{tf} manifest validation_passed is False"
    mfst_path_1w = Path(results["1W"]["manifest_path"])
    assert mfst_path_1w.exists()
    with open(mfst_path_1w) as fh:
        mfst_1w = json.load(fh)
    assert mfst_1w["validation_passed"] is True


def test_ingest_from_raw_manifests_have_start_end_timestamps(ingest_args):
    results = ingest_from_raw(**ingest_args)
    for tf in ("6H", "1D", "1W"):
        if tf == "1W":
            mfst_path = Path(results[tf]["manifest_path"])
        else:
            mfst_path = Path(results[tf]["manifest_path"])
        with open(mfst_path) as fh:
            mfst = json.load(fh)
        assert "start_timestamp" in mfst, f"{tf} manifest missing start_timestamp"
        assert "end_timestamp" in mfst, f"{tf} manifest missing end_timestamp"
        assert mfst["start_timestamp"] != "", f"{tf} manifest start_timestamp is empty"
        assert mfst["end_timestamp"] != "", f"{tf} manifest end_timestamp is empty"


def test_ingest_from_raw_manifests_have_missing_bar_fields(ingest_args):
    results = ingest_from_raw(**ingest_args)
    for tf in ("6H", "1D", "1W"):
        if tf == "1W":
            mfst_path = Path(results[tf]["manifest_path"])
        else:
            mfst_path = Path(results[tf]["manifest_path"])
        with open(mfst_path) as fh:
            mfst = json.load(fh)
        assert "missing_bar_count" in mfst, f"{tf} manifest missing missing_bar_count"
        assert "missing_bar_policy" in mfst, f"{tf} manifest missing missing_bar_policy"
        assert "missing_bar_details" in mfst, f"{tf} manifest missing missing_bar_details"
        assert isinstance(mfst["missing_bar_count"], int), f"{tf} missing_bar_count not int"
        assert isinstance(mfst["missing_bar_details"], list), f"{tf} missing_bar_details not list"


def test_ingest_from_raw_version_string_format(ingest_args):
    results = ingest_from_raw(**ingest_args)
    pattern = r"^proc_[A-Z]+_[A-Z]+_[A-Z0-9]+_UTC_\d{4}-\d{2}-\d{2}_v\d+$"
    for tf in ("6H", "1D"):
        version = results[tf]["dataset_version"]
        assert re.match(pattern, version), (
            f"{tf} version '{version}' does not match naming convention"
        )
    version_1w = results["1W"]["dataset_version"]
    assert re.match(pattern, version_1w), (
        f"1W version '{version_1w}' does not match naming convention"
    )


def test_ingest_from_raw_1d_row_count(ingest_args):
    results = ingest_from_raw(**ingest_args)
    df = pd.read_parquet(results["1D"]["processed_path"])
    assert len(df) == 168  # 168 synthetic days


def test_ingest_from_raw_6h_row_count(ingest_args):
    results = ingest_from_raw(**ingest_args)
    df = pd.read_parquet(results["6H"]["processed_path"])
    assert len(df) == 672  # 168 days × 4 bars/day


def test_ingest_from_raw_1w_row_count_positive(ingest_args):
    results = ingest_from_raw(**ingest_args)
    assert results["1W"]["row_count"] > 0


def test_ingest_from_raw_1d_has_derived_fields(ingest_args):
    results = ingest_from_raw(**ingest_args)
    df = pd.read_parquet(results["1D"]["processed_path"])
    for col in ("bar_index", "log_close", "hl_range", "true_range", "atr_14"):
        assert col in df.columns, f"1D processed missing derived field: {col}"


def test_ingest_from_raw_overwrite_false_raises(ingest_args):
    ingest_from_raw(**ingest_args)
    no_overwrite_args = {**ingest_args, "overwrite": False}
    with pytest.raises(FileExistsError):
        ingest_from_raw(**no_overwrite_args)


def test_ingest_from_raw_overwrite_true_replaces(ingest_args):
    ingest_from_raw(**ingest_args)
    overwrite_args = {**ingest_args, "overwrite": True}
    results = ingest_from_raw(**overwrite_args)
    assert Path(results["1D"]["processed_path"]).exists()
