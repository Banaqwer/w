"""
tests/test_jttl.py

Tests for modules/jttl.py.

Coverage
--------
- theoretical_price: known-value checks, k=0, negative origin raises,
  zero origin, edge k values
- compute_jttl: basic construction, slope/intercept math, t1 placement,
  calendar_days basis, bars basis, invalid inputs raise, determinism
- JTTLLine.price_at: at t0, at t1, midpoint, before t0
- JTTLLine.time_at_price: at p0, at p1, flat-line returns None,
  round-trip with price_at
- JTTLLine.to_dict: all keys present
- horizon_bars override: sets basis="bars", horizon_days=horizon_bars
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd
import pytest

from modules.jttl import (
    JTTLLine,
    _CALENDAR_DAYS_PER_YEAR,
    compute_jttl,
    theoretical_price,
)

# ── Fixtures / helpers ────────────────────────────────────────────────────────

_T0 = pd.Timestamp("2020-01-01 00:00:00", tz="UTC")


def _make_jttl(
    origin_price: float = 100.0,
    k: float = 2.0,
    horizon_days: int = 365,
    horizon_bars: Optional[int] = None,
) -> JTTLLine:
    return compute_jttl(
        origin_time=_T0,
        origin_price=origin_price,
        k=k,
        horizon_days=horizon_days,
        horizon_bars=horizon_bars,
    )


# ── theoretical_price ────────────────────────────────────────────────────────

class TestTheoreticalPrice:
    def test_known_value_47_70_k2(self):
        """Example: origin=47.70, k=2.0 → (sqrt(47.70)+2)^2"""
        p0 = 47.70
        expected = (math.sqrt(p0) + 2.0) ** 2
        result = theoretical_price(p0, k=2.0)
        assert abs(result - expected) < 1e-10

    def test_known_value_100_k2(self):
        """origin=100, k=2 → (10+2)^2 = 144"""
        assert abs(theoretical_price(100.0, k=2.0) - 144.0) < 1e-10

    def test_known_value_100_k0(self):
        """k=0: output equals input"""
        assert abs(theoretical_price(100.0, k=0.0) - 100.0) < 1e-10

    def test_known_value_64_k4(self):
        """origin=64, k=4 → (8+4)^2 = 144"""
        assert abs(theoretical_price(64.0, k=4.0) - 144.0) < 1e-10

    def test_k_negative(self):
        """Negative k produces a lower target."""
        p1 = theoretical_price(100.0, k=-2.0)
        assert abs(p1 - (10.0 - 2.0) ** 2) < 1e-10
        assert p1 < 100.0

    def test_origin_zero_k_positive(self):
        """origin=0, k=2 → (0+2)^2 = 4"""
        assert abs(theoretical_price(0.0, k=2.0) - 4.0) < 1e-10

    def test_origin_negative_raises(self):
        with pytest.raises(ValueError, match="origin_price must be >= 0"):
            theoretical_price(-1.0)

    @pytest.mark.parametrize("p0", [1.0, 47.70, 100.0, 10000.0, 69000.0])
    def test_result_exceeds_origin_for_positive_k(self, p0):
        """For k > 0, theoretical price always > origin price."""
        assert theoretical_price(p0, k=2.0) > p0

    def test_deterministic(self):
        """Same inputs always produce the same output."""
        a = theoretical_price(12345.67, k=1.5)
        b = theoretical_price(12345.67, k=1.5)
        assert a == b


# ── compute_jttl ──────────────────────────────────────────────────────────────

class TestComputeJttl:
    def test_basic_construction(self):
        jl = _make_jttl()
        assert jl.p0 == 100.0
        assert jl.t0 == _T0
        assert jl.k == 2.0
        assert jl.horizon_days == 365.0
        assert jl.horizon_bars is None
        assert jl.basis == "calendar_days"

    def test_p1_matches_theoretical_price(self):
        jl = _make_jttl(origin_price=100.0, k=2.0)
        assert abs(jl.p1 - theoretical_price(100.0, k=2.0)) < 1e-10

    def test_t1_offset_365_days(self):
        jl = _make_jttl(horizon_days=365)
        expected_t1 = _T0 + pd.Timedelta(days=365)
        assert jl.t1 == expected_t1

    def test_slope_raw_formula(self):
        """slope_raw = (p1 - p0) / horizon_days"""
        jl = _make_jttl(origin_price=100.0, k=2.0, horizon_days=365)
        expected_slope = (jl.p1 - 100.0) / 365.0
        assert abs(jl.slope_raw - expected_slope) < 1e-12

    def test_intercept_raw_equals_p0(self):
        jl = _make_jttl(origin_price=100.0)
        assert jl.intercept_raw == 100.0

    def test_horizon_bars_overrides(self):
        jl = _make_jttl(horizon_bars=200)
        assert jl.horizon_bars == 200
        assert jl.horizon_days == 200.0
        assert jl.basis == "bars"
        assert jl.t1 == _T0 + pd.Timedelta(days=200)

    def test_calendar_days_basis_default(self):
        jl = _make_jttl()
        assert jl.basis == "calendar_days"

    def test_calendar_days_constant(self):
        assert _CALENDAR_DAYS_PER_YEAR == 365

    # ── Invalid inputs ─────────────────────────────────────────────────────

    def test_origin_price_zero_raises(self):
        with pytest.raises(ValueError, match="origin_price must be > 0"):
            compute_jttl(_T0, 0.0)

    def test_origin_price_negative_raises(self):
        with pytest.raises(ValueError, match="origin_price must be > 0"):
            compute_jttl(_T0, -10.0)

    def test_horizon_days_zero_raises(self):
        with pytest.raises(ValueError, match="horizon_days must be > 0"):
            compute_jttl(_T0, 100.0, horizon_days=0)

    def test_horizon_days_negative_raises(self):
        with pytest.raises(ValueError, match="horizon_days must be > 0"):
            compute_jttl(_T0, 100.0, horizon_days=-5)

    def test_horizon_bars_zero_raises(self):
        with pytest.raises(ValueError, match="horizon_bars must be > 0"):
            compute_jttl(_T0, 100.0, horizon_bars=0)

    def test_horizon_bars_negative_raises(self):
        with pytest.raises(ValueError, match="horizon_bars must be > 0"):
            compute_jttl(_T0, 100.0, horizon_bars=-1)

    # ── Determinism ────────────────────────────────────────────────────────

    def test_deterministic(self):
        a = _make_jttl(origin_price=47.70, k=2.0, horizon_days=365)
        b = _make_jttl(origin_price=47.70, k=2.0, horizon_days=365)
        assert a.p1 == b.p1
        assert a.slope_raw == b.slope_raw
        assert a.t1 == b.t1

    # ── Various origin prices ───────────────────────────────────────────────

    @pytest.mark.parametrize("p0", [1.0, 47.70, 100.0, 10_000.0, 69_000.0])
    def test_p1_gt_p0_for_positive_k(self, p0):
        jl = _make_jttl(origin_price=p0, k=2.0)
        assert jl.p1 > jl.p0

    @pytest.mark.parametrize("k", [0.5, 1.0, 2.0, 5.0])
    def test_slope_positive_for_positive_k(self, k):
        jl = _make_jttl(k=k)
        assert jl.slope_raw > 0.0


# ── JTTLLine.price_at ─────────────────────────────────────────────────────────

class TestPriceAt:
    def test_price_at_t0_equals_p0(self):
        jl = _make_jttl(origin_price=100.0)
        assert abs(jl.price_at(jl.t0) - jl.p0) < 1e-12

    def test_price_at_t1_equals_p1(self):
        jl = _make_jttl(origin_price=100.0)
        assert abs(jl.price_at(jl.t1) - jl.p1) < 1e-10

    def test_price_at_midpoint(self):
        """At the midpoint of the horizon, price should be the midpoint of p0/p1."""
        jl = _make_jttl(origin_price=100.0)
        t_mid = jl.t0 + pd.Timedelta(days=jl.horizon_days / 2)
        expected = (jl.p0 + jl.p1) / 2.0
        assert abs(jl.price_at(t_mid) - expected) < 1e-10

    def test_price_at_before_t0_extrapolates_down(self):
        """Before t0 with positive slope: price < p0."""
        jl = _make_jttl(origin_price=100.0, k=2.0)
        t_before = jl.t0 - pd.Timedelta(days=30)
        assert jl.price_at(t_before) < jl.p0

    def test_price_at_after_t1_extrapolates_up(self):
        """After t1 with positive slope: price > p1."""
        jl = _make_jttl(origin_price=100.0, k=2.0)
        t_after = jl.t1 + pd.Timedelta(days=30)
        assert jl.price_at(t_after) > jl.p1


# ── JTTLLine.time_at_price ────────────────────────────────────────────────────

class TestTimeAtPrice:
    def test_time_at_p0_equals_t0(self):
        jl = _make_jttl(origin_price=100.0)
        t = jl.time_at_price(jl.p0)
        assert t is not None
        # Should be very close to t0 (float precision)
        diff_seconds = abs((t - jl.t0).total_seconds())
        assert diff_seconds < 1.0

    def test_time_at_p1_equals_t1(self):
        jl = _make_jttl(origin_price=100.0)
        t = jl.time_at_price(jl.p1)
        assert t is not None
        diff_seconds = abs((t - jl.t1).total_seconds())
        assert diff_seconds < 1.0  # within 1 second

    def test_flat_line_returns_none(self):
        """k=0 → p1==p0 → slope_raw==0 → time_at_price returns None."""
        jl = _make_jttl(origin_price=100.0, k=0.0)
        assert jl.slope_raw == 0.0
        assert jl.time_at_price(100.0) is None

    def test_round_trip_price_at(self):
        """price_at(time_at_price(p)) should recover p."""
        jl = _make_jttl(origin_price=100.0, k=2.0)
        target_price = (jl.p0 + jl.p1) / 2.0
        t = jl.time_at_price(target_price)
        assert t is not None
        recovered = jl.price_at(t)
        assert abs(recovered - target_price) < 1e-10


# ── JTTLLine.to_dict ──────────────────────────────────────────────────────────

class TestToDict:
    def test_all_keys_present(self):
        jl = _make_jttl()
        d = jl.to_dict()
        for key in ("t0", "p0", "t1", "p1", "k", "horizon_days",
                    "horizon_bars", "slope_raw", "intercept_raw", "basis"):
            assert key in d, f"Missing key: {key}"

    def test_values_consistent(self):
        jl = _make_jttl(origin_price=100.0, k=2.0)
        d = jl.to_dict()
        assert d["p0"] == 100.0
        assert d["k"] == 2.0
        assert d["basis"] == "calendar_days"
        assert d["horizon_bars"] is None

    def test_bars_basis_in_dict(self):
        jl = _make_jttl(horizon_bars=180)
        d = jl.to_dict()
        assert d["basis"] == "bars"
        assert d["horizon_bars"] == 180


# ── Horizon mapping correctness ────────────────────────────────────────────────

class TestHorizonMapping:
    def test_365_calendar_days_default(self):
        jl = compute_jttl(_T0, 100.0)
        expected_t1 = _T0 + pd.Timedelta(days=365)
        assert jl.t1 == expected_t1
        assert jl.basis == "calendar_days"
        assert jl.horizon_days == 365.0

    def test_n_bars_horizon(self):
        jl = compute_jttl(_T0, 100.0, horizon_bars=180)
        expected_t1 = _T0 + pd.Timedelta(days=180)
        assert jl.t1 == expected_t1
        assert jl.basis == "bars"
        assert jl.horizon_days == 180.0
        assert jl.horizon_bars == 180

    def test_bars_and_days_equivalent_at_365(self):
        """For N=365, calendar_days and bars basis give the same t1."""
        jl_cal = compute_jttl(_T0, 100.0, horizon_days=365)
        jl_bar = compute_jttl(_T0, 100.0, horizon_bars=365)
        assert jl_cal.t1 == jl_bar.t1
        assert abs(jl_cal.slope_raw - jl_bar.slope_raw) < 1e-15

    def test_custom_horizon_days(self):
        jl = compute_jttl(_T0, 100.0, horizon_days=180)
        assert jl.horizon_days == 180.0
        assert jl.t1 == _T0 + pd.Timedelta(days=180)
