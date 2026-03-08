"""
backtest/runner.py

Phase 6 — Backtest runner.

Loads processed datasets, generates forecast zones and signals for a given
time window, simulates trade execution, and aggregates results.

Pipeline per backtest window
-----------------------------
1. Filter 1D data to the train window ``[train_start, train_end)``.
2. Detect origins (pivot detector) and impulses from train data.
3. Run all five Phase 3/4 generators → Projections.
4. Run confluence engine → ConfluenceZones.
5. Generate SignalCandidates (Phase 5 rules).
6. For each signal, iterate through 6H bars in the test window:
   a. Check if price closes inside ``entry_region`` (first triggering bar).
   b. On the next bar's open, apply fees+slippage and enter.
   c. On each subsequent bar, check invalidation conditions.
   d. On first invalidation, exit at the following bar's open.
   e. Safety-valve: if ``max_hold_bars`` exceeded, exit at next open.
7. Compute equity curve and summary metrics.
8. Write output files to the configured output directory.

Determinism guarantee
---------------------
All operations are purely functional given the input DataFrames and config.
No random state, no live data, no mutable global state.

Gap policy
----------
The ``missing_bar_count`` from the 6H manifest is passed to signal generation
so that ``strict_multi_candle`` is appended to ``confirmations_required`` when
gaps are present (Phase 5 rule).  During execution, confirmation checks are
**not** re-evaluated per bar; the backtest assumes that the confirmation
window is the ``train_end`` bar (i.e., the most recent train bar acts as the
confirmation snapshot).

Output files
-----------
- ``<output_dir>/trades.csv`` — one row per completed trade
- ``<output_dir>/equity_curve.csv`` — equity at each 6H bar timestamp
- ``<output_dir>/summary.json`` — aggregate performance metrics

References
----------
backtest/execution.py — Trade, build_trade, fill helpers
configs/backtest.yaml — configurable defaults
signals/signal_generation.py — generate_signals
signals/confluence.py — build_confluence_zones
ASSUMPTIONS.md — Assumptions 31–38
CLAUDE.md — Phase 6 goal
PROJECT_STATUS.md — Phase 6 section
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtest.execution import (
    Trade,
    build_trade,
    compute_position_size,
)
from modules.impulse import Impulse, detect_impulses
from modules.origin_selection import detect_pivots
from signals.confluence import build_confluence_zones
from signals.generators_angle_families import projections_from_angle_families
from signals.generators_jttl import projections_from_jttl_lines
from signals.generators_measured_moves import projections_from_measured_moves
from signals.generators_sqrt_levels import projections_from_sqrt_levels
from signals.generators_time_counts import projections_from_time_windows
from signals.projections import Projection
from signals.signal_generation import generate_signals
from signals.signal_types import SignalCandidate

logger = logging.getLogger(__name__)


# ── Data helpers ──────────────────────────────────────────────────────────────


def ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with a UTC DatetimeIndex.

    If the DataFrame already has a ``DatetimeIndex``, return it unchanged.
    If it has a ``timestamp`` column, set that column as the index.
    Otherwise return the DataFrame unchanged (will fail downstream with a
    clear error rather than a confusing one).
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    if "timestamp" in df.columns:
        df2 = df.set_index("timestamp")
        if not isinstance(df2.index, pd.DatetimeIndex):
            df2.index = pd.to_datetime(df2.index, utc=True)
        return df2
    return df


# ── Module imports that may be unavailable in minimal tests ──────────────────
try:
    from modules.adjusted_angles import compute_impulse_angles
    from modules.jttl import compute_jttl
    from modules.measured_moves import compute_measured_moves
    from modules.sqrt_levels import sqrt_levels
    from modules.time_counts import build_bar_to_time_map, time_square_windows
    from core.coordinate_system import get_angle_scale_basis
    _PIPELINE_AVAILABLE = True
except ImportError:
    _PIPELINE_AVAILABLE = False
    logger.warning("Some pipeline modules unavailable; signal generation will be empty.")


# ── Config ────────────────────────────────────────────────────────────────────


@dataclass
class BacktestConfig:
    """Parsed backtest configuration.

    All fields have conservative defaults matching configs/backtest.yaml.
    """

    # Dataset
    version_1d: str = "proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1"
    version_6h: str = "proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1"

    # Capital
    initial_capital: float = 100_000.0
    position_sizing: str = "fixed_fraction"   # "fixed_fraction" or "fixed_notional"
    fraction: float = 0.01
    fixed_notional: float = 1_000.0

    # Costs (one-way bps; total round-trip = 2×)
    fees_bps: float = 5.0          # half of 10 bps round-trip
    slippage_bps: float = 2.5      # half of 5 bps round-trip

    # Execution
    entry_timing: str = "next_bar_open"
    exit_on_invalidation: bool = True
    exit_on_time_expiry: bool = True
    max_hold_bars: int = 200

    # Signal generation
    min_score_for_neutral: float = 0.5
    invalidation_buffer: float = 0.0
    min_impulse_quality: float = 0.0
    pivot_n_bars: int = 5
    max_impulses: int = 50
    max_origins: int = 20

    @classmethod
    def from_yaml(cls, path: str = "configs/backtest.yaml") -> "BacktestConfig":
        """Load config from a YAML file.  Returns defaults on missing keys."""
        import yaml  # optional dependency; yaml is already in pyproject.toml

        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        ds = raw.get("dataset", {})
        cap = raw.get("capital", {})
        costs = raw.get("costs", {})
        exec_ = raw.get("execution", {})
        sig = raw.get("signal_generation", {})

        # Round-trip bps → split in half for one-way application
        fees_rt = float(costs.get("fees_bps", 10.0))
        slip_rt = float(costs.get("slippage_bps", 5.0))

        return cls(
            version_1d=ds.get("version_1d", cls.version_1d),
            version_6h=ds.get("version_6h", cls.version_6h),
            initial_capital=float(cap.get("initial", cls.initial_capital)),
            position_sizing=cap.get("position_sizing", cls.position_sizing),
            fraction=float(cap.get("fraction", cls.fraction)),
            fixed_notional=float(cap.get("fixed_notional", cls.fixed_notional)),
            fees_bps=fees_rt / 2.0,
            slippage_bps=slip_rt / 2.0,
            entry_timing=exec_.get("entry_timing", cls.entry_timing),
            exit_on_invalidation=bool(exec_.get("exit_on_invalidation", cls.exit_on_invalidation)),
            exit_on_time_expiry=bool(exec_.get("exit_on_time_expiry", cls.exit_on_time_expiry)),
            max_hold_bars=int(exec_.get("max_hold_bars", cls.max_hold_bars)),
            min_score_for_neutral=float(sig.get("min_score_for_neutral", cls.min_score_for_neutral)),
            invalidation_buffer=float(sig.get("invalidation_buffer", cls.invalidation_buffer)),
            min_impulse_quality=float(sig.get("min_impulse_quality", cls.min_impulse_quality)),
            pivot_n_bars=int(sig.get("pivot_n_bars", cls.pivot_n_bars)),
            max_impulses=int(sig.get("max_impulses", cls.max_impulses)),
            max_origins=int(sig.get("max_origins", cls.max_origins)),
        )


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class BacktestResult:
    """Aggregated results from a single backtest window.

    Fields
    ------
    trades : list of Trade
        All simulated trades (including zero-pnl no-entry trades).
    equity_curve : pd.Series
        Account equity at each 6H bar timestamp (indexed by timestamp).
    summary : dict
        Aggregate performance metrics (see :func:`compute_summary`).
    window_start : Optional[pd.Timestamp]
        Start of the test window.
    window_end : Optional[pd.Timestamp]
        End of the test window.
    n_signals_generated : int
        Number of signal candidates produced from the train data.
    dataset_version : str
        Dataset version used.
    """

    trades: List[Trade] = field(default_factory=list)
    equity_curve: "pd.Series" = field(default_factory=lambda: pd.Series(dtype=float))
    summary: Dict[str, Any] = field(default_factory=dict)
    window_start: Optional[pd.Timestamp] = None
    window_end: Optional[pd.Timestamp] = None
    n_signals_generated: int = 0
    dataset_version: str = ""


# ── Pipeline helpers ──────────────────────────────────────────────────────────


def _generate_projections(
    df_1d: pd.DataFrame,
    impulses: List[Impulse],
    config: BacktestConfig,
) -> List[Projection]:
    """Run all five Phase 3/4 generators on the given impulses and 1D data.

    Returns an empty list if pipeline modules are unavailable.
    """
    if not _PIPELINE_AVAILABLE:
        return []

    projections: List[Projection] = []
    if not impulses:
        return projections

    # ── Measured moves ──────────────────────────────────────────────────
    try:
        ratios = [0.5, 1.0, 1.5, 2.0]
        for imp in impulses:
            mms = compute_measured_moves(imp, ratios=ratios)
            projections.extend(projections_from_measured_moves(mms))
    except Exception as exc:
        logger.debug("measured_moves generator error: %s", exc)

    # ── JTTL ────────────────────────────────────────────────────────────
    try:
        origins = detect_pivots(df_1d, n_bars=config.pivot_n_bars)
        origins = origins[: config.max_origins]
        for orig in origins:
            lines = compute_jttl(orig)
            horizons = [30, 60, 90, 180]
            projs = projections_from_jttl_lines(lines, df_1d, horizons=horizons)
            projections.extend(projs)
    except Exception as exc:
        logger.debug("jttl generator error: %s", exc)

    # ── Sqrt levels ─────────────────────────────────────────────────────
    try:
        for imp in impulses:
            levels = sqrt_levels(imp)
            projections.extend(projections_from_sqrt_levels(levels))
    except Exception as exc:
        logger.debug("sqrt_levels generator error: %s", exc)

    # ── Time counts ─────────────────────────────────────────────────────
    try:
        if not df_1d.empty and "bar_index" in df_1d.columns:
            bar_to_time = build_bar_to_time_map(df_1d)
            for imp in impulses:
                windows = time_square_windows(imp)
                projections.extend(
                    projections_from_time_windows(windows, bar_to_time)
                )
    except Exception as exc:
        logger.debug("time_counts generator error: %s", exc)

    # ── Angle families ──────────────────────────────────────────────────
    try:
        basis = get_angle_scale_basis(df_1d)
        for imp in impulses:
            angles = compute_impulse_angles(imp, basis)
            projs = projections_from_angle_families(angles, df_1d, horizons=[30, 60, 90])
            projections.extend(projs)
    except Exception as exc:
        logger.debug("angle_families generator error: %s", exc)

    return projections


def generate_signals_from_df(
    df_1d: pd.DataFrame,
    manifest_1d: dict,
    config: BacktestConfig,
    dataset_version: str = "",
) -> List[SignalCandidate]:
    """Run the full Phase 2–5 pipeline on a 1D DataFrame slice.

    Parameters
    ----------
    df_1d:
        Processed 1D DataFrame (must have standard derived columns).
    manifest_1d:
        Manifest dict for the 1D dataset (provides missing_bar_count).
    config:
        Backtest configuration.
    dataset_version:
        Version string for provenance.

    Returns
    -------
    List of :class:`~signals.signal_types.SignalCandidate` objects.
    """
    if df_1d is None or df_1d.empty:
        logger.debug("generate_signals_from_df: empty DataFrame — returning []")
        return []

    if not _PIPELINE_AVAILABLE:
        logger.warning("Pipeline unavailable; no signals generated.")
        return []

    # ── Phase 2: Origins and impulses ─────────────────────────────────────
    try:
        skip_on_gap = int(manifest_1d.get("missing_bar_count", 0)) > 0
        origins = detect_pivots(df_1d, n_bars=config.pivot_n_bars)
        impulses = detect_impulses(
            df_1d,
            origins,
            skip_on_gap=skip_on_gap,
        )
    except Exception as exc:
        logger.warning("Impulse detection failed: %s", exc)
        return []

    # Filter by quality
    impulses = [
        imp for imp in impulses
        if imp.quality_score >= config.min_impulse_quality
    ]
    impulses = impulses[: config.max_impulses]

    if not impulses:
        logger.debug("No impulses produced from 1D slice.")
        return []

    # ── Phase 3–4: Projections and zones ──────────────────────────────────
    projections = _generate_projections(df_1d, impulses, config)
    if not projections:
        logger.debug("No projections produced.")
        return []

    zones = build_confluence_zones(projections)
    if not zones:
        logger.debug("No confluence zones produced.")
        return []

    # ── Phase 5: Signal candidates ────────────────────────────────────────
    signals = generate_signals(
        zones=zones,
        projections=projections,
        dataset_version=dataset_version,
        manifest=manifest_1d,
        invalidation_buffer=config.invalidation_buffer,
        min_score_for_neutral=config.min_score_for_neutral,
    )
    return signals


# ── Execution simulation ──────────────────────────────────────────────────────


def _get_invalidation_price(signal: SignalCandidate) -> Optional[float]:
    """Extract the primary price-based invalidation level from a signal."""
    for rule in signal.invalidation:
        if rule.condition in ("close_below_zone", "close_above_zone"):
            if rule.price_level is not None:
                return rule.price_level
    return None


def _get_time_cutoff(signal: SignalCandidate) -> Optional[pd.Timestamp]:
    """Extract the time-based invalidation cutoff from a signal."""
    for rule in signal.invalidation:
        if rule.condition == "time_expired" and rule.time_cutoff is not None:
            return rule.time_cutoff
    return None


def simulate_signal_on_6h(
    signal: SignalCandidate,
    df_6h: pd.DataFrame,
    equity: float,
    config: BacktestConfig,
) -> Optional[Trade]:
    """Simulate a single signal's execution against 6H bars.

    Parameters
    ----------
    signal:
        The signal candidate to simulate.
    df_6h:
        6H DataFrame sorted by index (timestamp ascending) covering the test
        window.  Must contain at minimum: ``open``, ``high``, ``low``,
        ``close`` columns.
    equity:
        Current account equity used to compute position size.
    config:
        Backtest configuration.

    Returns
    -------
    A :class:`~backtest.execution.Trade` if an entry was triggered, or
    ``None`` if price never entered the entry region during the window.

    Notes
    -----
    - Neutral-bias signals are skipped (no directional trade).
    - Only price-based entry is implemented (confirmation checks are assumed
      to have passed at signal generation time; see ASSUMPTIONS.md Assumption 36).
    """
    if signal.bias == "neutral":
        return None

    required_cols = {"open", "high", "low", "close"}
    if df_6h.empty or not required_cols.issubset(df_6h.columns):
        return None

    er = signal.entry_region
    price_lo = er.price_low
    price_hi = er.price_high
    side = signal.bias  # "long" or "short"

    inv_price = _get_invalidation_price(signal)
    time_cutoff = _get_time_cutoff(signal) if config.exit_on_time_expiry else None

    position_size = compute_position_size(
        equity=equity,
        sizing_mode=config.position_sizing,
        fraction=config.fraction,
        fixed_notional=config.fixed_notional,
    )

    rows = df_6h  # already sorted by caller

    entry_bar_idx: Optional[int] = None
    entry_bar_time: Optional[pd.Timestamp] = None
    entry_open: Optional[float] = None

    # ── Step 1: find first bar where close is inside entry_region ────────
    for i in range(len(rows) - 1):
        row = rows.iloc[i]
        ts = rows.index[i]

        # Skip bars before entry_region's time_earliest
        if er.time_earliest is not None and ts < er.time_earliest:
            continue
        if er.time_latest is not None and ts > er.time_latest:
            break

        close = float(row["close"])
        if price_lo <= close <= price_hi:
            # Entry: use next bar's open
            entry_bar_idx = i + 1
            entry_bar_time = rows.index[entry_bar_idx]
            entry_open = float(rows.iloc[entry_bar_idx]["open"])
            break

    if entry_bar_idx is None or entry_open is None:
        return None  # price never entered the zone

    # ── Step 2: monitor exit conditions ─────────────────────────────────
    exit_bar_idx: Optional[int] = None
    exit_open_val: Optional[float] = None
    exit_reason: str = "end_of_data"

    for j in range(entry_bar_idx + 1, len(rows)):
        row_j = rows.iloc[j]
        ts_j = rows.index[j]
        close_j = float(row_j["close"])

        bars_held = j - entry_bar_idx

        # Time-expiry invalidation
        if time_cutoff is not None and ts_j > time_cutoff:
            exit_bar_idx = j
            exit_open_val = float(row_j["open"])
            exit_reason = "time_expired"
            break

        # Max hold bars safety valve
        if bars_held >= config.max_hold_bars:
            exit_bar_idx = j
            exit_open_val = float(row_j["open"])
            exit_reason = "max_hold_bars"
            break

        # Price-based invalidation
        if config.exit_on_invalidation and inv_price is not None:
            if side == "long":
                # Invalidate if close falls below inv_price - buffer
                buffer = _get_invalidation_buffer(signal, "close_below_zone")
                if close_j < inv_price - buffer:
                    if j + 1 < len(rows):
                        exit_bar_idx = j + 1
                        exit_open_val = float(rows.iloc[j + 1]["open"])
                    else:
                        exit_bar_idx = j
                        exit_open_val = float(row_j["open"])
                    exit_reason = "invalidation"
                    break
            elif side == "short":
                buffer = _get_invalidation_buffer(signal, "close_above_zone")
                if close_j > inv_price + buffer:
                    if j + 1 < len(rows):
                        exit_bar_idx = j + 1
                        exit_open_val = float(rows.iloc[j + 1]["open"])
                    else:
                        exit_bar_idx = j
                        exit_open_val = float(row_j["open"])
                    exit_reason = "invalidation"
                    break

    if exit_bar_idx is None:
        # No exit triggered: exit at last bar open
        exit_bar_idx = len(rows) - 1
        exit_open_val = float(rows.iloc[exit_bar_idx]["open"])
        exit_reason = "end_of_data"

    exit_time_val = rows.index[exit_bar_idx]

    return build_trade(
        signal_id=signal.signal_id,
        side=side,
        entry_time=entry_bar_time,
        entry_open=entry_open,
        exit_time=exit_time_val,
        exit_open=float(exit_open_val),
        exit_reason=exit_reason,
        position_size=position_size,
        fees_bps=config.fees_bps,
        slippage_bps=config.slippage_bps,
        entry_region_low=price_lo,
        entry_region_high=price_hi,
        invalidation_price=inv_price,
        quality_score=signal.quality_score,
        dataset_version=signal.dataset_version,
        metadata={"zone_id": signal.zone_id, "confirmations": signal.confirmations_required},
    )


def _get_invalidation_buffer(signal: SignalCandidate, condition: str) -> float:
    """Return the buffer for a specific invalidation condition."""
    for rule in signal.invalidation:
        if rule.condition == condition:
            return rule.buffer
    return 0.0


# ── Equity curve ──────────────────────────────────────────────────────────────


def build_equity_curve(
    trades: List[Trade],
    df_6h_index: pd.DatetimeIndex,
    initial_capital: float,
) -> pd.Series:
    """Build a bar-by-bar equity curve from a list of completed trades.

    Parameters
    ----------
    trades:
        List of completed Trade objects.
    df_6h_index:
        DatetimeIndex of all 6H bars in the test window.
    initial_capital:
        Starting equity value.

    Returns
    -------
    pd.Series indexed by timestamp, values are equity at each bar.
    """
    # Map each trade's net_pnl to its exit_time
    pnl_by_time: Dict[pd.Timestamp, float] = {}
    for t in trades:
        if t.exit_time is not None:
            pnl_by_time[t.exit_time] = pnl_by_time.get(t.exit_time, 0.0) + t.net_pnl

    equity = initial_capital
    equity_series: Dict[pd.Timestamp, float] = {}
    for ts in df_6h_index:
        equity += pnl_by_time.get(ts, 0.0)
        equity_series[ts] = equity

    return pd.Series(equity_series, name="equity")


# ── Summary metrics ───────────────────────────────────────────────────────────


def compute_summary(
    trades: List[Trade],
    equity_curve: pd.Series,
    initial_capital: float,
    window_start: Optional[pd.Timestamp],
    window_end: Optional[pd.Timestamp],
    n_signals_generated: int,
    dataset_version: str,
) -> dict:
    """Compute aggregate performance metrics from a list of trades.

    Metrics
    -------
    - ``total_trades``: number of completed trades
    - ``winning_trades``: trades with net_pnl > 0
    - ``win_rate``: winning_trades / total_trades (0.0 if no trades)
    - ``total_net_pnl``: sum of all net_pnl
    - ``total_gross_pnl``: sum of gross_pnl
    - ``total_fees_slippage``: sum of fees_and_slippage
    - ``avg_net_pnl``: mean net_pnl per trade
    - ``avg_r_multiple``: mean R-multiple (trades with defined invalidation)
    - ``expectancy``: avg_net_pnl / position_size_avg (if applicable)
    - ``max_drawdown``: maximum peak-to-trough equity decline (absolute)
    - ``max_drawdown_pct``: max drawdown as fraction of peak equity
    - ``sharpe_like``: (mean net_pnl) / (std net_pnl) * sqrt(252)
      assuming each trade is ~1 day; documented approximation (ASSUMPTIONS.md 35)
    - ``total_return_pct``: (final_equity - initial_equity) / initial_equity
    - ``n_signals_generated``: signals produced in the train window
    - ``exit_reason_counts``: breakdown by exit reason

    Notes
    -----
    Sharpe-like is computed per-trade, not per-bar.  This is a documented
    approximation (ASSUMPTIONS.md Assumption 35).  Walk-forward Sharpe is more
    meaningful than single-window Sharpe.
    """
    n = len(trades)
    if n == 0:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "win_rate": 0.0,
            "total_net_pnl": 0.0,
            "total_gross_pnl": 0.0,
            "total_fees_slippage": 0.0,
            "avg_net_pnl": 0.0,
            "avg_r_multiple": 0.0,
            "expectancy": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_like": 0.0,
            "total_return_pct": 0.0,
            "n_signals_generated": n_signals_generated,
            "window_start": str(window_start) if window_start else None,
            "window_end": str(window_end) if window_end else None,
            "dataset_version": dataset_version,
            "exit_reason_counts": {},
        }

    net_pnls = [t.net_pnl for t in trades]
    gross_pnls = [t.gross_pnl for t in trades]
    costs = [t.fees_and_slippage for t in trades]

    winners = sum(1 for p in net_pnls if p > 0)
    total_net = sum(net_pnls)
    total_gross = sum(gross_pnls)
    total_cost = sum(costs)
    avg_net = total_net / n
    avg_gross = total_gross / n

    # R-multiples (only for trades with defined invalidation)
    r_mults = [t.r_multiple for t in trades if t.invalidation_price is not None]
    avg_r = sum(r_mults) / len(r_mults) if r_mults else 0.0

    # Expectancy: avg_net as fraction of avg position size
    avg_pos_size = sum(t.position_size for t in trades) / n
    expectancy = avg_net / avg_pos_size if avg_pos_size > 0 else 0.0

    # Max drawdown from equity curve
    max_dd = 0.0
    max_dd_pct = 0.0
    if not equity_curve.empty:
        peak = equity_curve.expanding().max()
        drawdown = equity_curve - peak
        max_dd = float(drawdown.min())
        peak_at_trough = float(peak[drawdown.idxmin()])
        max_dd_pct = max_dd / peak_at_trough if peak_at_trough > 0 else 0.0

    # Sharpe-like (per-trade returns)
    import numpy as np
    pnl_arr = pd.Series(net_pnls)
    std_pnl = float(pnl_arr.std(ddof=1)) if len(pnl_arr) > 1 else 0.0
    # Scale to annualise: assume ~252 trades per year as approximation
    sharpe_like = (avg_net / std_pnl) * math.sqrt(252) if std_pnl > 0 else 0.0

    # Total return
    if not equity_curve.empty:
        final_equity = float(equity_curve.iloc[-1])
        total_return_pct = (final_equity - initial_capital) / initial_capital
    else:
        total_return_pct = total_net / initial_capital

    # Exit reason breakdown
    exit_counts: Dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    return {
        "total_trades": n,
        "winning_trades": winners,
        "win_rate": winners / n,
        "total_net_pnl": total_net,
        "total_gross_pnl": total_gross,
        "total_fees_slippage": total_cost,
        "avg_net_pnl": avg_net,
        "avg_r_multiple": avg_r,
        "expectancy": expectancy,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "sharpe_like": sharpe_like,
        "total_return_pct": total_return_pct,
        "n_signals_generated": n_signals_generated,
        "window_start": str(window_start) if window_start else None,
        "window_end": str(window_end) if window_end else None,
        "dataset_version": dataset_version,
        "exit_reason_counts": exit_counts,
    }


# ── Main backtest entry point ─────────────────────────────────────────────────


def run_backtest(
    df_1d: pd.DataFrame,
    df_6h: pd.DataFrame,
    manifest_1d: dict,
    manifest_6h: dict,
    config: BacktestConfig,
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    dataset_version: str = "",
) -> BacktestResult:
    """Run a single backtest window.

    Parameters
    ----------
    df_1d:
        Full 1D processed DataFrame (will be sliced to train window).
    df_6h:
        Full 6H processed DataFrame (will be sliced to test window).
    manifest_1d:
        Manifest for the 1D dataset.
    manifest_6h:
        Manifest for the 6H dataset.
    config:
        Backtest configuration.
    train_end:
        Inclusive upper bound of the training window (1D bars ≤ this time).
    test_start:
        Inclusive lower bound of the test window (6H bars ≥ this time).
    test_end:
        Inclusive upper bound of the test window (6H bars ≤ this time).
    dataset_version:
        Dataset version string for provenance.

    Returns
    -------
    :class:`BacktestResult` containing trades, equity curve, and summary.
    """
    # ── Slice data ────────────────────────────────────────────────────────
    if df_1d is None or df_1d.empty:
        logger.warning("Empty or invalid 1D DataFrame — returning empty result.")
        return BacktestResult(
            window_start=test_start,
            window_end=test_end,
            dataset_version=dataset_version,
        )

    df_1d = ensure_datetime_index(df_1d)
    df_6h = ensure_datetime_index(df_6h) if df_6h is not None else pd.DataFrame()

    df_1d_sorted = df_1d.sort_index()
    df_6h_sorted = df_6h.sort_index() if not df_6h.empty else pd.DataFrame()

    # Guard against non-DatetimeIndex (e.g. empty RangeIndex)
    if not isinstance(df_1d_sorted.index, pd.DatetimeIndex):
        logger.warning("1D DataFrame has non-DatetimeIndex — returning empty result.")
        return BacktestResult(
            window_start=test_start,
            window_end=test_end,
            dataset_version=dataset_version,
        )

    df_1d_train = df_1d_sorted[df_1d_sorted.index <= train_end]
    if isinstance(df_6h_sorted.index, pd.DatetimeIndex) and not df_6h_sorted.empty:
        df_6h_test = df_6h_sorted[
            (df_6h_sorted.index >= test_start) & (df_6h_sorted.index <= test_end)
        ]
    else:
        df_6h_test = pd.DataFrame()

    logger.info(
        "Backtest window: train up to %s | test %s → %s | 1D bars=%d | 6H bars=%d",
        train_end.date(),
        test_start.date(),
        test_end.date(),
        len(df_1d_train),
        len(df_6h_test),
    )

    if df_1d_train.empty or df_6h_test.empty:
        logger.warning("Empty train or test slice — returning empty result.")
        return BacktestResult(
            window_start=test_start,
            window_end=test_end,
            dataset_version=dataset_version,
        )

    # ── Generate signals from train data ─────────────────────────────────
    signals = generate_signals_from_df(
        df_1d=df_1d_train,
        manifest_1d=manifest_1d,
        config=config,
        dataset_version=dataset_version,
    )
    n_signals = len(signals)
    logger.info("Signals generated: %d", n_signals)

    # ── Simulate execution ────────────────────────────────────────────────
    equity = config.initial_capital
    trades: List[Trade] = []

    for signal in signals:
        trade = simulate_signal_on_6h(
            signal=signal,
            df_6h=df_6h_test,
            equity=equity,
            config=config,
        )
        if trade is not None:
            trades.append(trade)
            equity += trade.net_pnl

    logger.info("Trades executed: %d", len(trades))

    # ── Equity curve ──────────────────────────────────────────────────────
    equity_curve = build_equity_curve(trades, df_6h_test.index, config.initial_capital)

    # ── Summary ───────────────────────────────────────────────────────────
    summary = compute_summary(
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=config.initial_capital,
        window_start=test_start,
        window_end=test_end,
        n_signals_generated=n_signals,
        dataset_version=dataset_version,
    )

    return BacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        summary=summary,
        window_start=test_start,
        window_end=test_end,
        n_signals_generated=n_signals,
        dataset_version=dataset_version,
    )


# ── Output writers ────────────────────────────────────────────────────────────


def write_trades(trades: List[Trade], path: Path, fmt: str = "csv") -> None:
    """Write trades to CSV or Parquet.

    Parameters
    ----------
    trades:
        List of :class:`Trade` objects.
    path:
        Output file path (extension will be replaced with fmt).
    fmt:
        ``"csv"`` or ``"parquet"``.
    """
    if not trades:
        logger.warning("No trades to write.")
        return
    df = pd.DataFrame([t.to_dict() for t in trades])
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        df.to_parquet(path.with_suffix(".parquet"), index=False)
    else:
        df.to_csv(path.with_suffix(".csv"), index=False)
    logger.info("Trades written to: %s", path)


def write_equity_curve(equity_curve: pd.Series, path: Path) -> None:
    """Write equity curve to CSV."""
    if equity_curve.empty:
        logger.warning("Empty equity curve — not writing.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    equity_curve.to_csv(path.with_suffix(".csv"), header=["equity"])
    logger.info("Equity curve written to: %s", path)


def write_summary(summary: dict, path: Path) -> None:
    """Write summary JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    logger.info("Summary written to: %s", path)
