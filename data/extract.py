"""
data/extract.py

Coinbase REST API extraction script via ccxt.

Usage (from repo root):
    python -m data.extract [--timeframe 1D] [--version <version_string>]
    python -m data.extract --timeframe 1D --use-synthetic   # offline / sandbox use

This script:
  1. Fetches all available OHLCV bars from the Coinbase REST API via ccxt.
  2. Saves the raw CSV to data/raw/coinbase_rest/COINBASE_BTCUSD/<TF>/.
  3. Writes extraction metadata JSON sidecar.
  4. Runs validation.
  5. Builds the processed Parquet + manifest via the ingestion pipeline.
  6. Prints the dataset version string to stdout.

The script reads defaults from configs/default.yaml.

Pass ``--use-synthetic`` to generate realistic BTC/USD-like synthetic OHLCV
data instead of calling the live Coinbase REST API.  This is intended for
offline/sandboxed environments only; production pulls must use the live API.

References
----------
DECISIONS.md       — 2026-03-04 change log (official acquisition method)
ASSUMPTIONS.md     — Assumption 16 (Coinbase REST via ccxt)
docs/data/data_spec.md — §16–18 (storage, naming, metadata)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).parent.parent / "configs" / "default.yaml"

# ccxt timeframe strings mapped from project convention
_TF_MAP = {
    "1D": "1d",
    "6H": "6h",
    "4H": "4h",
    "1W": "1w",
    "1H": "1h",
}

# Oldest start date to request (ccxt will return from earliest available)
_HISTORY_START_MS = int(
    datetime(2013, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
)


# ── Public API ─────────────────────────────────────────────────────────────


def fetch_coinbase_ohlcv(
    timeframe: str = "1D",
    since_ms: Optional[int] = None,
    limit: int = 300,
) -> pd.DataFrame:
    """Fetch all available OHLCV bars from Coinbase via ccxt.

    Parameters
    ----------
    timeframe:
        Project timeframe string (``"1D"``, ``"6H"``, ``"4H"``, ``"1H"``, ``"1W"``).
    since_ms:
        Start timestamp in UTC milliseconds.  Defaults to 2013-01-01.
    limit:
        Number of bars per ccxt page request (max 300 for Coinbase via ccxt).

    Returns
    -------
    DataFrame with columns: ``timestamp``, ``open``, ``high``, ``low``,
    ``close``, ``volume``.  Timestamps are UTC-aware ``datetime64[ns, UTC]``.
    """
    try:
        import ccxt  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "ccxt is not installed. Run: pip install ccxt"
        ) from exc

    ccxt_tf = _TF_MAP.get(timeframe)
    if ccxt_tf is None:
        raise ValueError(
            f"Unsupported timeframe: '{timeframe}'. "
            f"Supported: {list(_TF_MAP.keys())}"
        )

    if since_ms is None:
        since_ms = _HISTORY_START_MS

    exchange = ccxt.coinbase({"enableRateLimit": True})

    all_bars: list[list] = []
    current_since = since_ms

    logger.info(
        "Fetching OHLCV from Coinbase REST API via ccxt: symbol=BTC/USD, timeframe=%s",
        ccxt_tf,
    )

    while True:
        bars = exchange.fetch_ohlcv(
            "BTC/USD",
            timeframe=ccxt_tf,
            since=current_since,
            limit=limit,
        )
        if not bars:
            break
        all_bars.extend(bars)
        last_ts = bars[-1][0]
        if last_ts <= current_since:
            break
        current_since = last_ts + 1
        if len(bars) < limit:
            break

    logger.info("Fetched %d bars total", len(all_bars))

    if not all_bars:
        raise RuntimeError(
            "No OHLCV bars returned from Coinbase REST API. "
            "Check network connectivity and ccxt exchange status."
        )

    df = pd.DataFrame(
        all_bars, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def generate_synthetic_ohlcv(
    timeframe: str = "1D",
    start: str = "2013-01-01",
    end: str = "2026-03-04",
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic BTC/USD-like synthetic OHLCV bars.

    Used for offline / sandboxed environments where the live Coinbase REST API
    is not accessible.  The price path uses a log-random-walk seeded for
    reproducibility.  NOT for production use.

    Parameters
    ----------
    timeframe:
        Project timeframe string (``"1D"``, ``"6H"``, ``"4H"``, ``"1W"``).
    start, end:
        ISO date strings for the date range.
    seed:
        Random seed for reproducibility.

    Returns
    -------
    DataFrame with columns: ``timestamp``, ``open``, ``high``, ``low``,
    ``close``, ``volume``.  Timestamps are UTC-aware.
    """
    rng = np.random.default_rng(seed)

    # Build timestamp grid
    _freq_map = {"1D": "D", "6H": "6h", "4H": "4h", "1H": "h", "1W": "W-MON"}
    freq = _freq_map.get(timeframe, "D")
    timestamps = pd.date_range(start=start, end=end, freq=freq, tz="UTC")
    n = len(timestamps)

    # Log-random-walk price path anchored near BTC history
    log_prices = np.cumsum(rng.normal(0.0008, 0.025, n))
    # Anchor so that prices span roughly 100 → 90 000
    log_prices = log_prices - log_prices[0] + np.log(100.0)
    close = np.exp(log_prices)

    # Realistic OHLC spreads
    daily_vol = rng.uniform(0.005, 0.03, n)
    high = close * (1 + daily_vol)
    low = close * (1 - daily_vol)
    open_ = close * np.exp(rng.normal(0, 0.01, n))
    # Clamp open to [low, high]
    open_ = np.clip(open_, low, high)

    volume = rng.uniform(5_000, 50_000, n) * (close / 10_000)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_.round(2),
            "high": high.round(2),
            "low": low.round(2),
            "close": close.round(2),
            "volume": volume.round(4),
        }
    )
    logger.info(
        "Generated %d synthetic %s bars [%s → %s]",
        n,
        timeframe,
        timestamps[0].date(),
        timestamps[-1].date(),
    )
    return df


def run_extraction(
    timeframe: str = "1D",
    dataset_version: Optional[str] = None,
    pull_date: Optional[str] = None,
    config_path: Optional[Path] = None,
    overwrite: bool = False,
    use_synthetic: bool = False,
) -> dict:
    """Run the full extraction + ingestion pipeline.

    Parameters
    ----------
    timeframe:
        Project timeframe string (``"1D"``, ``"6H"``, ``"4H"``).
    dataset_version:
        Processed dataset version string override.  If omitted, derived from
        config or constructed from ``pull_date``.
    pull_date:
        ISO date string for the pull (e.g. ``"2026-03-04"``).  Defaults to today.
    config_path:
        Path to ``default.yaml``.  Defaults to ``configs/default.yaml``.
    overwrite:
        Whether to overwrite an existing processed dataset.
    use_synthetic:
        If True, generate realistic synthetic BTC/USD-like data instead of
        calling the live Coinbase REST API.  Intended for offline/sandboxed
        environments.  NOT for production use.

    Returns
    -------
    Dict from :func:`data.ingestion.run_ingestion_pipeline`.
    """
    from data.ingestion import run_ingestion_pipeline  # noqa: PLC0415

    cfg = _load_config(config_path or _CONFIG_PATH)

    if pull_date is None:
        pull_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if dataset_version is None:
        symbol_path = cfg["market"]["symbol_path"]
        tz = cfg.get("timezone", "UTC")
        dataset_version = f"proc_{symbol_path}_{timeframe}_{tz}_{pull_date}_v1"

    logger.info("Dataset version: %s", dataset_version)

    if use_synthetic:
        logger.warning(
            "SYNTHETIC DATA MODE: generating simulated BTC/USD bars. "
            "NOT for production use."
        )
        raw_df = generate_synthetic_ohlcv(timeframe=timeframe, end=pull_date)
        extraction_method = "synthetic_generated"
        user_note = f"Synthetic data — offline/sandbox pull — {pull_date}"
    else:
        raw_df = fetch_coinbase_ohlcv(timeframe=timeframe)
        extraction_method = cfg["acquisition"]["method"]
        user_note = f"Official Phase 1B pull — {pull_date}"

    result = run_ingestion_pipeline(
        raw_df=raw_df,
        symbol_tv=cfg["market"]["symbol_tv"],
        symbol_path=cfg["market"]["symbol_path"],
        timeframe=timeframe,
        pull_date=pull_date,
        dataset_version=dataset_version,
        atr_windows=cfg.get("derived_fields", {}).get("atr_windows", [14]),
        raw_base=cfg["paths"]["raw"],
        processed_base=cfg["paths"]["processed"],
        metadata_base=cfg["paths"]["metadata"],
        extraction_method=extraction_method,
        mcp_tool_name="",
        user_note=user_note,
        overwrite=overwrite,
    )

    logger.info("Extraction complete: %s", result["dataset_version"])
    return result


# ── Internal helpers ───────────────────────────────────────────────────────


def _load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ── CLI entry point ────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fetch Coinbase REST OHLCV data and run the ingestion pipeline."
    )
    p.add_argument(
        "--timeframe",
        default="1D",
        choices=list(_TF_MAP.keys()),
        help="Timeframe to pull (default: 1D).",
    )
    p.add_argument(
        "--version",
        default=None,
        metavar="VERSION",
        help=(
            "Processed dataset version string override. "
            "Example: proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1"
        ),
    )
    p.add_argument(
        "--pull-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Pull date for file naming (default: today UTC).",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing processed dataset if it exists.",
    )
    p.add_argument(
        "--use-synthetic",
        action="store_true",
        help=(
            "Generate realistic synthetic BTC/USD-like bars instead of "
            "calling the live Coinbase REST API. "
            "For offline/sandboxed environments only. NOT for production use."
        ),
    )
    p.add_argument(
        "--resample-weekly-from",
        default=None,
        metavar="DAILY_VERSION",
        help=(
            "Instead of pulling new data, resample an existing daily processed "
            "dataset into a weekly dataset. "
            "Example: proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1"
        ),
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.resample_weekly_from:
        from data.ingestion import resample_daily_to_weekly  # noqa: PLC0415

        pull_date = args.pull_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            result = resample_daily_to_weekly(
                daily_version=args.resample_weekly_from,
                pull_date=pull_date,
                weekly_version=args.version,
                overwrite=args.overwrite,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Weekly resample failed: %s", exc)
            sys.exit(1)
        print(f"dataset_version: {result['dataset_version']}")
        print(f"processed_path:  {result['processed_path']}")
        print(f"manifest_path:   {result['manifest_path']}")
        print(f"rows:            {result['row_count']}")
        return

    try:
        result = run_extraction(
            timeframe=args.timeframe,
            dataset_version=args.version,
            pull_date=args.pull_date,
            overwrite=args.overwrite,
            use_synthetic=args.use_synthetic,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Extraction failed: %s", exc)
        sys.exit(1)

    print(f"dataset_version: {result['dataset_version']}")
    print(f"raw_path:        {result['raw_path']}")
    print(f"processed_path:  {result['processed_path']}")
    print(f"rows:            {result['validation_result'].row_count}")


if __name__ == "__main__":
    main()
