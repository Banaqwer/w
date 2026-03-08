"""
tests/test_generator_angle_families.py

Tests for signals/generators_angle_families.py.

Coverage
--------
- projections_from_angle_families:
  - basic conversion: produces projections for bucketed impulses
  - impulses without angle_family are skipped
  - non-positive extreme_price skipped
  - direction_hint: above extreme → resistance, below → support
  - price band computed correctly at default band_pct
  - custom band_pct applied
  - negative band_pct raises ValueError
  - non-positive horizon raises ValueError
  - time_band is (None, None)
  - projected_time is None
  - module_name correct
  - source_id propagated
  - raw_score includes angle-match decay
  - empty input returns empty list
  - determinism
  - metadata contains angle_family, horizon_bars, extreme_price
  - multiple horizons produce multiple projections
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from signals.generators_angle_families import (
    _DEFAULT_BAND_PCT,
    _QUALITY_DECAY_PER_DEG,
    projections_from_angle_families,
)


def _make_scale_basis(ppb: float = 100.0) -> Dict[str, Any]:
    """Return a minimal scale_basis dict."""
    return {"price_per_bar": ppb}


def _make_impulse_angle(
    impulse_id: str = "imp_0",
    extreme_price: float = 50000.0,
    delta_p: float = 10000.0,
    quality_score: float = 0.8,
    angle_family: str = "1x1",
    angle_family_delta_deg: float = 1.0,
    angle_family_deg: float = 45.0,
    angle_deg: float = 44.0,
    angle_normalized: float = 44.0,
    delta_t: int = 100,
    origin_price: float = 40000.0,
) -> Dict[str, Any]:
    """Return a plain-dict impulse angle record (as from compute_impulse_angles)."""
    return {
        "impulse_id": impulse_id,
        "extreme_price": extreme_price,
        "delta_p": delta_p,
        "quality_score": quality_score,
        "angle_family": angle_family,
        "angle_family_delta_deg": angle_family_delta_deg,
        "angle_family_deg": angle_family_deg,
        "angle_deg": angle_deg,
        "angle_normalized": angle_normalized,
        "delta_t": delta_t,
        "origin_price": origin_price,
    }


# ── Basic conversion ──────────────────────────────────────────────────────────


class TestBasicConversion:
    def test_produces_projections_for_bucketed_impulse(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        assert len(projs) > 0

    def test_unbucketed_impulse_skipped(self):
        imp = _make_impulse_angle(angle_family=None)
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        assert projs == []

    def test_nonpositive_extreme_price_skipped(self):
        imp = _make_impulse_angle(extreme_price=0.0)
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        assert projs == []

    def test_negative_extreme_price_skipped(self):
        imp = _make_impulse_angle(extreme_price=-100.0)
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        assert projs == []

    def test_empty_input(self):
        sb = _make_scale_basis()
        assert projections_from_angle_families([], sb) == []


# ── Direction hints ───────────────────────────────────────────────────────────


class TestDirectionHint:
    def test_above_extreme_is_resistance(self):
        imp = _make_impulse_angle(extreme_price=50000.0, delta_p=10000.0)
        sb = _make_scale_basis(ppb=100.0)
        projs = projections_from_angle_families([imp], sb)
        resistance_projs = [p for p in projs if p.direction_hint == "resistance"]
        assert len(resistance_projs) > 0
        for p in resistance_projs:
            assert p.projected_price > 50000.0

    def test_below_extreme_is_support(self):
        imp = _make_impulse_angle(extreme_price=50000.0, delta_p=10000.0)
        sb = _make_scale_basis(ppb=100.0)
        projs = projections_from_angle_families([imp], sb)
        support_projs = [p for p in projs if p.direction_hint == "support"]
        assert len(support_projs) > 0
        for p in support_projs:
            assert p.projected_price < 50000.0

    def test_downward_impulse_produces_projections(self):
        imp = _make_impulse_angle(
            extreme_price=30000.0, delta_p=-20000.0,
            origin_price=50000.0,
        )
        sb = _make_scale_basis(ppb=100.0)
        projs = projections_from_angle_families([imp], sb)
        assert len(projs) > 0


# ── Price band ────────────────────────────────────────────────────────────────


class TestPriceBand:
    def test_default_band_pct(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            lo, hi = p.price_band
            assert lo == pytest.approx(p.projected_price * (1 - _DEFAULT_BAND_PCT))
            assert hi == pytest.approx(p.projected_price * (1 + _DEFAULT_BAND_PCT))

    def test_custom_band_pct(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb, band_pct=0.05)
        for p in projs:
            lo, hi = p.price_band
            assert lo == pytest.approx(p.projected_price * 0.95)
            assert hi == pytest.approx(p.projected_price * 1.05)

    def test_negative_band_pct_raises(self):
        sb = _make_scale_basis()
        with pytest.raises(ValueError, match="band_pct"):
            projections_from_angle_families([], sb, band_pct=-0.01)


# ── Horizons ──────────────────────────────────────────────────────────────────


class TestHorizons:
    def test_nonpositive_horizon_raises(self):
        sb = _make_scale_basis()
        with pytest.raises(ValueError, match="horizon"):
            projections_from_angle_families([], sb, horizons=[0])

    def test_negative_horizon_raises(self):
        sb = _make_scale_basis()
        with pytest.raises(ValueError, match="horizon"):
            projections_from_angle_families([], sb, horizons=[-10])

    def test_multiple_horizons_produce_more_projections(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs_1 = projections_from_angle_families([imp], sb, horizons=[90])
        projs_2 = projections_from_angle_families([imp], sb, horizons=[90, 180])
        # Two horizons produce at least as many projections as one (some may
        # be filtered at longer horizons due to negative target prices)
        assert len(projs_2) > len(projs_1)


# ── Other fields ──────────────────────────────────────────────────────────────


class TestOtherFields:
    def test_projected_time_is_none(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.projected_time is None

    def test_time_band_is_none_none(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.time_band == (None, None)

    def test_module_name(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.module_name == "angle_families"

    def test_source_id_propagated(self):
        imp = _make_impulse_angle(impulse_id="my_imp_42")
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.source_id == "my_imp_42"


# ── Scoring ───────────────────────────────────────────────────────────────────


class TestScoring:
    def test_raw_score_within_bounds(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert 0.0 <= p.raw_score <= 1.0

    def test_perfect_match_higher_score(self):
        imp_tight = _make_impulse_angle(angle_family_delta_deg=0.0, quality_score=0.8)
        imp_loose = _make_impulse_angle(
            angle_family_delta_deg=4.0, quality_score=0.8, impulse_id="imp_loose"
        )
        sb = _make_scale_basis()
        projs_tight = projections_from_angle_families([imp_tight], sb)
        projs_loose = projections_from_angle_families([imp_loose], sb)
        assert projs_tight[0].raw_score >= projs_loose[0].raw_score

    def test_score_minimum_floor(self):
        imp = _make_impulse_angle(angle_family_delta_deg=50.0, quality_score=0.1)
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.raw_score >= 0.1


# ── Metadata ─────────────────────────────────────────────────────────────────


class TestMetadata:
    def test_metadata_has_angle_family(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert "angle_family" in p.metadata

    def test_metadata_has_horizon_bars(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.metadata["horizon_bars"] == 90

    def test_metadata_has_extreme_price(self):
        imp = _make_impulse_angle(extreme_price=55000.0)
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.metadata["extreme_price"] == 55000.0

    def test_metadata_has_impulse_direction(self):
        imp = _make_impulse_angle(delta_p=5000.0)
        sb = _make_scale_basis()
        projs = projections_from_angle_families([imp], sb)
        for p in projs:
            assert p.metadata["impulse_direction"] in ("up", "down")


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_ids(self):
        imps = [
            _make_impulse_angle(impulse_id=f"imp_{i}", extreme_price=50000.0 + i * 1000)
            for i in range(3)
        ]
        sb = _make_scale_basis()
        ids_1 = [p.projection_id for p in projections_from_angle_families(imps, sb)]
        ids_2 = [p.projection_id for p in projections_from_angle_families(imps, sb)]
        assert ids_1 == ids_2

    def test_same_input_same_count(self):
        imp = _make_impulse_angle()
        sb = _make_scale_basis()
        n1 = len(projections_from_angle_families([imp], sb))
        n2 = len(projections_from_angle_families([imp], sb))
        assert n1 == n2
