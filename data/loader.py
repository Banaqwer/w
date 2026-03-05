"""
data/loader.py

Load raw and processed datasets, extraction metadata, and dataset manifests
by version string, symbol, and timeframe.

All path conventions follow DECISIONS.md §data-storage and data_spec.md §16–17.

References
----------
DECISIONS.md — data storage and naming conventions
docs/data/data_spec.md — §16 (storage paths), §17 (version naming)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Public API ─────────────────────────────────────────────────────────────


def load_processed(
    dataset_version: str,
    base_path: str = "data/processed",
) -> pd.DataFrame:
    """Load a processed dataset by its version string.

    Parameters
    ----------
    dataset_version:
        Version string such as ``"proc_COINBASE_BTCUSD_1D_UTC_2026-03-03_v1"``.
    base_path:
        Root directory for processed datasets (default: ``"data/processed"``).

    Returns
    -------
    DataFrame loaded from the versioned Parquet file.

    Raises
    ------
    FileNotFoundError
        If the versioned directory or Parquet file does not exist.
    """
    version_dir = Path(base_path) / dataset_version
    parquet_path = version_dir / f"{dataset_version}.parquet"

    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Processed dataset not found: {parquet_path}\n"
            f"Expected version directory: {version_dir}"
        )

    logger.info("Loading processed dataset: %s", parquet_path)
    df = pd.read_parquet(parquet_path)
    return df


def load_manifest(
    dataset_version: str,
    base_path: str = "data/processed",
) -> dict:
    """Load the JSON manifest for a processed dataset version.

    Parameters
    ----------
    dataset_version:
        Version string such as ``"proc_COINBASE_BTCUSD_1D_UTC_2026-03-03_v1"``.
    base_path:
        Root directory for processed datasets.

    Returns
    -------
    Parsed manifest as a dict.

    Raises
    ------
    FileNotFoundError
        If the manifest JSON file does not exist.
    """
    version_dir = Path(base_path) / dataset_version
    manifest_path = version_dir / f"{dataset_version}_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    logger.info("Loading manifest: %s", manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_raw(
    symbol_path: str,
    timeframe: str,
    pull_date: str,
    base_path: str = "data/raw/coinbase_rest",
    extension: str = "csv",
) -> pd.DataFrame:
    """Load a raw Coinbase REST extraction file.

    Parameters
    ----------
    symbol_path:
        Path-sanitised symbol (e.g. ``"COINBASE_BTCUSD"``).
    timeframe:
        Timeframe string (e.g. ``"1D"``, ``"6H"``).
    pull_date:
        ISO date string of the extraction (e.g. ``"2026-03-03"``).
    base_path:
        Root directory for raw extractions.
    extension:
        File extension, ``"csv"`` or ``"parquet"``.

    Returns
    -------
    DataFrame loaded from the raw file.

    Raises
    ------
    FileNotFoundError
        If the raw file does not exist.
    ValueError
        If ``extension`` is not ``"csv"`` or ``"parquet"``.
    """
    filename = f"cbrest_{symbol_path}_{timeframe}_UTC_{pull_date}.{extension}"
    raw_path = Path(base_path) / symbol_path / timeframe / filename

    if not raw_path.exists():
        raise FileNotFoundError(f"Raw file not found: {raw_path}")

    logger.info("Loading raw file: %s", raw_path)

    if extension == "csv":
        return pd.read_csv(raw_path)
    if extension == "parquet":
        return pd.read_parquet(raw_path)

    raise ValueError(f"Unsupported file extension: '{extension}'. Use 'csv' or 'parquet'.")


def load_extraction_metadata(
    symbol_path: str,
    timeframe: str,
    pull_date: str,
    base_path: str = "data/metadata/extractions",
) -> dict:
    """Load extraction metadata JSON for a raw pull.

    Parameters
    ----------
    symbol_path:
        Path-sanitised symbol (e.g. ``"COINBASE_BTCUSD"``).
    timeframe:
        Timeframe string (e.g. ``"1D"``).
    pull_date:
        ISO date string of the extraction (e.g. ``"2026-03-03"``).
    base_path:
        Root directory for extraction metadata.

    Returns
    -------
    Parsed metadata as a dict.
    """
    filename = f"cbrest_{symbol_path}_{timeframe}_UTC_{pull_date}.json"
    meta_path = Path(base_path) / filename

    if not meta_path.exists():
        raise FileNotFoundError(f"Extraction metadata not found: {meta_path}")

    logger.info("Loading extraction metadata: %s", meta_path)
    with open(meta_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def list_processed_versions(
    base_path: str = "data/processed",
    symbol_path: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> list[str]:
    """Return a sorted list of available processed dataset versions.

    Parameters
    ----------
    base_path:
        Root directory for processed datasets.
    symbol_path:
        If provided, filter to versions containing this string.
    timeframe:
        If provided, filter to versions containing this string.

    Returns
    -------
    Sorted list of version directory names.
    """
    root = Path(base_path)
    if not root.exists():
        return []

    versions = [d.name for d in sorted(root.iterdir()) if d.is_dir()]

    if symbol_path:
        versions = [v for v in versions if symbol_path in v]
    if timeframe:
        versions = [v for v in versions if timeframe in v]

    return versions
