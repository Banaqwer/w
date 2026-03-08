"""
tests/test_generator_sqrt_levels.py

Tests for signals/generators_sqrt_levels.py.

Coverage
--------
- projections_from_sqrt_levels:
  - basic conversion: up level → resistance, down level → support
  - origin_price fallback for direction detection
  - step-based score decay
  - price band computed correctly
  - negative band_pct raises ValueError
  - time_band is (None, None)
  - projected_time is None
  - module_name correct
  - source_id propagated
  - non-positive level_price skipped
  - empty input returns empty list
  - determinism
  - metadata contains step, label, increment_used
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from signals.generators_sqrt_levels import (
    _DEFAULT_BAND_PCT,
    _STEP_DECAY,
    projections_from_sqrt_levels,
)


def _make_level(
    level_price: float = 50000.0,
    direction: str = "up",
    step: int = 1,
    label: str = "+1.0×1",
    increment_used: float = 1.0,
) -> Dict[str, Any]:
    return {
        "level_price": level_price,
        "direction": direction,
        "step": step,
        "label": label,
        "increment_used": increment_used,
    }


# ── Direction hints ───────────────────────────────────────────────────────────


class TestDirectionHint:
    def test_up_level_is_resistance(self):
        lvl = _make_level(direction="up")
        projs = projections_from_sqrt_levels([lvl])
        assert projs[0].direction_hint == "resistance"

    def test_down_level_is_support(self):
        lvl = _make_level(direction="down")
        projs = projections_from_sqrt_levels([lvl])
        assert projs[0].direction_hint == "support"

    def test_missing_direction_uses_origin_price_above(self):
        lvl = _make_level(level_price=55000.0, direction="")
        projs = projections_from_sqrt_levels([lvl], origin_price=50000.0)
        assert projs[0].direction_hint == "resistance"

    def test_missing_direction_uses_origin_price_below(self):
        lvl = _make_level(level_price=45000.0, direction="")
        projs = projections_from_sqrt_levels([lvl], origin_price=50000.0)
        assert projs[0].direction_hint == "support"

    def test_no_direction_no_origin_is_ambiguous(self):
        lvl = _make_level(direction="")
        projs = projections_from_sqrt_levels([lvl])
        assert projs[0].direction_hint == "ambiguous"


# ── Score decay ───────────────────────────────────────────────────────────────


class TestScoreDecay:
    def test_step1_score(self):
        lvl = _make_level(step=1)
        projs = projections_from_sqrt_levels([lvl])
        expected = 1.0 / (1.0 + 1 * _STEP_DECAY)
        assert projs[0].raw_score == pytest.approx(expected)

    def test_step8_score_lower_than_step1(self):
        lvl1 = _make_level(step=1)
        lvl8 = _make_level(step=8, label="+1.0×8")
        p1 = projections_from_sqrt_levels([lvl1])[0]
        p8 = projections_from_sqrt_levels([lvl8])[0]
        assert p8.raw_score < p1.raw_score

    def test_score_in_range(self):
        for step in range(1, 10):
            lvl = _make_level(step=step)
            projs = projections_from_sqrt_levels([lvl])
            assert 0.0 <= projs[0].raw_score <= 1.0


# ── Price band ────────────────────────────────────────────────────────────────


class TestPriceBand:
    def test_default_band_pct(self):
        price = 50000.0
        lvl = _make_level(level_price=price)
        projs = projections_from_sqrt_levels([lvl])
        lo, hi = projs[0].price_band
        assert lo == pytest.approx(price * (1 - _DEFAULT_BAND_PCT))
        assert hi == pytest.approx(price * (1 + _DEFAULT_BAND_PCT))

    def test_custom_band_pct(self):
        price = 50000.0
        lvl = _make_level(level_price=price)
        projs = projections_from_sqrt_levels([lvl], band_pct=0.02)
        lo, hi = projs[0].price_band
        assert lo == pytest.approx(price * 0.98)
        assert hi == pytest.approx(price * 1.02)

    def test_negative_band_pct_raises(self):
        with pytest.raises(ValueError, match="band_pct"):
            projections_from_sqrt_levels([], band_pct=-0.01)


# ── Other fields ──────────────────────────────────────────────────────────────


class TestOtherFields:
    def test_projected_time_is_none(self):
        projs = projections_from_sqrt_levels([_make_level()])
        assert projs[0].projected_time is None

    def test_time_band_is_none_none(self):
        projs = projections_from_sqrt_levels([_make_level()])
        assert projs[0].time_band == (None, None)

    def test_module_name(self):
        projs = projections_from_sqrt_levels([_make_level()])
        assert projs[0].module_name == "sqrt_levels"

    def test_source_id_propagated(self):
        projs = projections_from_sqrt_levels([_make_level()], source_id="my_origin_42")
        assert projs[0].source_id == "my_origin_42"

    def test_metadata_step(self):
        lvl = _make_level(step=3)
        projs = projections_from_sqrt_levels([lvl])
        assert projs[0].metadata["step"] == 3

    def test_metadata_label(self):
        lvl = _make_level(label="+0.5×2")
        projs = projections_from_sqrt_levels([lvl])
        assert projs[0].metadata["label"] == "+0.5×2"

    def test_metadata_increment_used(self):
        lvl = _make_level(increment_used=0.75)
        projs = projections_from_sqrt_levels([lvl])
        assert projs[0].metadata["increment_used"] == pytest.approx(0.75)

    def test_metadata_origin_price_stored(self):
        lvl = _make_level()
        projs = projections_from_sqrt_levels([lvl], origin_price=48000.0)
        assert projs[0].metadata["origin_price"] == 48000.0


# ── Skipping / edge cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_input(self):
        assert projections_from_sqrt_levels([]) == []

    def test_nonpositive_level_price_skipped(self):
        lvl = _make_level(level_price=0.0)
        projs = projections_from_sqrt_levels([lvl])
        assert projs == []

    def test_negative_level_price_skipped(self):
        lvl = _make_level(level_price=-100.0)
        projs = projections_from_sqrt_levels([lvl])
        assert projs == []

    def test_mixed_valid_invalid(self):
        lvl_valid = _make_level(level_price=50000.0)
        lvl_invalid = _make_level(level_price=0.0)
        projs = projections_from_sqrt_levels([lvl_valid, lvl_invalid])
        assert len(projs) == 1


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_ids(self):
        levels = [_make_level(level_price=50000.0 + i * 1000, step=i + 1) for i in range(5)]
        ids_1 = [p.projection_id for p in projections_from_sqrt_levels(levels)]
        ids_2 = [p.projection_id for p in projections_from_sqrt_levels(levels)]
        assert ids_1 == ids_2
