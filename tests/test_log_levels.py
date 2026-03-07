"""
tests/test_log_levels.py

Tests for modules/log_levels.py.

Coverage
--------
- log_price: known values, p=1 → 0, p=e → 1, negative/zero raises
- log_return: known values, round-trip, symmetry, invalid inputs raise
- log_slope: known values, matches impulse.py convention, delta_t=0 raises,
  non-positive p0 raises, non-positive implied p1 raises
- log_scale_basis: known value, matches adjusted_angles.py convention
- Determinism: repeated calls produce identical results
- Consistency with Phase 3A adjusted_angles log-mode convention
"""

from __future__ import annotations

import math

import pytest

from modules.log_levels import (
    log_price,
    log_return,
    log_scale_basis,
    log_slope,
)


# ── log_price ─────────────────────────────────────────────────────────────────


class TestLogPrice:
    def test_price_1_returns_0(self):
        assert log_price(1.0) == pytest.approx(0.0, abs=1e-15)

    def test_price_e_returns_1(self):
        assert log_price(math.e) == pytest.approx(1.0, rel=1e-10)

    def test_price_100(self):
        assert log_price(100.0) == pytest.approx(math.log(100.0), rel=1e-10)

    def test_price_10000(self):
        assert log_price(10000.0) == pytest.approx(math.log(10000.0), rel=1e-10)

    def test_price_fractional(self):
        assert log_price(0.5) == pytest.approx(math.log(0.5), rel=1e-10)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            log_price(0.0)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            log_price(-1.0)

    def test_very_small_positive(self):
        """Very small positive price should work (no error)."""
        result = log_price(1e-10)
        assert math.isfinite(result)

    def test_deterministic(self):
        assert log_price(50000.0) == log_price(50000.0)


# ── log_return ────────────────────────────────────────────────────────────────


class TestLogReturn:
    def test_equal_prices_returns_0(self):
        assert log_return(100.0, 100.0) == pytest.approx(0.0, abs=1e-15)

    def test_doubling_returns_log_2(self):
        assert log_return(100.0, 200.0) == pytest.approx(math.log(2.0), rel=1e-10)

    def test_halving_returns_neg_log_2(self):
        assert log_return(200.0, 100.0) == pytest.approx(-math.log(2.0), rel=1e-10)

    def test_sign_positive_for_gain(self):
        assert log_return(100.0, 150.0) > 0

    def test_sign_negative_for_loss(self):
        assert log_return(150.0, 100.0) < 0

    def test_antisymmetry(self):
        """log_return(p0, p1) == -log_return(p1, p0)."""
        r_fwd = log_return(100.0, 200.0)
        r_rev = log_return(200.0, 100.0)
        assert r_fwd == pytest.approx(-r_rev, rel=1e-10)

    def test_additivity(self):
        """log_return(p0, p2) == log_return(p0, p1) + log_return(p1, p2)."""
        p0, p1, p2 = 100.0, 150.0, 225.0
        assert log_return(p0, p2) == pytest.approx(
            log_return(p0, p1) + log_return(p1, p2), rel=1e-10
        )

    def test_p0_zero_raises(self):
        with pytest.raises(ValueError):
            log_return(0.0, 100.0)

    def test_p0_negative_raises(self):
        with pytest.raises(ValueError):
            log_return(-50.0, 100.0)

    def test_p1_zero_raises(self):
        with pytest.raises(ValueError):
            log_return(100.0, 0.0)

    def test_p1_negative_raises(self):
        with pytest.raises(ValueError):
            log_return(100.0, -50.0)

    def test_known_btc_values(self):
        """log_return(3000, 60000) is about 2.996 (≈ 20x gain in log space)."""
        lr = log_return(3000.0, 60000.0)
        assert lr == pytest.approx(math.log(60000.0 / 3000.0), rel=1e-10)
        assert lr > 0

    def test_deterministic(self):
        assert log_return(100.0, 200.0) == log_return(100.0, 200.0)


# ── log_slope ─────────────────────────────────────────────────────────────────


class TestLogSlope:
    def test_unit_move_over_1_bar(self):
        """delta_p=0 → slope=0."""
        assert log_slope(0.0, 100.0, 1) == pytest.approx(0.0, abs=1e-15)

    def test_known_value(self):
        """log_slope(100, 100, 1) = log(2) / 1 = log(2)."""
        assert log_slope(100.0, 100.0, 1) == pytest.approx(math.log(2.0), rel=1e-10)

    def test_delta_t_2(self):
        """Dividing by delta_t=2 halves the per-bar slope."""
        assert log_slope(100.0, 100.0, 2) == pytest.approx(
            math.log(2.0) / 2.0, rel=1e-10
        )

    def test_matches_impulse_convention(self):
        """
        Verify log_slope matches modules/impulse.py convention:
            slope_log = log(extreme / origin) / delta_t
        """
        origin = 47.70
        extreme = 198.0
        delta_t = 28
        delta_p = extreme - origin
        # impulse.py formula
        expected = math.log(extreme / origin) / delta_t
        assert log_slope(delta_p, origin, delta_t) == pytest.approx(expected, rel=1e-10)

    def test_upward_impulse_positive_slope(self):
        assert log_slope(50.0, 100.0, 10) > 0

    def test_downward_impulse_negative_slope(self):
        assert log_slope(-50.0, 200.0, 10) < 0

    def test_delta_t_zero_raises(self):
        with pytest.raises(ValueError):
            log_slope(10.0, 100.0, 0)

    def test_p0_zero_raises(self):
        with pytest.raises(ValueError):
            log_slope(10.0, 0.0, 5)

    def test_p0_negative_raises(self):
        with pytest.raises(ValueError):
            log_slope(10.0, -100.0, 5)

    def test_implied_p1_nonpositive_raises(self):
        """delta_p = -200 with p0 = 100 → p1 = -100 → should raise."""
        with pytest.raises(ValueError):
            log_slope(-200.0, 100.0, 5)

    def test_implied_p1_zero_raises(self):
        """delta_p = -100 with p0 = 100 → p1 = 0 → should raise."""
        with pytest.raises(ValueError):
            log_slope(-100.0, 100.0, 5)

    def test_deterministic(self):
        assert log_slope(50.0, 100.0, 10) == log_slope(50.0, 100.0, 10)


# ── log_scale_basis ───────────────────────────────────────────────────────────


class TestLogScaleBasis:
    def test_known_value(self):
        """log_scale_basis(100, 1000) = log(1 + 100/1000) = log(1.1)."""
        ppb = 100.0
        origin = 1000.0
        expected = math.log(1.0 + ppb / origin)
        assert log_scale_basis(ppb, origin) == pytest.approx(expected, rel=1e-10)

    def test_matches_adjusted_angles_convention(self):
        """
        Verify that log_scale_basis matches the log_ppb formula in
        modules/adjusted_angles.py:
            log_ppb = math.log(1.0 + ppb / origin_price)
        This is the critical consistency check with Phase 3A.
        """
        ppb = 897.0       # realistic median ATR for 1D BTC/USD
        origin = 30000.0  # a plausible BTC origin price
        # adjusted_angles.py formula (copied verbatim):
        log_ppb_angles = math.log(1.0 + ppb / origin)
        # log_levels.py wrapper:
        log_ppb_levels = log_scale_basis(ppb, origin)
        assert log_ppb_levels == pytest.approx(log_ppb_angles, rel=1e-15)

    def test_positive_result(self):
        assert log_scale_basis(500.0, 10000.0) > 0

    def test_ppb_zero_raises(self):
        with pytest.raises(ValueError):
            log_scale_basis(0.0, 100.0)

    def test_ppb_negative_raises(self):
        with pytest.raises(ValueError):
            log_scale_basis(-1.0, 100.0)

    def test_origin_zero_raises(self):
        with pytest.raises(ValueError):
            log_scale_basis(100.0, 0.0)

    def test_origin_negative_raises(self):
        with pytest.raises(ValueError):
            log_scale_basis(100.0, -1000.0)

    def test_small_ppb_relative_to_origin(self):
        """For small ppb/origin, result ≈ ppb/origin (first-order approx)."""
        ppb = 1.0
        origin = 10000.0
        result = log_scale_basis(ppb, origin)
        approx_linear = ppb / origin
        # log(1+x) ≈ x for small x; check they are close
        assert abs(result - approx_linear) < 1e-8

    def test_deterministic(self):
        assert log_scale_basis(897.0, 30000.0) == log_scale_basis(897.0, 30000.0)
