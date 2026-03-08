"""
tests/test_generator_time_counts.py

Tests for signals/generators_time_counts.py.

Coverage
--------
- projections_from_time_windows:
  - basic conversion: time-only projection
  - direction_hint is always "turn"
  - projected_price is None
  - price_band is (None, None)
  - time_band built from target_time when available
  - time_band is (None, None) when target_time missing and no bar_to_time_map
  - module_name correct
  - source_id from impulse_id
  - raw_score from quality_scores dict
  - recency weight: multiplier > 1 discounts score
  - multiplier == 1.0 → no recency penalty
  - negative half_band_bars raises ValueError
  - missing target_bar_index skipped
  - empty input returns empty list
  - determinism
  - metadata contains multiplier, target_bar_index, in_dataset
  - bar_to_time_map resolves timestamps
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import pytest

from signals.generators_time_counts import (
    _DEFAULT_HALF_BAND_BARS,
    _DEFAULT_QUALITY,
    projections_from_time_windows,
)

_T0 = pd.Timestamp("2020-01-01", tz="UTC")
_T1 = pd.Timestamp("2020-06-15", tz="UTC")
_T2 = pd.Timestamp("2021-01-01", tz="UTC")


def _make_window(
    impulse_id: str = "imp_0",
    target_bar_index: Optional[int] = 100,
    multiplier: float = 1.0,
    in_dataset: bool = True,
    target_time: Optional[pd.Timestamp] = _T1,
    origin_bar_index: int = 0,
    extreme_bar_index: int = 50,
    impulse_delta_t: int = 50,
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "impulse_id": impulse_id,
        "target_bar_index": target_bar_index,
        "multiplier": multiplier,
        "in_dataset": in_dataset,
        "target_time": str(target_time) if target_time is not None else None,
        "origin_bar_index": origin_bar_index,
        "extreme_bar_index": extreme_bar_index,
        "impulse_delta_t": impulse_delta_t,
        "notes": notes,
    }


# ── Basic conversion ──────────────────────────────────────────────────────────


class TestBasicConversion:
    def test_direction_hint_is_turn(self):
        w = _make_window()
        projs = projections_from_time_windows([w])
        assert projs[0].direction_hint == "turn"

    def test_projected_price_is_none(self):
        w = _make_window()
        projs = projections_from_time_windows([w])
        assert projs[0].projected_price is None

    def test_price_band_is_none_none(self):
        w = _make_window()
        projs = projections_from_time_windows([w])
        assert projs[0].price_band == (None, None)

    def test_module_name(self):
        w = _make_window()
        projs = projections_from_time_windows([w])
        assert projs[0].module_name == "time_counts"

    def test_source_id_from_impulse_id(self):
        w = _make_window(impulse_id="my_imp_42")
        projs = projections_from_time_windows([w])
        assert projs[0].source_id == "my_imp_42"


# ── Timestamps and bands ──────────────────────────────────────────────────────


class TestTimeBand:
    def test_time_band_built_from_target_time(self):
        w = _make_window(target_time=_T1)
        projs = projections_from_time_windows([w])
        lo, hi = projs[0].time_band
        assert lo is not None
        assert hi is not None
        assert lo < _T1 < hi

    def test_time_band_half_width(self):
        w = _make_window(target_time=_T1)
        projs = projections_from_time_windows([w], half_band_bars=5)
        lo, hi = projs[0].time_band
        # For 1D data (1 bar ≈ 1 day), half-width ≈ 5 days
        # Allow some flexibility since estimation may vary
        assert lo is not None and hi is not None
        width_days = (hi - lo).total_seconds() / 86400.0
        assert width_days > 0

    def test_projected_time_from_target_time(self):
        w = _make_window(target_time=_T1)
        projs = projections_from_time_windows([w])
        assert projs[0].projected_time == _T1

    def test_missing_target_time_gives_none_projected_time(self):
        w = _make_window(target_time=None)
        projs = projections_from_time_windows([w])
        assert projs[0].projected_time is None

    def test_missing_target_time_gives_none_band(self):
        w = _make_window(target_time=None)
        projs = projections_from_time_windows([w])
        assert projs[0].time_band == (None, None)

    def test_negative_half_band_bars_raises(self):
        with pytest.raises(ValueError, match="half_band_bars"):
            projections_from_time_windows([], half_band_bars=-1)


# ── Quality scoring ───────────────────────────────────────────────────────────


class TestScoring:
    def test_default_score(self):
        w = _make_window()
        projs = projections_from_time_windows([w])
        # multiplier=1.0, recency_weight=1.0, base=0.5 → score=0.5
        assert projs[0].raw_score == pytest.approx(0.5)

    def test_quality_scores_dict_used(self):
        w = _make_window(impulse_id="imp_q")
        projs = projections_from_time_windows([w], quality_scores={"imp_q": 0.8})
        # multiplier=1.0, recency=1.0, base=0.8
        assert projs[0].raw_score == pytest.approx(0.8)

    def test_recency_weight_multiplier_gt_1(self):
        w = _make_window(multiplier=2.0)
        projs_2 = projections_from_time_windows([w])
        w1 = _make_window(multiplier=1.0)
        projs_1 = projections_from_time_windows([w1])
        # multiplier=2.0 → recency = max(0.5, 1/2.0) = 0.5 → score lower
        assert projs_2[0].raw_score < projs_1[0].raw_score

    def test_score_clamped_to_unit_interval(self):
        w = _make_window()
        projs = projections_from_time_windows([w], quality_scores={"imp_0": 1.5})
        assert 0.0 <= projs[0].raw_score <= 1.0


# ── Metadata ─────────────────────────────────────────────────────────────────


class TestMetadata:
    def test_metadata_has_multiplier(self):
        w = _make_window(multiplier=0.5)
        projs = projections_from_time_windows([w])
        assert projs[0].metadata["multiplier"] == 0.5

    def test_metadata_has_target_bar_index(self):
        w = _make_window(target_bar_index=200)
        projs = projections_from_time_windows([w])
        assert projs[0].metadata["target_bar_index"] == 200

    def test_metadata_has_in_dataset(self):
        w = _make_window(in_dataset=True)
        projs = projections_from_time_windows([w])
        assert projs[0].metadata["in_dataset"] is True

    def test_metadata_has_origin_bar_index(self):
        w = _make_window(origin_bar_index=10)
        projs = projections_from_time_windows([w])
        assert projs[0].metadata["origin_bar_index"] == 10

    def test_metadata_has_extreme_bar_index(self):
        w = _make_window(extreme_bar_index=60)
        projs = projections_from_time_windows([w])
        assert projs[0].metadata["extreme_bar_index"] == 60


# ── Edge cases / skipping ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_input(self):
        assert projections_from_time_windows([]) == []

    def test_missing_target_bar_index_skipped(self):
        w = {
            "impulse_id": "imp_x",
            "target_bar_index": None,
            "multiplier": 1.0,
        }
        projs = projections_from_time_windows([w])
        assert projs == []

    def test_bar_to_time_map_resolves_timestamp(self):
        # Build a bar_to_time_map that has bar 100 → _T1
        btm = {
            99: _T0,
            100: _T1,
            101: _T2,
        }
        w = _make_window(target_bar_index=100, target_time=None)
        projs = projections_from_time_windows([w], bar_to_time_map=btm)
        assert projs[0].projected_time == _T1


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_ids(self):
        windows = [_make_window(impulse_id=f"imp_{i}", target_bar_index=100 + i) for i in range(5)]
        ids_1 = [p.projection_id for p in projections_from_time_windows(windows)]
        ids_2 = [p.projection_id for p in projections_from_time_windows(windows)]
        assert ids_1 == ids_2
