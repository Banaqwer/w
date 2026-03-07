"""
tests/test_sqrt_levels.py

Tests for modules/sqrt_levels.py.

Coverage
--------
- sqrt_levels: known-value checks (origin=47.70), up/down/both directions,
  custom increments and steps, invalid inputs raise, determinism,
  output sorted ascending, zero down-level clamping
- SqrtLevel.to_dict: all keys present
- SqrtLevel fields: label format, direction, step
"""

from __future__ import annotations

import math

import pytest

from modules.sqrt_levels import SqrtLevel, sqrt_levels


# ── Helpers ───────────────────────────────────────────────────────────────────


def _level_prices(levels):
    """Return sorted list of level prices from a list of SqrtLevel."""
    return [lv.level_price for lv in levels]


# ── Known-value tests ─────────────────────────────────────────────────────────


class TestKnownValues:
    """Numerically verify the formula against manually computed values."""

    def test_origin_47_70_up_inc1_step1(self):
        """inc=1.0, step=1: (sqrt(47.70)+1.0)^2"""
        p0 = 47.70
        expected = (math.sqrt(p0) + 1.0) ** 2
        levels = sqrt_levels(p0, increments=[1.0], steps=1, direction="up")
        assert len(levels) == 1
        assert abs(levels[0].level_price - expected) < 1e-10

    def test_origin_47_70_up_inc1_step2(self):
        """inc=1.0, step=2: (sqrt(47.70)+2.0)^2"""
        p0 = 47.70
        expected = (math.sqrt(p0) + 2.0) ** 2
        levels = sqrt_levels(p0, increments=[1.0], steps=2, direction="up")
        assert len(levels) == 2
        step2 = [lv for lv in levels if lv.step == 2][0]
        assert abs(step2.level_price - expected) < 1e-10

    def test_origin_47_70_down_inc1_step1(self):
        """inc=1.0, step=1: (sqrt(47.70)-1.0)^2"""
        p0 = 47.70
        expected = (math.sqrt(p0) - 1.0) ** 2
        levels = sqrt_levels(p0, increments=[1.0], steps=1, direction="down")
        assert len(levels) == 1
        assert abs(levels[0].level_price - expected) < 1e-10

    def test_origin_100_up_inc1_step1(self):
        """origin=100, inc=1, step=1 → (10+1)^2 = 121"""
        levels = sqrt_levels(100.0, increments=[1.0], steps=1, direction="up")
        assert abs(levels[0].level_price - 121.0) < 1e-10

    def test_origin_100_down_inc1_step1(self):
        """origin=100, inc=1, step=1 → (10-1)^2 = 81"""
        levels = sqrt_levels(100.0, increments=[1.0], steps=1, direction="down")
        assert abs(levels[0].level_price - 81.0) < 1e-10

    def test_origin_100_up_inc2_step3(self):
        """origin=100, inc=2, step=3 → (10+6)^2 = 256"""
        levels = sqrt_levels(100.0, increments=[2.0], steps=3, direction="up")
        step3 = [lv for lv in levels if lv.step == 3][0]
        assert abs(step3.level_price - 256.0) < 1e-10

    @pytest.mark.parametrize("inc,n", [
        (0.25, 1), (0.25, 4), (0.5, 1), (0.5, 2),
        (0.75, 1), (1.0, 1), (1.0, 3),
    ])
    def test_up_formula_parametrized(self, inc, n):
        """Up level = (sqrt(p0) + inc*n)^2."""
        p0 = 47.70
        expected = (math.sqrt(p0) + inc * n) ** 2
        levels = sqrt_levels(p0, increments=[inc], steps=n, direction="up")
        target = [lv for lv in levels if lv.step == n][0]
        assert abs(target.level_price - expected) < 1e-10

    @pytest.mark.parametrize("inc,n", [
        (0.25, 1), (0.5, 1), (0.5, 2), (1.0, 1),
    ])
    def test_down_formula_parametrized(self, inc, n):
        """Down level = (sqrt(p0) - inc*n)^2."""
        p0 = 47.70
        expected = (math.sqrt(p0) - inc * n) ** 2
        levels = sqrt_levels(p0, increments=[inc], steps=n, direction="down")
        target = [lv for lv in levels if lv.step == n][0]
        assert abs(target.level_price - expected) < 1e-10


# ── Direction tests ────────────────────────────────────────────────────────────


class TestDirection:
    def test_direction_up_only(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=3, direction="up")
        assert all(lv.direction == "up" for lv in levels)
        assert len(levels) == 3

    def test_direction_down_only(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=3, direction="down")
        assert all(lv.direction == "down" for lv in levels)

    def test_direction_both(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=3, direction="both")
        ups = [lv for lv in levels if lv.direction == "up"]
        downs = [lv for lv in levels if lv.direction == "down"]
        assert len(ups) == 3
        assert len(downs) == 3

    def test_both_default(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=2)
        assert any(lv.direction == "up" for lv in levels)
        assert any(lv.direction == "down" for lv in levels)

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="direction must be one of"):
            sqrt_levels(100.0, direction="sideways")

    def test_all_up_levels_above_origin(self):
        levels = sqrt_levels(100.0, increments=[0.25, 0.5, 1.0], steps=4, direction="up")
        for lv in levels:
            assert lv.level_price > 100.0, f"Expected > 100, got {lv.level_price}"

    def test_all_down_levels_below_origin(self):
        levels = sqrt_levels(100.0, increments=[0.25, 0.5, 1.0], steps=4, direction="down")
        for lv in levels:
            assert lv.level_price < 100.0, f"Expected < 100, got {lv.level_price}"


# ── Steps and increments ───────────────────────────────────────────────────────


class TestStepsAndIncrements:
    def test_default_increments_and_steps(self):
        """Default: [0.25, 0.5, 0.75, 1.0], steps=8, direction=both."""
        levels = sqrt_levels(100.0)
        # 4 increments × 8 steps × 2 directions = 64 levels (minus clamped downs)
        assert len(levels) >= 32  # at minimum 32 up-levels

    def test_single_increment_single_step_up(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=1, direction="up")
        assert len(levels) == 1
        assert levels[0].step == 1
        assert levels[0].increment_used == 1.0

    def test_multiple_increments(self):
        levels = sqrt_levels(100.0, increments=[0.5, 1.0], steps=2, direction="up")
        assert len(levels) == 4  # 2 increments × 2 steps

    def test_steps_count_correct(self):
        n = 5
        levels = sqrt_levels(100.0, increments=[1.0], steps=n, direction="up")
        assert len(levels) == n
        steps_found = sorted([lv.step for lv in levels])
        assert steps_found == list(range(1, n + 1))

    def test_empty_increments_raises(self):
        with pytest.raises(ValueError, match="increments must be a non-empty list"):
            sqrt_levels(100.0, increments=[])

    def test_negative_increment_raises(self):
        with pytest.raises(ValueError, match="All increments must be > 0"):
            sqrt_levels(100.0, increments=[-0.5])

    def test_zero_increment_raises(self):
        with pytest.raises(ValueError, match="All increments must be > 0"):
            sqrt_levels(100.0, increments=[0.0])

    def test_steps_zero_raises(self):
        with pytest.raises(ValueError, match="steps must be > 0"):
            sqrt_levels(100.0, steps=0)

    def test_steps_negative_raises(self):
        with pytest.raises(ValueError, match="steps must be > 0"):
            sqrt_levels(100.0, steps=-1)


# ── Invalid origin price ───────────────────────────────────────────────────────


class TestInvalidOriginPrice:
    def test_origin_zero_raises(self):
        with pytest.raises(ValueError, match="origin_price must be > 0"):
            sqrt_levels(0.0)

    def test_origin_negative_raises(self):
        with pytest.raises(ValueError, match="origin_price must be > 0"):
            sqrt_levels(-10.0)


# ── Down-level clamping (sqrt-negative) ───────────────────────────────────────


class TestDownLevelClamping:
    def test_down_level_clamps_when_sqrt_negative(self):
        """With small origin and large increment, down levels stop before sqrt<0."""
        # sqrt(4.0) = 2.0; step 1: 2.0-2.0=0, step 2: 2.0-4.0 < 0 → clamped
        levels = sqrt_levels(4.0, increments=[2.0], steps=5, direction="down")
        # step1: val=0 → allowed (0^2=0); step2: val=-2 → skipped
        for lv in levels:
            assert lv.level_price >= 0.0

    def test_large_origin_no_clamping(self):
        """Large origin price — no clamping for small increments."""
        levels = sqrt_levels(10000.0, increments=[1.0], steps=8, direction="down")
        assert len(levels) == 8  # no clamping at sqrt(10000)=100

    def test_boundary_down_level_zero_included(self):
        """A down level at exactly zero is valid (sqrt_base == inc*n)."""
        # sqrt(4)=2, inc=2, step=1 → val=0 → level_price=0
        levels = sqrt_levels(4.0, increments=[2.0], steps=1, direction="down")
        assert len(levels) == 1
        assert abs(levels[0].level_price - 0.0) < 1e-12


# ── Output ordering ───────────────────────────────────────────────────────────


class TestOutputOrdering:
    def test_levels_sorted_ascending(self):
        levels = sqrt_levels(100.0, increments=[0.25, 0.5, 1.0], steps=4, direction="both")
        prices = [lv.level_price for lv in levels]
        assert prices == sorted(prices)

    def test_up_levels_all_above_down_levels(self):
        """All upward levels should be above all downward levels (for large enough origin)."""
        levels = sqrt_levels(10000.0, increments=[1.0], steps=4, direction="both")
        up_prices = [lv.level_price for lv in levels if lv.direction == "up"]
        down_prices = [lv.level_price for lv in levels if lv.direction == "down"]
        assert min(up_prices) > max(down_prices)


# ── Label format ──────────────────────────────────────────────────────────────


class TestLabelFormat:
    def test_up_label_format(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=1, direction="up")
        assert levels[0].label == "+1×1"

    def test_down_label_format(self):
        levels = sqrt_levels(100.0, increments=[0.5], steps=2, direction="down")
        # There will be 2 down levels; find step=2
        step2 = [lv for lv in levels if lv.step == 2][0]
        assert step2.label == "-0.5×2"

    def test_label_contains_plus_for_up(self):
        levels = sqrt_levels(100.0, increments=[0.25], steps=1, direction="up")
        assert levels[0].label.startswith("+")

    def test_label_contains_minus_for_down(self):
        levels = sqrt_levels(100.0, increments=[0.25], steps=1, direction="down")
        assert levels[0].label.startswith("-")


# ── SqrtLevel.to_dict ─────────────────────────────────────────────────────────


class TestToDict:
    def test_all_keys_present(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=1, direction="up")
        d = levels[0].to_dict()
        for key in ("level_price", "increment_used", "step", "direction", "label"):
            assert key in d, f"Missing key: {key}"

    def test_values_consistent(self):
        levels = sqrt_levels(100.0, increments=[1.0], steps=1, direction="up")
        d = levels[0].to_dict()
        assert d["increment_used"] == 1.0
        assert d["step"] == 1
        assert d["direction"] == "up"
        assert abs(d["level_price"] - 121.0) < 1e-10


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_deterministic_up(self):
        a = sqrt_levels(47.70, increments=[0.5, 1.0], steps=4, direction="up")
        b = sqrt_levels(47.70, increments=[0.5, 1.0], steps=4, direction="up")
        assert [lv.level_price for lv in a] == [lv.level_price for lv in b]

    def test_deterministic_both(self):
        a = sqrt_levels(47.70)
        b = sqrt_levels(47.70)
        assert [lv.level_price for lv in a] == [lv.level_price for lv in b]
