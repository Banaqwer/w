"""
tests/test_confirmations.py

Tests for signals/confirmations.py — check_candle_direction, check_zone_rejection,
check_strict_multi_candle, run_all_confirmations.

Coverage
--------
- Empty OHLCV slice → passed=False with reason
- Missing required columns → passed=False
- check_candle_direction:
  - neutral bias → not applicable (passed=False)
  - long: bullish body (close > open) → pass
  - long: close above midpoint → pass even if open > close
  - long: close below open AND below midpoint → fail
  - short: bearish body (close < open) → pass
  - short: close below midpoint → pass even if close > open
  - short: close above open AND above midpoint → fail
  - missing_bar_count > 0: gap noted in metadata
- check_zone_rejection:
  - neutral bias → not applicable
  - long: price touches zone and closes above zone_lo → pass
  - long: price never touches zone → fail
  - long: price touches zone but closes below zone_lo → fail
  - short: price touches zone high and closes below zone_hi → pass
  - missing bars recorded in metadata
- check_strict_multi_candle:
  - neutral → not applicable
  - not enough bars → fail with reason
  - n consecutive bullish for long → pass
  - one non-bullish in N → fail
  - n consecutive bearish for short → pass
  - one non-bearish → fail
- run_all_confirmations:
  - runs all named checks
  - unknown check name → passed=False
  - missing_bar_count passed through
- Gap-policy: missing_bar_count > 0 reflected in metadata
"""

from __future__ import annotations

from typing import List

import pandas as pd
import pytest

from signals.confirmations import (
    check_candle_direction,
    check_strict_multi_candle,
    check_zone_rejection,
    run_all_confirmations,
)
from signals.signal_types import EntryRegion, InvalidationRule, SignalCandidate


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_signal(
    bias: str = "long",
    price_low: float = 100.0,
    price_high: float = 110.0,
    confirmations: List[str] = None,
    zone_id: str = "z1",
) -> SignalCandidate:
    if confirmations is None:
        confirmations = ["candle_direction", "zone_rejection"]
    return SignalCandidate(
        signal_id=f"sig_{bias}_{zone_id}",
        dataset_version="proc_TEST_v1",
        timeframe_context="1D primary / 6H confirm",
        zone_id=zone_id,
        bias=bias,
        entry_region=EntryRegion(price_low=price_low, price_high=price_high),
        invalidation=[],
        confirmations_required=confirmations,
        quality_score=0.5,
        provenance=[],
    )


def _make_ohlcv(rows: List[dict]) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame from a list of dicts."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    # Add a simple integer index (deterministic)
    return df.reset_index(drop=True)


def _single_bar(open_: float, high: float, low: float, close: float) -> pd.DataFrame:
    return _make_ohlcv([{"open": open_, "high": high, "low": low, "close": close}])


# ── check_candle_direction ────────────────────────────────────────────────────


class TestCandleDirection:
    def test_empty_slice_fails(self):
        signal = _make_signal("long")
        result = check_candle_direction(signal, pd.DataFrame())
        assert result.passed is False
        assert "empty" in result.reason.lower()

    def test_missing_column_fails(self):
        signal = _make_signal("long")
        df = pd.DataFrame([{"open": 100, "high": 110, "low": 90}])  # missing close
        result = check_candle_direction(signal, df)
        assert result.passed is False

    def test_neutral_not_applicable(self):
        signal = _make_signal("neutral")
        df = _single_bar(100, 110, 90, 105)
        result = check_candle_direction(signal, df)
        assert result.passed is False
        assert "neutral" in result.reason.lower()

    def test_long_bullish_bar_passes(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        # close > open → bullish body
        df = _single_bar(open_=95, high=108, low=93, close=107)
        result = check_candle_direction(signal, df)
        assert result.passed is True

    def test_long_close_above_midpoint_passes_even_if_bearish_body(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        # midpoint = 105; close=106 > mid=105, open=108 > close → bearish body
        df = _single_bar(open_=108, high=110, low=100, close=106)
        result = check_candle_direction(signal, df)
        # close above mid → pass
        assert result.passed is True

    def test_long_close_below_open_and_below_midpoint_fails(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        # mid = 105; close=103 < mid=105, close=103 < open=108
        df = _single_bar(open_=108, high=112, low=100, close=103)
        result = check_candle_direction(signal, df)
        assert result.passed is False

    def test_short_bearish_bar_passes(self):
        signal = _make_signal("short", price_low=100.0, price_high=110.0)
        # close < open → bearish body
        df = _single_bar(open_=108, high=112, low=100, close=103)
        result = check_candle_direction(signal, df)
        assert result.passed is True

    def test_short_close_below_midpoint_passes_even_if_bullish_body(self):
        signal = _make_signal("short", price_low=100.0, price_high=110.0)
        # mid=105; close=104 < mid=105 → pass; open=102 < close → bullish body
        df = _single_bar(open_=102, high=110, low=100, close=104)
        result = check_candle_direction(signal, df)
        assert result.passed is True

    def test_short_close_above_open_and_above_midpoint_fails(self):
        signal = _make_signal("short", price_low=100.0, price_high=110.0)
        # mid=105; close=108 > mid=105, close=108 > open=105
        df = _single_bar(open_=105, high=112, low=103, close=108)
        result = check_candle_direction(signal, df)
        assert result.passed is False

    def test_missing_bar_count_in_metadata(self):
        signal = _make_signal("long")
        df = _single_bar(95, 108, 93, 107)
        result = check_candle_direction(signal, df, missing_bar_count=1)
        assert result.metadata["missing_bar_count"] == 1
        assert "gap_note" in result.metadata

    def test_no_gap_no_gap_note(self):
        signal = _make_signal("long")
        df = _single_bar(95, 108, 93, 107)
        result = check_candle_direction(signal, df, missing_bar_count=0)
        assert "gap_note" not in result.metadata

    def test_uses_last_bar(self):
        """check_candle_direction should use the LAST row, not the first."""
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        # First bar bearish, last bar bullish
        df = _make_ohlcv([
            {"open": 110, "high": 112, "low": 100, "close": 105},  # bearish
            {"open": 100, "high": 115, "low": 98, "close": 112},   # bullish + above mid
        ])
        result = check_candle_direction(signal, df)
        assert result.passed is True


# ── check_zone_rejection ──────────────────────────────────────────────────────


class TestZoneRejection:
    def test_empty_slice_fails(self):
        signal = _make_signal("long")
        result = check_zone_rejection(signal, pd.DataFrame())
        assert result.passed is False

    def test_neutral_not_applicable(self):
        signal = _make_signal("neutral")
        df = _single_bar(100, 115, 95, 108)
        result = check_zone_rejection(signal, df)
        assert result.passed is False
        assert "neutral" in result.reason.lower()

    def test_long_bar_touches_zone_and_closes_above_low_passes(self):
        # zone: [100, 110]; bar low=100 touches zone, bar close=112 > zone_lo=100
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _single_bar(open_=115, high=115, low=100, close=112)
        result = check_zone_rejection(signal, df)
        assert result.passed is True

    def test_long_bar_never_touches_zone_fails(self):
        # zone: [100, 110]; bar low=111 > zone_hi=110 → never touched
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _single_bar(open_=115, high=118, low=111, close=116)
        result = check_zone_rejection(signal, df)
        assert result.passed is False

    def test_long_bar_touches_zone_but_closes_below_low_fails(self):
        # zone: [100, 110]; bar low=98 < zone_lo=100, close=99 < zone_lo=100
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _single_bar(open_=103, high=103, low=98, close=99)
        result = check_zone_rejection(signal, df)
        assert result.passed is False

    def test_short_bar_touches_zone_and_closes_below_high_passes(self):
        # zone: [100, 110]; bar high=110 touches zone, close=95 < zone_hi=110
        signal = _make_signal("short", price_low=100.0, price_high=110.0)
        df = _single_bar(open_=108, high=110, low=93, close=95)
        result = check_zone_rejection(signal, df)
        assert result.passed is True

    def test_short_bar_never_reaches_zone_low_fails(self):
        # zone: [100, 110]; bar high=99 < zone_lo=100 → never touched
        signal = _make_signal("short", price_low=100.0, price_high=110.0)
        df = _single_bar(open_=97, high=99, low=90, close=95)
        result = check_zone_rejection(signal, df)
        assert result.passed is False

    def test_multiple_bars_any_rejection_counts(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _make_ohlcv([
            {"open": 120, "high": 125, "low": 112, "close": 118},  # above zone, no touch
            {"open": 113, "high": 113, "low": 100, "close": 115},  # touches zone, closes above
        ])
        result = check_zone_rejection(signal, df)
        assert result.passed is True
        assert result.metadata["rejection_bars_found"] == 1

    def test_gap_recorded_in_metadata(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _single_bar(115, 115, 100, 112)
        result = check_zone_rejection(signal, df, missing_bar_count=1)
        assert result.metadata["missing_bar_count"] == 1
        assert "gap_note" in result.metadata


# ── check_strict_multi_candle ─────────────────────────────────────────────────


class TestStrictMultiCandle:
    def test_empty_slice_fails(self):
        signal = _make_signal("long")
        result = check_strict_multi_candle(signal, pd.DataFrame(), n_required=2)
        assert result.passed is False

    def test_neutral_not_applicable(self):
        signal = _make_signal("neutral")
        df = _make_ohlcv([
            {"open": 100, "high": 110, "low": 95, "close": 108},
            {"open": 108, "high": 115, "low": 105, "close": 113},
        ])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert result.passed is False
        assert "neutral" in result.reason.lower()

    def test_insufficient_bars_fails(self):
        signal = _make_signal("long")
        df = _single_bar(100, 110, 95, 108)
        result = check_strict_multi_candle(signal, df, n_required=3)
        assert result.passed is False
        assert "insufficient" in result.reason.lower()

    def test_long_all_bullish_passes(self):
        signal = _make_signal("long")
        df = _make_ohlcv([
            {"open": 100, "high": 110, "low": 95, "close": 108},   # bullish
            {"open": 108, "high": 115, "low": 105, "close": 113},  # bullish
        ])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert result.passed is True

    def test_long_one_bearish_fails(self):
        signal = _make_signal("long")
        df = _make_ohlcv([
            {"open": 100, "high": 110, "low": 95, "close": 108},  # bullish
            {"open": 110, "high": 112, "low": 100, "close": 105},  # bearish
        ])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert result.passed is False

    def test_short_all_bearish_passes(self):
        signal = _make_signal("short")
        df = _make_ohlcv([
            {"open": 110, "high": 112, "low": 100, "close": 102},  # bearish
            {"open": 102, "high": 103, "low": 95, "close": 97},    # bearish
        ])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert result.passed is True

    def test_short_one_bullish_fails(self):
        signal = _make_signal("short")
        df = _make_ohlcv([
            {"open": 110, "high": 112, "low": 100, "close": 102},  # bearish
            {"open": 100, "high": 108, "low": 98, "close": 106},   # bullish
        ])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert result.passed is False

    def test_uses_last_n_bars(self):
        """Only the last n_required bars matter."""
        signal = _make_signal("long")
        # 4 bars: first 2 bearish, last 2 bullish
        df = _make_ohlcv([
            {"open": 110, "high": 112, "low": 100, "close": 102},  # bearish (old)
            {"open": 102, "high": 104, "low": 96, "close": 98},    # bearish (old)
            {"open": 100, "high": 112, "low": 98, "close": 108},   # bullish (recent)
            {"open": 108, "high": 115, "low": 105, "close": 113},  # bullish (recent)
        ])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert result.passed is True

    def test_bar_results_in_metadata(self):
        signal = _make_signal("long")
        df = _make_ohlcv([
            {"open": 100, "high": 110, "low": 95, "close": 108},
            {"open": 108, "high": 115, "low": 105, "close": 113},
        ])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert "bar_results" in result.metadata
        assert len(result.metadata["bar_results"]) == 2

    def test_n_required_in_metadata(self):
        signal = _make_signal("long")
        df = _make_ohlcv([{"open": 100, "high": 110, "low": 95, "close": 108}])
        result = check_strict_multi_candle(signal, df, n_required=2)
        assert result.metadata["n_required"] == 2

    def test_missing_bar_count_in_metadata(self):
        signal = _make_signal("long")
        df = _make_ohlcv([
            {"open": 100, "high": 110, "low": 95, "close": 108},
            {"open": 108, "high": 115, "low": 105, "close": 113},
        ])
        result = check_strict_multi_candle(signal, df, missing_bar_count=3)
        assert result.metadata["missing_bar_count"] == 3


# ── run_all_confirmations ─────────────────────────────────────────────────────


class TestRunAllConfirmations:
    def test_runs_all_named_checks(self):
        signal = _make_signal(
            "long",
            price_low=100.0,
            price_high=110.0,
            confirmations=["candle_direction", "zone_rejection"],
        )
        df = _single_bar(open_=95, high=108, low=100, close=107)
        results = run_all_confirmations(signal, df, missing_bar_count=0)
        check_names = {r.check_name for r in results}
        assert "candle_direction" in check_names
        assert "zone_rejection" in check_names
        assert len(results) == 2

    def test_unknown_check_name_produces_fail(self):
        signal = _make_signal(
            "long",
            confirmations=["candle_direction", "unknown_check_42"],
        )
        df = _single_bar(95, 108, 93, 107)
        results = run_all_confirmations(signal, df)
        unknown = [r for r in results if r.check_name == "unknown_check_42"]
        assert len(unknown) == 1
        assert unknown[0].passed is False
        assert "Unknown" in unknown[0].reason

    def test_strict_multi_candle_dispatched(self):
        signal = _make_signal(
            "long",
            confirmations=["strict_multi_candle"],
        )
        df = _make_ohlcv([
            {"open": 100, "high": 110, "low": 95, "close": 108},
            {"open": 108, "high": 115, "low": 105, "close": 113},
        ])
        results = run_all_confirmations(signal, df, missing_bar_count=1)
        assert len(results) == 1
        assert results[0].check_name == "strict_multi_candle"

    def test_missing_bar_count_passed_through(self):
        signal = _make_signal(
            "long",
            confirmations=["candle_direction"],
        )
        df = _single_bar(95, 108, 93, 107)
        results = run_all_confirmations(signal, df, missing_bar_count=2)
        assert results[0].metadata["missing_bar_count"] == 2

    def test_empty_confirmations_list_returns_empty(self):
        signal = _make_signal("long", confirmations=[])
        df = _single_bar(95, 108, 93, 107)
        results = run_all_confirmations(signal, df)
        assert results == []

    def test_determinism(self):
        """Same inputs → same results."""
        signal = _make_signal(
            "long",
            confirmations=["candle_direction", "zone_rejection"],
        )
        df = _single_bar(95, 108, 100, 107)
        r1 = run_all_confirmations(signal, df)
        r2 = run_all_confirmations(signal, df)
        assert [r.passed for r in r1] == [r.passed for r in r2]
        assert [r.reason for r in r1] == [r.reason for r in r2]


# ── Gap-policy integration ────────────────────────────────────────────────────


class TestGapPolicyIntegration:
    def test_gap_flag_triggers_downgrade_note_in_candle_direction(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _single_bar(95, 108, 93, 107)
        result = check_candle_direction(signal, df, missing_bar_count=1)
        assert "gap_note" in result.metadata

    def test_no_gap_no_note_in_candle_direction(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _single_bar(95, 108, 93, 107)
        result = check_candle_direction(signal, df, missing_bar_count=0)
        assert "gap_note" not in result.metadata

    def test_gap_flag_triggers_note_in_zone_rejection(self):
        signal = _make_signal("long", price_low=100.0, price_high=110.0)
        df = _single_bar(115, 115, 100, 112)
        result = check_zone_rejection(signal, df, missing_bar_count=1)
        assert "gap_note" in result.metadata
