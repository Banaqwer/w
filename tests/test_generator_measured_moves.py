"""
tests/test_generator_measured_moves.py

Tests for signals/generators_measured_moves.py.

Coverage
--------
- projections_from_measured_moves:
  - basic conversion: extension upward impulse → resistance
  - basic conversion: extension downward impulse → support
  - retracement upward impulse → support
  - retracement downward impulse → resistance
  - non-positive target_price skipped
  - price band computed correctly at default band_pct
  - custom band_pct applied
  - negative band_pct raises ValueError
  - time_band is (None, None)
  - projected_time is None
  - raw_score clamped to [0, 1]
  - determinism
  - metadata propagated (ratio, mode, notes)
  - empty input returns empty list
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import pytest

from signals.generators_measured_moves import (
    _DEFAULT_BAND_PCT,
    projections_from_measured_moves,
)

_T0 = pd.Timestamp("2020-01-01", tz="UTC")
_T1 = pd.Timestamp("2020-06-01", tz="UTC")


def _make_target(
    impulse_id: str = "imp_0",
    target_price: float = 60000.0,
    direction: str = "extension",
    origin_price: float = 30000.0,
    extreme_price: float = 60000.0,
    quality_score: float = 0.7,
    ratio: float = 1.0,
    mode: str = "raw",
    notes: str = "",
) -> Dict[str, Any]:
    """Return a plain-dict MeasuredMoveTarget."""
    return {
        "impulse_id": impulse_id,
        "target_price": target_price,
        "direction": direction,
        "origin_price": origin_price,
        "extreme_price": extreme_price,
        "quality_score": quality_score,
        "ratio": ratio,
        "mode": mode,
        "notes": notes,
    }


# ── Basic conversions ─────────────────────────────────────────────────────────


class TestDirectionHint:
    def test_extension_up_impulse_is_resistance(self):
        t = _make_target(direction="extension", origin_price=30000.0, extreme_price=60000.0)
        projs = projections_from_measured_moves([t])
        assert projs[0].direction_hint == "resistance"

    def test_extension_down_impulse_is_support(self):
        t = _make_target(direction="extension", origin_price=60000.0, extreme_price=30000.0,
                         target_price=10000.0)
        projs = projections_from_measured_moves([t])
        assert projs[0].direction_hint == "support"

    def test_retracement_up_impulse_is_support(self):
        t = _make_target(direction="retracement", origin_price=30000.0, extreme_price=60000.0,
                         target_price=45000.0)
        projs = projections_from_measured_moves([t])
        assert projs[0].direction_hint == "support"

    def test_retracement_down_impulse_is_resistance(self):
        t = _make_target(direction="retracement", origin_price=60000.0, extreme_price=30000.0,
                         target_price=45000.0)
        projs = projections_from_measured_moves([t])
        assert projs[0].direction_hint == "resistance"

    def test_unknown_direction_is_ambiguous(self):
        t = _make_target(direction="extension", origin_price=50000.0, extreme_price=50000.0)
        projs = projections_from_measured_moves([t])
        assert projs[0].direction_hint == "ambiguous"


# ── Price band ────────────────────────────────────────────────────────────────


class TestPriceBand:
    def test_default_band_pct(self):
        price = 50000.0
        t = _make_target(target_price=price)
        projs = projections_from_measured_moves([t])
        lo, hi = projs[0].price_band
        assert lo == pytest.approx(price * (1 - _DEFAULT_BAND_PCT))
        assert hi == pytest.approx(price * (1 + _DEFAULT_BAND_PCT))

    def test_custom_band_pct(self):
        price = 50000.0
        t = _make_target(target_price=price)
        projs = projections_from_measured_moves([t], band_pct=0.05)
        lo, hi = projs[0].price_band
        assert lo == pytest.approx(price * 0.95)
        assert hi == pytest.approx(price * 1.05)

    def test_negative_band_pct_raises(self):
        with pytest.raises(ValueError, match="band_pct"):
            projections_from_measured_moves([], band_pct=-0.01)


# ── Other fields ──────────────────────────────────────────────────────────────


class TestOtherFields:
    def test_projected_time_is_none(self):
        t = _make_target()
        projs = projections_from_measured_moves([t])
        assert projs[0].projected_time is None

    def test_time_band_is_none_none(self):
        t = _make_target()
        projs = projections_from_measured_moves([t])
        assert projs[0].time_band == (None, None)

    def test_module_name(self):
        t = _make_target()
        projs = projections_from_measured_moves([t])
        assert projs[0].module_name == "measured_moves"

    def test_source_id_propagated(self):
        t = _make_target(impulse_id="test_imp_42")
        projs = projections_from_measured_moves([t])
        assert projs[0].source_id == "test_imp_42"

    def test_raw_score_clamped(self):
        t = _make_target(quality_score=1.5)
        projs = projections_from_measured_moves([t])
        assert projs[0].raw_score == 1.0

    def test_metadata_has_ratio(self):
        t = _make_target(ratio=0.5)
        projs = projections_from_measured_moves([t])
        assert projs[0].metadata["ratio"] == 0.5

    def test_metadata_has_mode(self):
        t = _make_target(mode="log")
        projs = projections_from_measured_moves([t])
        assert projs[0].metadata["mode"] == "log"


# ── Skipping / edge cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_input(self):
        assert projections_from_measured_moves([]) == []

    def test_nonpositive_target_price_skipped(self):
        t1 = _make_target(target_price=0.0)
        t2 = _make_target(target_price=-100.0, impulse_id="neg")
        projs = projections_from_measured_moves([t1, t2])
        assert projs == []

    def test_mixed_valid_invalid(self):
        t_valid = _make_target(target_price=50000.0, impulse_id="valid")
        t_invalid = _make_target(target_price=-1.0, impulse_id="invalid")
        projs = projections_from_measured_moves([t_valid, t_invalid])
        assert len(projs) == 1
        assert projs[0].source_id == "valid"


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_ids(self):
        targets = [
            _make_target(impulse_id=f"imp_{i}", target_price=50000.0 + i * 100)
            for i in range(5)
        ]
        ids_1 = [p.projection_id for p in projections_from_measured_moves(targets)]
        ids_2 = [p.projection_id for p in projections_from_measured_moves(targets)]
        assert ids_1 == ids_2
