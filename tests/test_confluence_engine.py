"""
tests/test_confluence_engine.py

Tests for signals/confluence.py.

Coverage
--------
- build_confluence_zones:
  - empty input returns empty list
  - single projection forms singleton zone
  - price overlap correctly merges two projections
  - non-overlapping projections form separate zones
  - time overlap correctly merges two time projections
  - price-only and time-only never merged (no shared dimension)
  - mixed projection bridges price+time projections
  - determinism: same input → same output
  - min_cluster_size filtering
  - module diversity reflected in score
  - score ordering: highest first
  - scoring formula: n_score * diversity_score * avg_raw
  - zone has correct type annotation in notes
  - price_window is intersection, not union
  - time_window is intersection
  - zone_id is deterministic
- _price_overlap / _time_overlap helpers (via public API)
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from signals.confluence import build_confluence_zones
from signals.projections import ConfluenceZone, Projection

_T0 = pd.Timestamp("2021-01-01", tz="UTC")
_T1 = pd.Timestamp("2021-06-01", tz="UTC")
_T2 = pd.Timestamp("2021-12-31", tz="UTC")
_T3 = pd.Timestamp("2022-06-01", tz="UTC")


def _price_proj(price: float, low: float, high: float, module: str = "measured_moves",
                source: str = "imp_1", score: float = 0.5,
                hint: str = "resistance") -> Projection:
    return Projection(
        module_name=module,
        source_id=source,
        projected_time=None,
        projected_price=price,
        time_band=(None, None),
        price_band=(low, high),
        direction_hint=hint,
        raw_score=score,
    )


def _time_proj(t_lo: pd.Timestamp, t_hi: pd.Timestamp,
               module: str = "time_counts", source: str = "imp_1",
               score: float = 0.5) -> Projection:
    return Projection(
        module_name=module,
        source_id=source,
        projected_time=t_lo + (t_hi - t_lo) / 2,
        projected_price=None,
        time_band=(t_lo, t_hi),
        price_band=(None, None),
        direction_hint="turn",
        raw_score=score,
    )


def _mixed_proj(price: float, p_lo: float, p_hi: float,
                t_lo: pd.Timestamp, t_hi: pd.Timestamp,
                module: str = "jttl", source: str = "jttl_0",
                score: float = 0.5) -> Projection:
    return Projection(
        module_name=module,
        source_id=source,
        projected_time=t_lo + (t_hi - t_lo) / 2,
        projected_price=price,
        time_band=(t_lo, t_hi),
        price_band=(p_lo, p_hi),
        direction_hint="resistance",
        raw_score=score,
    )


# ── Empty / single ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_input(self):
        assert build_confluence_zones([]) == []

    def test_single_projection_forms_singleton_zone(self):
        p = _price_proj(50000.0, 49500.0, 50500.0)
        zones = build_confluence_zones([p])
        assert len(zones) == 1
        assert p.projection_id in zones[0].contributing_projection_ids

    def test_min_cluster_size_filters_singletons(self):
        p = _price_proj(50000.0, 49500.0, 50500.0)
        zones = build_confluence_zones([p], min_cluster_size=2)
        assert zones == []


# ── Price overlap ─────────────────────────────────────────────────────────────


class TestPriceOverlap:
    def test_overlapping_price_bands_merged(self):
        p1 = _price_proj(50000.0, 49000.0, 51000.0)
        p2 = _price_proj(50500.0, 50000.0, 51500.0)  # overlaps p1
        zones = build_confluence_zones([p1, p2])
        assert len(zones) == 1
        assert len(zones[0].contributing_projection_ids) == 2

    def test_touching_price_bands_merged(self):
        p1 = _price_proj(50000.0, 49000.0, 50000.0)
        p2 = _price_proj(50500.0, 50000.0, 51500.0)  # touches exactly at 50000
        zones = build_confluence_zones([p1, p2])
        assert len(zones) == 1

    def test_non_overlapping_price_bands_separate(self):
        p1 = _price_proj(50000.0, 49000.0, 50000.0)
        p2 = _price_proj(55000.0, 54500.0, 55500.0)
        zones = build_confluence_zones([p1, p2])
        assert len(zones) == 2

    def test_price_window_is_intersection(self):
        # p1 band: 48000..52000, p2 band: 50000..54000 → intersection: 50000..52000
        p1 = _price_proj(50000.0, 48000.0, 52000.0)
        p2 = _price_proj(52000.0, 50000.0, 54000.0)
        zones = build_confluence_zones([p1, p2])
        assert len(zones) == 1
        pw = zones[0].price_window
        assert pw is not None
        lo, hi = pw
        assert lo == pytest.approx(50000.0)
        assert hi == pytest.approx(52000.0)


# ── Time overlap ──────────────────────────────────────────────────────────────


class TestTimeOverlap:
    def test_overlapping_time_bands_merged(self):
        p1 = _time_proj(_T0, _T1)
        p2 = _time_proj(_T1 - pd.Timedelta(days=10), _T2)  # overlaps
        zones = build_confluence_zones([p1, p2])
        assert len(zones) == 1

    def test_non_overlapping_time_bands_separate(self):
        p1 = _time_proj(_T0, _T1)
        p2 = _time_proj(_T2, _T3)  # no overlap
        zones = build_confluence_zones([p1, p2])
        assert len(zones) == 2

    def test_time_window_is_intersection(self):
        # band1: T0..T2, band2: T1..T3 → intersection: T1..T2
        p1 = _time_proj(_T0, _T2)
        p2 = _time_proj(_T1, _T3)
        zones = build_confluence_zones([p1, p2])
        assert len(zones) == 1
        tw = zones[0].time_window
        assert tw is not None
        assert tw[0] == _T1
        assert tw[1] == _T2


# ── Price-only vs time-only: no cross-merge ───────────────────────────────────


class TestNoCrossMerge:
    def test_price_only_and_time_only_not_merged(self):
        pp = _price_proj(50000.0, 49000.0, 51000.0)
        tp = _time_proj(_T0, _T1)
        zones = build_confluence_zones([pp, tp])
        # They share no dimension → separate zones
        assert len(zones) == 2

    def test_mixed_bridges_price_and_time(self):
        pp = _price_proj(50000.0, 49000.0, 51000.0)
        tp = _time_proj(_T0, _T1)
        # Mixed projection overlaps both pp (price) and tp (time)
        mp = _mixed_proj(50000.0, 49500.0, 51500.0, _T0, _T1)
        zones = build_confluence_zones([pp, tp, mp])
        # mp bridges pp and tp → all three merge
        assert len(zones) == 1
        assert len(zones[0].contributing_projection_ids) == 3


# ── Scoring ───────────────────────────────────────────────────────────────────


class TestScoring:
    def test_single_projection_score(self):
        p = _price_proj(50000.0, 49500.0, 50500.0, score=0.8)
        zones = build_confluence_zones([p])
        z = zones[0]
        # n_score = 1/10 = 0.1, diversity = 1/5 = 0.2, avg_raw = 0.8
        expected = 0.1 * 0.2 * 0.8
        assert z.confluence_score == pytest.approx(expected, rel=1e-6)

    def test_higher_diversity_higher_score(self):
        # One zone with 2 projections from same module
        p1 = _price_proj(50000.0, 48000.0, 52000.0, module="measured_moves", score=0.5)
        p2 = _price_proj(50200.0, 49000.0, 51500.0, module="measured_moves", score=0.5)
        zones_same = build_confluence_zones([p1, p2])

        # Same overlap but different modules
        p3 = _price_proj(50000.0, 48000.0, 52000.0, module="measured_moves", score=0.5)
        p4 = _price_proj(50200.0, 49000.0, 51500.0, module="sqrt_levels", score=0.5)
        zones_diff = build_confluence_zones([p3, p4])

        assert zones_diff[0].confluence_score > zones_same[0].confluence_score

    def test_sorted_by_score_descending(self):
        # Create three separate zones with known scores by making them non-overlapping
        p1 = _price_proj(10000.0, 9000.0, 11000.0, score=0.9)
        p2 = _price_proj(20000.0, 19000.0, 21000.0, score=0.2)
        p3 = _price_proj(30000.0, 29000.0, 31000.0, score=0.5)
        zones = build_confluence_zones([p1, p2, p3])
        assert len(zones) == 3
        scores = [z.confluence_score for z in zones]
        assert scores == sorted(scores, reverse=True)


# ── Module counts ─────────────────────────────────────────────────────────────


class TestModuleCounts:
    def test_module_counts_correct(self):
        p1 = _price_proj(50000.0, 48000.0, 52000.0, module="measured_moves")
        p2 = _price_proj(50100.0, 49000.0, 52000.0, module="sqrt_levels")
        p3 = _price_proj(50200.0, 49500.0, 52000.0, module="measured_moves")
        zones = build_confluence_zones([p1, p2, p3])
        assert len(zones) == 1
        mc = zones[0].module_counts
        assert mc["measured_moves"] == 2
        assert mc["sqrt_levels"] == 1

    def test_time_only_zone_type_note(self):
        tp = _time_proj(_T0, _T1)
        zones = build_confluence_zones([tp])
        assert "time_only" in zones[0].notes

    def test_price_only_zone_type_note(self):
        pp = _price_proj(50000.0, 49000.0, 51000.0)
        zones = build_confluence_zones([pp])
        assert "price_only" in zones[0].notes


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_output(self):
        projs = [
            _price_proj(50000.0, 49000.0, 51000.0, source="a"),
            _price_proj(50200.0, 49800.0, 51200.0, source="b"),
            _time_proj(_T0, _T1, source="c"),
        ]
        zones1 = build_confluence_zones(projs)
        zones2 = build_confluence_zones(projs)
        assert [z.zone_id for z in zones1] == [z.zone_id for z in zones2]
        assert [z.confluence_score for z in zones1] == [z.confluence_score for z in zones2]

    def test_zone_ids_are_stable(self):
        p1 = _price_proj(50000.0, 49000.0, 51000.0, source="stable_1")
        p2 = _price_proj(50200.0, 49800.0, 51200.0, source="stable_2")
        zones_a = build_confluence_zones([p1, p2])
        zones_b = build_confluence_zones([p1, p2])
        assert zones_a[0].zone_id == zones_b[0].zone_id

    def test_to_dict_json_serialisable(self):
        p1 = _price_proj(50000.0, 49000.0, 51000.0)
        p2 = _time_proj(_T0, _T1)
        zones = build_confluence_zones([p1, p2])
        for z in zones:
            json.dumps(z.to_dict())  # must not raise


# ── Contributing projection IDs ───────────────────────────────────────────────


class TestContributingIds:
    def test_contributing_ids_correct(self):
        p1 = _price_proj(50000.0, 49000.0, 51000.0)
        p2 = _price_proj(50200.0, 49800.0, 51200.0)
        zones = build_confluence_zones([p1, p2])
        ids = set(zones[0].contributing_projection_ids)
        assert p1.projection_id in ids
        assert p2.projection_id in ids

    def test_no_duplicate_ids(self):
        p1 = _price_proj(50000.0, 49000.0, 51000.0)
        p2 = _price_proj(50200.0, 49800.0, 51200.0)
        zones = build_confluence_zones([p1, p2])
        ids = zones[0].contributing_projection_ids
        assert len(ids) == len(set(ids))
