"""
tests/test_gating.py

Tests for backtest/gating.py — evaluate_confirmation_gate and GatingResult.

Coverage
--------
- GatingResult:
  - to_dict() returns expected keys
- evaluate_confirmation_gate:
  - empty OHLCV slice → passed=False with reason
  - signal with no confirmations_required → passed=True (gate trivially passes)
  - signal with confirmations: all pass → GatingResult.passed=True
  - signal with confirmations: any fail → GatingResult.passed=False
  - neutral signal with candle_direction → gate fails (neutral bias not applicable)
  - lookback limits the bars seen by the checks (no lookahead)
  - metadata contains lookback and n_bars_in_slice
- Timing / no-lookahead:
  - when 100 bars are available but lookback=5, gate only sees last 5 bars
  - gate at bar i uses only rows[:i+1] — future bars not used
- Integration with simulate_signal_on_6h (via BacktestConfig.use_confirmation_gating):
  - gating=False: entry occurs regardless of confirmation state
  - gating=True: entry blocked when candle_direction fails
  - gating=True: entry allowed when candle_direction passes
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import pytest

from backtest.gating import GatingResult, evaluate_confirmation_gate
from backtest.runner import BacktestConfig, simulate_signal_on_6h
from signals.signal_types import EntryRegion, InvalidationRule, SignalCandidate


# ── Helpers ───────────────────────────────────────────────────────────────────

_TS_BASE = pd.Timestamp("2024-01-01 00:00:00+00:00")


def _make_ohlcv(
    n: int = 20,
    base: float = 100.0,
    bullish: bool = True,
    start: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    ts = start or _TS_BASE
    rows = []
    for i in range(n):
        o = base + i * 0.5
        if bullish:
            c = o + 1.0
        else:
            c = o - 1.0
        rows.append({"open": o, "high": o + 2.0, "low": o - 2.0, "close": c, "volume": 1.0})
    return pd.DataFrame(rows, index=pd.date_range(ts, periods=n, freq="6h", tz="UTC"))


def _make_signal(
    bias: str = "long",
    price_lo: float = 100.0,
    price_hi: float = 110.0,
    confirmations: Optional[list] = None,
) -> SignalCandidate:
    er = EntryRegion(price_low=price_lo, price_high=price_hi)
    if bias == "long":
        inv = [InvalidationRule(condition="close_below_zone", price_level=90.0)]
    elif bias == "short":
        inv = [InvalidationRule(condition="close_above_zone", price_level=130.0)]
    else:
        inv = []
    return SignalCandidate(
        signal_id="gate_test",
        dataset_version="test",
        timeframe_context="1D primary / 6H confirm",
        zone_id="z1",
        bias=bias,
        entry_region=er,
        invalidation=inv,
        confirmations_required=confirmations or [],
        quality_score=0.5,
        provenance=["p1"],
    )


# ── GatingResult tests ────────────────────────────────────────────────────────


def test_gating_result_to_dict_keys():
    result = GatingResult(
        signal_id="s1",
        bar_time=_TS_BASE,
        passed=True,
        n_required=1,
        n_passed=1,
    )
    d = result.to_dict()
    for key in [
        "signal_id", "bar_time", "passed", "n_required", "n_passed",
        "check_names", "check_passed", "check_reasons", "metadata",
    ]:
        assert key in d, f"Missing key: {key}"


# ── evaluate_confirmation_gate tests ─────────────────────────────────────────


def test_gate_empty_slice_returns_fail():
    signal = _make_signal(confirmations=["candle_direction"])
    result = evaluate_confirmation_gate(signal, pd.DataFrame(), missing_bar_count=0)
    assert result.passed is False
    assert "Empty" in result.metadata.get("reason", "")


def test_gate_no_confirmations_required_passes():
    """When confirmations_required is empty, gate should pass trivially."""
    signal = _make_signal(confirmations=[])
    df = _make_ohlcv(n=10)
    result = evaluate_confirmation_gate(signal, df)
    assert result.passed is True
    assert result.n_required == 0
    assert result.n_passed == 0


def test_gate_long_bullish_bars_passes():
    """Long signal + bullish bars → candle_direction check passes → gate passes."""
    signal = _make_signal(bias="long", confirmations=["candle_direction"])
    df = _make_ohlcv(n=10, bullish=True)
    result = evaluate_confirmation_gate(signal, df)
    assert result.passed is True
    assert result.n_passed == 1


def test_gate_long_bearish_bars_may_fail():
    """Long signal with close well below mid of entry zone → candle_direction may fail.

    The entry zone is [100, 110], mid=105.
    Bearish bars: close = open - 1.  open starts at 100, so close starts at 99.
    For the last bar: open ≈ 104.75, close ≈ 103.75.
    close(103.75) < open(104.75) (bearish body) AND close(103.75) < mid(105) → FAIL.
    """
    # Use a zone with very high midpoint so bearish bars are below mid
    signal = _make_signal(bias="long", price_lo=200.0, price_hi=300.0, confirmations=["candle_direction"])
    df = _make_ohlcv(n=10, base=100.0, bullish=False)
    result = evaluate_confirmation_gate(signal, df)
    # close < open (bearish) AND close < mid(250) → should fail
    assert result.passed is False
    assert result.n_passed == 0


def test_gate_neutral_signal_candle_direction_fails():
    """Neutral signal's candle_direction check is 'not applicable' → gate fails."""
    signal = _make_signal(bias="neutral", confirmations=["candle_direction"])
    df = _make_ohlcv(n=10, bullish=True)
    result = evaluate_confirmation_gate(signal, df)
    # candle_direction on neutral always returns passed=False
    assert result.passed is False


def test_gate_lookback_limits_bars_seen():
    """Gate with lookback=3 should see only the last 3 bars, not all 20."""
    signal = _make_signal(bias="long", confirmations=["candle_direction"])
    df = _make_ohlcv(n=20, bullish=True)
    result = evaluate_confirmation_gate(signal, df, lookback=3)
    assert result.metadata["n_bars_in_slice"] == 3
    assert result.metadata["lookback"] == 3


def test_gate_metadata_contains_expected_keys():
    signal = _make_signal(bias="long", confirmations=["candle_direction"])
    df = _make_ohlcv(n=10)
    result = evaluate_confirmation_gate(signal, df, lookback=5, missing_bar_count=2)
    meta = result.metadata
    assert "lookback" in meta
    assert "missing_bar_count" in meta
    assert meta["missing_bar_count"] == 2
    assert "n_bars_in_slice" in meta
    assert "confirmations_required" in meta


# ── No-lookahead timing tests ─────────────────────────────────────────────────


def test_gate_no_lookahead_future_bars_not_used():
    """Gate at bar i must not use bars after i.

    We simulate a scenario where bars 0-4 are all bullish (good for long gate),
    but the entry zone has a very high midpoint (mid=1050) so the bullish
    bars at ~100-104 are below mid and have mixed candle_direction results.

    Key insight: candle_direction for long passes if bullish_body OR close>mid.
    We'll use a setup where:
    - bars 0-4: bullish body (close > open), so gate passes on first 5 bars
    - bars 5-9: explicitly bearish body AND close < mid (so gate fails on last 5 bars)
    - show gate is evaluated on the passed slice, not lookahead
    """
    # Zone [1000, 1100], mid=1050. Bearish bars at open~1055, close~1040 → close<mid, bearish body
    signal = _make_signal(bias="long", price_lo=1000.0, price_hi=1100.0, confirmations=["candle_direction"])

    # First 5 bars: open=1051+i, close=1060+i (bullish body, close > mid=1050)
    bullish_rows = [
        {"open": 1051.0 + i, "high": 1070.0 + i, "low": 1040.0 + i, "close": 1060.0 + i, "volume": 1.0}
        for i in range(5)
    ]
    # Last 5 bars: open=1060+i, close=1040+i (bearish body, close < mid=1050)
    bearish_rows = [
        {"open": 1060.0 + i, "high": 1070.0 + i, "low": 1030.0 + i, "close": 1040.0 + i, "volume": 1.0}
        for i in range(5)
    ]

    ts = pd.date_range(_TS_BASE, periods=10, freq="6h", tz="UTC")
    df_full = pd.DataFrame(bullish_rows + bearish_rows, index=ts)

    # Evaluate gate using only first 5 bars (bar index 0..4)
    gate_slice = df_full.iloc[:5]
    result_first5 = evaluate_confirmation_gate(signal, gate_slice, lookback=5)
    # Last bar of first-5: open=1055, close=1064 — bullish body AND close>mid → passes
    assert result_first5.passed is True

    # Evaluate gate using full 10 bars with lookback=3 — last 3 bars are bearish rows
    # Last 3 bearish: open=1061..1063, close=1041..1043 → bearish body, close<mid=1050
    result_full = evaluate_confirmation_gate(signal, df_full, lookback=3)
    # Last bar of bearish section: open=1064, close=1044 → bearish_body=True(1044<1064) but close(1044)<mid(1050)
    # candle_direction for long: passed = bullish_body OR above_mid
    # bullish_body = 1044 > 1064? No. above_mid = 1044 > 1050? No. → FAIL
    assert result_full.passed is False


# ── Integration: simulate_signal_on_6h with gating ───────────────────────────


def _make_6h_df_entering_zone(
    n: int = 20,
    entry_lo: float = 100.0,
    entry_hi: float = 110.0,
    bullish: bool = True,
) -> pd.DataFrame:
    """Build a df where bar 5's close enters [entry_lo, entry_hi]."""
    rows = []
    ts = pd.date_range(_TS_BASE, periods=n, freq="6h", tz="UTC")
    for i in range(n):
        if i == 5:
            # Bar 5: close inside zone
            o = entry_lo - 5
            c = (entry_lo + entry_hi) / 2
        else:
            o = 50.0 + i
            if bullish:
                c = o + 1.0
            else:
                c = o - 1.0
        rows.append({"open": o, "high": max(o, c) + 2, "low": min(o, c) - 2, "close": c, "volume": 1.0})
    return pd.DataFrame(rows, index=ts)


def test_simulate_gating_disabled_allows_entry():
    """When gating is disabled, entry should occur regardless of conf checks."""
    # Signal requires candle_direction; data at bar 5 is bearish
    signal = _make_signal(
        bias="long",
        price_lo=100.0,
        price_hi=110.0,
        confirmations=["candle_direction"],
    )
    # Bearish data except bar 5 which closes inside zone
    df = _make_6h_df_entering_zone(n=25, entry_lo=100.0, entry_hi=110.0, bullish=False)

    config = BacktestConfig(use_confirmation_gating=False)
    trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=config)
    # Gate disabled → entry should occur (trade is not None)
    assert trade is not None


def test_simulate_gating_enabled_blocks_entry_when_all_bars_bearish():
    """When gating is enabled and bars at the trigger point fail candle_direction,
    entry is blocked.

    For long candle_direction to fail: close <= open (bearish body) AND close <= mid.
    Entry zone: [500, 600], mid=550.
    Bar 5 closes inside zone with bearish body AND close < mid:
        open=502, close=501 → bearish body (501<502), close(501)<mid(550) → FAIL.
    All other bars are also bearish and below mid → gate never passes.
    """
    signal = _make_signal(
        bias="long",
        price_lo=500.0,
        price_hi=600.0,
        confirmations=["candle_direction"],
    )

    rows = []
    ts = pd.date_range(_TS_BASE, periods=25, freq="6h", tz="UTC")
    for i in range(25):
        if i == 5:
            # close inside [500, 600] but bearish body and below mid=550
            o = 502.0
            c = 501.0  # bearish (c < o) and c(501) < mid(550)
        else:
            # Well below zone, bearish bars
            o = 200.0 + i
            c = o - 5.0  # bearish body
        rows.append({"open": o, "high": max(o, c) + 2, "low": min(o, c) - 2, "close": c, "volume": 1.0})
    df = pd.DataFrame(rows, index=ts)

    config = BacktestConfig(use_confirmation_gating=True, confirmation_lookback=4)
    trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=config)
    # Gate should fail: last 4 bars before/at bar 5 are bearish and close < mid=550
    # Entry blocked → None
    assert trade is None


def test_simulate_gating_enabled_allows_entry_when_confirmations_pass():
    """When gating enabled and candle_direction passes (bullish bars), entry occurs."""
    # Entry zone [100, 110], bullish bars → close > open AND close > mid(105)
    signal = _make_signal(
        bias="long",
        price_lo=100.0,
        price_hi=110.0,
        confirmations=["candle_direction"],
    )
    # Build bars that are bullish; bar 10 closes inside zone
    rows = []
    ts = pd.date_range(_TS_BASE, periods=30, freq="6h", tz="UTC")
    for i in range(30):
        if i == 10:
            o = 99.0
            c = 105.0  # inside [100, 110]
        else:
            o = 90.0 + i * 0.3
            c = o + 1.5  # bullish
        rows.append({"open": o, "high": max(o, c) + 1, "low": min(o, c) - 1, "close": c, "volume": 1.0})
    df = pd.DataFrame(rows, index=ts)

    config = BacktestConfig(use_confirmation_gating=True, confirmation_lookback=5)
    trade = simulate_signal_on_6h(signal, df, equity=100_000.0, config=config)
    # Gate passes (recent bars bullish) → entry should occur
    assert trade is not None
