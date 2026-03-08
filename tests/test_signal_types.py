"""
tests/test_signal_types.py

Tests for signals/signal_types.py — SignalCandidate, EntryRegion,
InvalidationRule, ConfirmationResult.

Coverage
--------
- Construction and field validation (valid/invalid inputs)
- Deterministic signal_id generation
- to_dict() round-trip (JSON-serialisable)
- EntryRegion mid_price()
- InvalidationRule buffer/condition constraints
- ConfirmationResult to_dict()
"""

from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from signals.signal_types import (
    ConfirmationResult,
    EntryRegion,
    InvalidationRule,
    SignalCandidate,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_entry(low=100.0, high=110.0, t_lo=None, t_hi=None) -> EntryRegion:
    return EntryRegion(price_low=low, price_high=high, time_earliest=t_lo, time_latest=t_hi)


def _make_signal(
    bias="long",
    zone_id="abc123",
    dataset_version="proc_TEST_v1",
    quality_score=0.5,
    entry=None,
    invalidation=None,
    confirmations=None,
    provenance=None,
    signal_id="",
) -> SignalCandidate:
    return SignalCandidate(
        signal_id=signal_id,
        dataset_version=dataset_version,
        timeframe_context="1D primary / 6H confirm",
        zone_id=zone_id,
        bias=bias,
        entry_region=entry or _make_entry(),
        invalidation=invalidation or [],
        confirmations_required=confirmations or ["candle_direction"],
        quality_score=quality_score,
        provenance=provenance or ["proj_001"],
    )


# ── EntryRegion ───────────────────────────────────────────────────────────────


class TestEntryRegion:
    def test_basic_construction(self):
        er = EntryRegion(price_low=100.0, price_high=200.0)
        assert er.price_low == 100.0
        assert er.price_high == 200.0
        assert er.time_earliest is None
        assert er.time_latest is None

    def test_mid_price(self):
        er = EntryRegion(price_low=100.0, price_high=200.0)
        assert er.mid_price() == 150.0

    def test_mid_price_single_point(self):
        er = EntryRegion(price_low=50.0, price_high=50.0)
        assert er.mid_price() == 50.0

    def test_with_time_window(self):
        t_lo = pd.Timestamp("2025-01-01", tz="UTC")
        t_hi = pd.Timestamp("2025-02-01", tz="UTC")
        er = EntryRegion(price_low=100.0, price_high=200.0, time_earliest=t_lo, time_latest=t_hi)
        assert er.time_earliest == t_lo
        assert er.time_latest == t_hi

    def test_invalid_price_order(self):
        with pytest.raises(ValueError, match="price_low"):
            EntryRegion(price_low=200.0, price_high=100.0)

    def test_invalid_time_order(self):
        t_lo = pd.Timestamp("2025-03-01", tz="UTC")
        t_hi = pd.Timestamp("2025-01-01", tz="UTC")
        with pytest.raises(ValueError, match="time_earliest"):
            EntryRegion(price_low=100.0, price_high=200.0, time_earliest=t_lo, time_latest=t_hi)

    def test_to_dict_no_time(self):
        er = EntryRegion(price_low=100.0, price_high=200.0)
        d = er.to_dict()
        assert d["price_low"] == 100.0
        assert d["price_high"] == 200.0
        assert d["time_earliest"] is None
        assert d["time_latest"] is None

    def test_to_dict_with_time(self):
        t = pd.Timestamp("2025-06-01", tz="UTC")
        er = EntryRegion(price_low=10.0, price_high=20.0, time_earliest=t, time_latest=t)
        d = er.to_dict()
        assert d["time_earliest"] == str(t)
        assert d["time_latest"] == str(t)

    def test_equal_price_bounds_allowed(self):
        er = EntryRegion(price_low=100.0, price_high=100.0)
        assert er.mid_price() == 100.0


# ── InvalidationRule ──────────────────────────────────────────────────────────


class TestInvalidationRule:
    def test_close_below_zone(self):
        r = InvalidationRule(condition="close_below_zone", price_level=90.0)
        assert r.condition == "close_below_zone"
        assert r.price_level == 90.0
        assert r.buffer == 0.0

    def test_close_above_zone(self):
        r = InvalidationRule(condition="close_above_zone", price_level=110.0, buffer=5.0)
        assert r.buffer == 5.0

    def test_time_expired(self):
        t = pd.Timestamp("2026-01-01", tz="UTC")
        r = InvalidationRule(condition="time_expired", time_cutoff=t)
        assert r.time_cutoff == t

    def test_invalid_condition(self):
        with pytest.raises(ValueError, match="condition must be one of"):
            InvalidationRule(condition="close_sideways")

    def test_negative_buffer(self):
        with pytest.raises(ValueError, match="buffer must be >= 0"):
            InvalidationRule(condition="close_below_zone", buffer=-1.0)

    def test_to_dict(self):
        r = InvalidationRule(condition="close_below_zone", price_level=95.0, buffer=2.0)
        d = r.to_dict()
        assert d["condition"] == "close_below_zone"
        assert d["price_level"] == 95.0
        assert d["buffer"] == 2.0
        assert d["time_cutoff"] is None

    def test_to_dict_time_expired(self):
        t = pd.Timestamp("2026-06-01", tz="UTC")
        r = InvalidationRule(condition="time_expired", time_cutoff=t)
        d = r.to_dict()
        assert d["time_cutoff"] == str(t)


# ── SignalCandidate ───────────────────────────────────────────────────────────


class TestSignalCandidate:
    def test_basic_long(self):
        s = _make_signal(bias="long")
        assert s.bias == "long"
        assert s.quality_score == 0.5

    def test_basic_short(self):
        s = _make_signal(bias="short")
        assert s.bias == "short"

    def test_neutral_signal(self):
        s = _make_signal(bias="neutral", quality_score=0.6)
        assert s.bias == "neutral"

    def test_invalid_bias(self):
        with pytest.raises(ValueError, match="bias must be one of"):
            _make_signal(bias="sideways")

    def test_quality_score_zero(self):
        s = _make_signal(quality_score=0.0)
        assert s.quality_score == 0.0

    def test_quality_score_one(self):
        s = _make_signal(quality_score=1.0)
        assert s.quality_score == 1.0

    def test_quality_score_out_of_range_high(self):
        with pytest.raises(ValueError, match="quality_score must be in"):
            _make_signal(quality_score=1.1)

    def test_quality_score_out_of_range_low(self):
        with pytest.raises(ValueError, match="quality_score must be in"):
            _make_signal(quality_score=-0.01)

    def test_signal_id_auto_generated(self):
        s = _make_signal(signal_id="")
        assert len(s.signal_id) == 16
        assert all(c in "0123456789abcdef" for c in s.signal_id)

    def test_signal_id_deterministic(self):
        """Same zone_id + bias + dataset_version always produces the same signal_id."""
        s1 = _make_signal(signal_id="", zone_id="z1", bias="long", dataset_version="v1")
        s2 = _make_signal(signal_id="", zone_id="z1", bias="long", dataset_version="v1")
        assert s1.signal_id == s2.signal_id

    def test_signal_id_differs_by_bias(self):
        s_long = _make_signal(signal_id="", zone_id="z1", bias="long", dataset_version="v1")
        s_short = _make_signal(signal_id="", zone_id="z1", bias="short", dataset_version="v1")
        assert s_long.signal_id != s_short.signal_id

    def test_signal_id_differs_by_zone(self):
        s1 = _make_signal(signal_id="", zone_id="z1", bias="long", dataset_version="v1")
        s2 = _make_signal(signal_id="", zone_id="z2", bias="long", dataset_version="v1")
        assert s1.signal_id != s2.signal_id

    def test_explicit_signal_id_preserved(self):
        s = _make_signal(signal_id="myid123abc")
        assert s.signal_id == "myid123abc"

    def test_to_dict_structure(self):
        inv = [InvalidationRule(condition="close_below_zone", price_level=90.0)]
        s = _make_signal(
            bias="long",
            zone_id="zone_abc",
            dataset_version="proc_TEST_v1",
            quality_score=0.75,
            invalidation=inv,
            confirmations=["candle_direction", "zone_rejection"],
            provenance=["proj_001", "module:jttl"],
        )
        d = s.to_dict()
        assert d["bias"] == "long"
        assert d["zone_id"] == "zone_abc"
        assert d["dataset_version"] == "proc_TEST_v1"
        assert d["quality_score"] == 0.75
        assert len(d["invalidation"]) == 1
        assert d["confirmations_required"] == ["candle_direction", "zone_rejection"]
        assert "entry_region" in d
        assert "provenance" in d

    def test_to_dict_is_json_serialisable(self):
        import json
        s = _make_signal()
        d = s.to_dict()
        json_str = json.dumps(d)  # should not raise
        assert isinstance(json_str, str)

    def test_metadata_default_empty_dict(self):
        s = _make_signal()
        assert s.metadata == {}

    def test_notes_default_empty(self):
        s = _make_signal()
        assert s.notes == ""


# ── ConfirmationResult ────────────────────────────────────────────────────────


class TestConfirmationResult:
    def test_basic_pass(self):
        r = ConfirmationResult(
            signal_id="abc123",
            check_name="candle_direction",
            passed=True,
            reason="Bullish bar.",
        )
        assert r.passed is True
        assert r.check_name == "candle_direction"

    def test_basic_fail(self):
        r = ConfirmationResult(
            signal_id="abc123",
            check_name="zone_rejection",
            passed=False,
            reason="No zone touch found.",
        )
        assert r.passed is False

    def test_to_dict(self):
        r = ConfirmationResult(
            signal_id="sig1",
            check_name="candle_direction",
            passed=True,
            reason="OK",
            metadata={"bar_close": 50000.0},
        )
        d = r.to_dict()
        assert d["signal_id"] == "sig1"
        assert d["check_name"] == "candle_direction"
        assert d["passed"] is True
        assert d["reason"] == "OK"
        assert d["metadata"]["bar_close"] == 50000.0

    def test_to_dict_is_json_serialisable(self):
        import json
        r = ConfirmationResult(
            signal_id="s1", check_name="c1", passed=False, reason="test"
        )
        d = r.to_dict()
        json.dumps(d)  # should not raise
