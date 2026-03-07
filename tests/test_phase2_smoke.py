"""
tests/test_phase2_smoke.py

Tests for research/run_phase2_smoke.py JSON artifact output.

Verifies that the smoke script writes a valid JSON summary file alongside
the existing CSV and TXT outputs.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Helpers ────────────────────────────────────────────────────────────────


def _create_synthetic_dataset(base_dir: Path, version: str, n: int = 100) -> None:
    """Create a minimal processed dataset + manifest for smoke-run testing."""
    ds_dir = base_dir / version
    ds_dir.mkdir(parents=True, exist_ok=True)

    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = 1000.0 + np.arange(n, dtype=float) * 5
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": close + 10.0,
            "low": close - 10.0,
            "close": close,
            "volume": [1000.0] * n,
            "bar_index": np.arange(n, dtype=np.int64),
            "calendar_day_index": np.arange(n, dtype=np.int64),
            "trading_day_index": np.arange(n, dtype=np.int64),
            "log_close": np.log(close),
            "hl_range": [20.0] * n,
            "true_range": [20.0] * n,
            "atr_14": [float("nan")] * 14 + [20.0] * (n - 14),
        }
    )
    parquet_path = ds_dir / f"{version}.parquet"
    df.to_parquet(parquet_path, index=False)

    manifest = {
        "dataset_version": version,
        "validation_passed": True,
        "row_count_processed": n,
        "missing_bar_count": 0,
        "missing_bar_policy": "strict",
        "missing_bar_details": [],
    }
    manifest_path = ds_dir / f"{version}_manifest.json"
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh)


@pytest.fixture
def smoke_env(tmp_path):
    """Set up a minimal config + dataset for the smoke script."""
    version = "proc_TEST_1D_v1"
    base_path = tmp_path / "processed"
    _create_synthetic_dataset(base_path, version, n=100)

    config = {
        "dataset": {
            "current_version": version,
        },
    }
    config_path = tmp_path / "config.yaml"
    import yaml

    with open(config_path, "w") as fh:
        yaml.dump(config, fh)

    output_dir = tmp_path / "reports" / "phase2"
    return {
        "config_path": str(config_path),
        "base_path": str(base_path),
        "output_dir": str(output_dir),
    }


# ── Tests ──────────────────────────────────────────────────────────────────


def test_smoke_produces_json_summary(smoke_env):
    """The smoke script must produce a phase2_smoke_summary.json file."""
    from research.run_phase2_smoke import main

    results = main(
        [
            "--config",
            smoke_env["config_path"],
            "--base-path",
            smoke_env["base_path"],
            "--output-dir",
            smoke_env["output_dir"],
        ]
    )

    json_path = Path(smoke_env["output_dir"]) / "phase2_smoke_summary.json"
    assert json_path.exists(), "phase2_smoke_summary.json not produced"


def test_smoke_json_is_valid(smoke_env):
    """The JSON summary must be valid JSON and parseable."""
    from research.run_phase2_smoke import main

    main(
        [
            "--config",
            smoke_env["config_path"],
            "--base-path",
            smoke_env["base_path"],
            "--output-dir",
            smoke_env["output_dir"],
        ]
    )

    json_path = Path(smoke_env["output_dir"]) / "phase2_smoke_summary.json"
    with open(json_path) as fh:
        data = json.load(fh)
    assert isinstance(data, list)
    assert len(data) > 0


def test_smoke_json_has_required_keys(smoke_env):
    """Each entry in the JSON summary must contain the expected keys."""
    from research.run_phase2_smoke import main

    main(
        [
            "--config",
            smoke_env["config_path"],
            "--base-path",
            smoke_env["base_path"],
            "--output-dir",
            smoke_env["output_dir"],
        ]
    )

    json_path = Path(smoke_env["output_dir"]) / "phase2_smoke_summary.json"
    with open(json_path) as fh:
        data = json.load(fh)

    required_keys = {
        "version",
        "method",
        "rows",
        "missing_bar_count",
        "skip_on_gap",
        "origins_count",
        "impulses_count",
        "origin_csv",
        "impulse_csv",
    }
    for entry in data:
        assert required_keys.issubset(set(entry.keys())), (
            f"Missing keys: {required_keys - set(entry.keys())}"
        )


def test_smoke_txt_summary_still_produced(smoke_env):
    """The TXT summary must still be produced alongside the JSON."""
    from research.run_phase2_smoke import main

    main(
        [
            "--config",
            smoke_env["config_path"],
            "--base-path",
            smoke_env["base_path"],
            "--output-dir",
            smoke_env["output_dir"],
        ]
    )

    txt_path = Path(smoke_env["output_dir"]) / "phase2_smoke_summary.txt"
    assert txt_path.exists(), "phase2_smoke_summary.txt not produced"
