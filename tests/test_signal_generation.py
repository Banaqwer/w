"""
tests/test_signal_generation.py

Tests for signals/signal_generation.py — generate_signals, build_projection_index,
bias determination, invalidation rules, gap-policy behavior.

Coverage
--------
- Empty zones and projections → empty signal list
- Bias assignment correctness on synthetic zone sets
  - majority support → long
  - majority resistance → short
  - equal support/resistance → neutral
  - all turn/ambiguous → neutral
- Neutral threshold: skipped below min_score_for_neutral
- Zones without price_window skipped
- Entry region populated from zone.price_window
- Entry region time window populated from zone.time_window when present
- Invalidation rules: long gets close_below_zone; short gets close_above_zone
- Invalidation buffer propagated
- Time invalidation rule added when zone has time_window
- Gap policy: missing_bar_count > 0 adds strict_multi_candle
- Determinism: identical inputs produce identical outputs
- Provenance contains projection IDs and module names
- quality_score inherits zone confluence_score
- build_projection_index returns correct dict
"""

from __future__ import annotations

import hashlib
from typing import List, Optional

import pandas as pd
import pytest

from signals.projections import ConfluenceZone, Projection
from signals.signal_generation import build_projection_index, generate_signals
from signals.signal_types import SignalCandidate


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_proj(
    pid: str,
    module: str = "measured_moves",
    direction: str = "support",
    price_lo: Optional[float] = 100.0,
    price_hi: Optional[float] = 110.0,
    raw_score: float = 0.5,
) -> Projection:
    pb = (price_lo, price_hi)
    return Projection(
        projection_id=pid,
        module_name=module,
        source_id=f"src_{pid}",
        projected_time=None,
        projected_price=(price_lo + price_hi) / 2 if price_lo and price_hi else None,
        time_band=(None, None),
        price_band=pb,
        direction_hint=direction,
        raw_score=raw_score,
    )


def _make_zone(
    zone_id: str,
    proj_ids: List[str],
    price_lo: float = 100.0,
    price_hi: float = 110.0,
    score: float = 0.4,
    time_window=None,
    module_counts: Optional[dict] = None,
    notes: str = "type=price_only",
) -> ConfluenceZone:
    return ConfluenceZone(
        zone_id=zone_id,
        price_window=(price_lo, price_hi),
        time_window=time_window,
        contributing_projection_ids=proj_ids,
        confluence_score=score,
        module_counts=module_counts or {"measured_moves": len(proj_ids)},
        notes=notes,
    )


_DATASET_VERSION = "proc_TEST_1D_v1"


# ── build_projection_index ────────────────────────────────────────────────────


class TestBuildProjectionIndex:
    def test_empty(self):
        assert build_projection_index([]) == {}

    def test_single(self):
        p = _make_proj("p1")
        idx = build_projection_index([p])
        assert "p1" in idx
        assert idx["p1"] is p

    def test_multiple(self):
        projs = [_make_proj(f"p{i}") for i in range(5)]
        idx = build_projection_index(projs)
        assert len(idx) == 5
        for i in range(5):
            assert f"p{i}" in idx

    def test_duplicate_id_last_wins(self):
        p1 = _make_proj("p1", direction="support")
        p2 = _make_proj("p1", direction="resistance")
        idx = build_projection_index([p1, p2])
        assert idx["p1"].direction_hint == "resistance"


# ── generate_signals — empty / edge cases ────────────────────────────────────


class TestGenerateSignalsEdgeCases:
    def test_empty_zones_returns_empty(self):
        result = generate_signals([], [], _DATASET_VERSION)
        assert result == []

    def test_zones_without_price_window_skipped(self):
        zone = ConfluenceZone(
            zone_id="z1",
            price_window=None,
            time_window=None,
            contributing_projection_ids=[],
            confluence_score=0.9,
            module_counts={},
        )
        result = generate_signals([zone], [], _DATASET_VERSION)
        assert result == []

    def test_zone_with_no_projections_in_index_returns_neutral(self):
        """Zone with projection IDs not in the index → counts=0 → neutral."""
        zone = _make_zone("z1", ["unknown_proj"], score=0.8)
        # supply empty projections list → no direction hints → neutral
        result = generate_signals([zone], [], _DATASET_VERSION, min_score_for_neutral=0.0)
        assert len(result) == 1
        assert result[0].bias == "neutral"

    def test_invalid_buffer_raises(self):
        with pytest.raises(ValueError, match="invalidation_buffer"):
            generate_signals([], [], _DATASET_VERSION, invalidation_buffer=-0.5)

    def test_invalid_min_score_raises(self):
        with pytest.raises(ValueError, match="min_score_for_neutral"):
            generate_signals([], [], _DATASET_VERSION, min_score_for_neutral=1.5)


# ── Bias assignment ───────────────────────────────────────────────────────────


class TestBiasAssignment:
    def test_majority_support_gives_long(self):
        projs = [
            _make_proj("p1", direction="support"),
            _make_proj("p2", direction="support"),
            _make_proj("p3", direction="resistance"),
        ]
        zone = _make_zone("z1", ["p1", "p2", "p3"], score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        assert len(result) == 1
        assert result[0].bias == "long"

    def test_majority_resistance_gives_short(self):
        projs = [
            _make_proj("p1", direction="resistance"),
            _make_proj("p2", direction="resistance"),
            _make_proj("p3", direction="support"),
        ]
        zone = _make_zone("z1", ["p1", "p2", "p3"], score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        assert len(result) == 1
        assert result[0].bias == "short"

    def test_equal_support_resistance_gives_neutral(self):
        projs = [
            _make_proj("p1", direction="support"),
            _make_proj("p2", direction="resistance"),
        ]
        zone = _make_zone("z1", ["p1", "p2"], score=0.9)
        result = generate_signals([zone], projs, _DATASET_VERSION, min_score_for_neutral=0.0)
        assert len(result) == 1
        assert result[0].bias == "neutral"

    def test_all_turn_gives_neutral(self):
        projs = [
            _make_proj("p1", direction="turn"),
            _make_proj("p2", direction="turn"),
        ]
        zone = _make_zone("z1", ["p1", "p2"], score=0.9)
        result = generate_signals([zone], projs, _DATASET_VERSION, min_score_for_neutral=0.0)
        assert result[0].bias == "neutral"

    def test_all_ambiguous_gives_neutral(self):
        projs = [_make_proj("p1", direction="ambiguous")]
        zone = _make_zone("z1", ["p1"], score=0.9)
        result = generate_signals([zone], projs, _DATASET_VERSION, min_score_for_neutral=0.0)
        assert result[0].bias == "neutral"

    def test_single_support_gives_long(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.3)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        assert result[0].bias == "long"

    def test_single_resistance_gives_short(self):
        projs = [_make_proj("p1", direction="resistance")]
        zone = _make_zone("z1", ["p1"], score=0.3)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        assert result[0].bias == "short"


# ── Neutral threshold ─────────────────────────────────────────────────────────


class TestNeutralThreshold:
    def test_neutral_below_threshold_skipped(self):
        projs = [
            _make_proj("p1", direction="support"),
            _make_proj("p2", direction="resistance"),
        ]
        zone = _make_zone("z1", ["p1", "p2"], score=0.3)
        # min_score_for_neutral=0.5, zone.score=0.3 → skipped
        result = generate_signals([zone], projs, _DATASET_VERSION, min_score_for_neutral=0.5)
        assert result == []

    def test_neutral_above_threshold_included(self):
        projs = [
            _make_proj("p1", direction="support"),
            _make_proj("p2", direction="resistance"),
        ]
        zone = _make_zone("z1", ["p1", "p2"], score=0.6)
        result = generate_signals([zone], projs, _DATASET_VERSION, min_score_for_neutral=0.5)
        assert len(result) == 1
        assert result[0].bias == "neutral"

    def test_non_neutral_not_filtered_by_threshold(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.1)
        result = generate_signals([zone], projs, _DATASET_VERSION, min_score_for_neutral=0.9)
        # Long bias is not neutral → not filtered by the threshold
        assert len(result) == 1
        assert result[0].bias == "long"


# ── Entry region ──────────────────────────────────────────────────────────────


class TestEntryRegion:
    def test_entry_region_uses_price_window(self):
        projs = [_make_proj("p1", direction="support", price_lo=200.0, price_hi=210.0)]
        zone = _make_zone("z1", ["p1"], price_lo=200.0, price_hi=210.0, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        er = result[0].entry_region
        assert er.price_low == 200.0
        assert er.price_high == 210.0

    def test_entry_region_no_time_when_zone_has_no_time_window(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], time_window=None, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        er = result[0].entry_region
        assert er.time_earliest is None
        assert er.time_latest is None

    def test_entry_region_has_time_when_zone_has_time_window(self):
        t_lo = pd.Timestamp("2026-01-01", tz="UTC")
        t_hi = pd.Timestamp("2026-02-01", tz="UTC")
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], time_window=(t_lo, t_hi), score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        er = result[0].entry_region
        assert er.time_earliest == t_lo
        assert er.time_latest == t_hi


# ── Invalidation rules ────────────────────────────────────────────────────────


class TestInvalidationRules:
    def test_long_gets_close_below_zone(self):
        projs = [_make_proj("p1", direction="support", price_lo=100.0, price_hi=110.0)]
        zone = _make_zone("z1", ["p1"], price_lo=100.0, price_hi=110.0, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        inv = result[0].invalidation
        conditions = [r.condition for r in inv]
        assert "close_below_zone" in conditions
        # long should NOT get close_above_zone
        assert "close_above_zone" not in conditions

    def test_long_invalidation_price_level_is_zone_low(self):
        projs = [_make_proj("p1", direction="support", price_lo=100.0, price_hi=110.0)]
        zone = _make_zone("z1", ["p1"], price_lo=100.0, price_hi=110.0, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        inv = [r for r in result[0].invalidation if r.condition == "close_below_zone"]
        assert len(inv) == 1
        assert inv[0].price_level == 100.0

    def test_short_gets_close_above_zone(self):
        projs = [_make_proj("p1", direction="resistance", price_lo=100.0, price_hi=110.0)]
        zone = _make_zone("z1", ["p1"], price_lo=100.0, price_hi=110.0, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        inv = result[0].invalidation
        conditions = [r.condition for r in inv]
        assert "close_above_zone" in conditions
        assert "close_below_zone" not in conditions

    def test_short_invalidation_price_level_is_zone_high(self):
        projs = [_make_proj("p1", direction="resistance", price_lo=100.0, price_hi=110.0)]
        zone = _make_zone("z1", ["p1"], price_lo=100.0, price_hi=110.0, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        inv = [r for r in result[0].invalidation if r.condition == "close_above_zone"]
        assert inv[0].price_level == 110.0

    def test_neutral_gets_both_directions(self):
        projs = [
            _make_proj("p1", direction="support"),
            _make_proj("p2", direction="resistance"),
        ]
        zone = _make_zone("z1", ["p1", "p2"], score=0.9)
        result = generate_signals([zone], projs, _DATASET_VERSION, min_score_for_neutral=0.0)
        conditions = [r.condition for r in result[0].invalidation]
        assert "close_below_zone" in conditions
        assert "close_above_zone" in conditions

    def test_buffer_propagated_to_invalidation(self):
        projs = [_make_proj("p1", direction="support", price_lo=100.0, price_hi=110.0)]
        zone = _make_zone("z1", ["p1"], price_lo=100.0, price_hi=110.0, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION, invalidation_buffer=5.0)
        inv = [r for r in result[0].invalidation if r.condition == "close_below_zone"]
        assert inv[0].buffer == 5.0

    def test_time_invalidation_added_when_zone_has_time_window(self):
        t_lo = pd.Timestamp("2026-01-01", tz="UTC")
        t_hi = pd.Timestamp("2026-06-01", tz="UTC")
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], time_window=(t_lo, t_hi), score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        conditions = [r.condition for r in result[0].invalidation]
        assert "time_expired" in conditions
        time_inv = [r for r in result[0].invalidation if r.condition == "time_expired"]
        assert time_inv[0].time_cutoff == t_hi

    def test_no_time_invalidation_without_time_window(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], time_window=None, score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        conditions = [r.condition for r in result[0].invalidation]
        assert "time_expired" not in conditions


# ── Gap policy ────────────────────────────────────────────────────────────────


class TestGapPolicy:
    def test_no_gap_does_not_add_strict_confirmation(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.5)
        manifest = {"missing_bar_count": 0}
        result = generate_signals([zone], projs, _DATASET_VERSION, manifest=manifest)
        assert "strict_multi_candle" not in result[0].confirmations_required

    def test_gap_adds_strict_multi_candle(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.5)
        manifest = {"missing_bar_count": 1}
        result = generate_signals([zone], projs, _DATASET_VERSION, manifest=manifest)
        assert "strict_multi_candle" in result[0].confirmations_required

    def test_gap_recorded_in_metadata(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.5)
        manifest = {"missing_bar_count": 2}
        result = generate_signals([zone], projs, _DATASET_VERSION, manifest=manifest)
        assert result[0].metadata["missing_bar_count"] == 2
        assert "gap_note" in result[0].metadata

    def test_no_gap_no_gap_note(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.5)
        manifest = {"missing_bar_count": 0}
        result = generate_signals([zone], projs, _DATASET_VERSION, manifest=manifest)
        assert "gap_note" not in result[0].metadata

    def test_base_confirmations_always_present(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION, manifest={"missing_bar_count": 0})
        reqs = result[0].confirmations_required
        assert "candle_direction" in reqs
        assert "zone_rejection" in reqs


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_inputs_same_output(self):
        projs = [
            _make_proj("p1", direction="support"),
            _make_proj("p2", direction="support"),
            _make_proj("p3", direction="resistance"),
        ]
        zone = _make_zone("z1", ["p1", "p2", "p3"], score=0.6)

        r1 = generate_signals([zone], projs, _DATASET_VERSION)
        r2 = generate_signals([zone], projs, _DATASET_VERSION)
        assert len(r1) == len(r2)
        assert r1[0].signal_id == r2[0].signal_id
        assert r1[0].bias == r2[0].bias
        assert r1[0].quality_score == r2[0].quality_score

    def test_signal_id_matches_expected_hash(self):
        """signal_id must be reproducible from zone_id + bias + dataset_version."""
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        s = result[0]
        raw = f"{s.zone_id}|{s.bias}|{s.dataset_version}"
        expected_id = hashlib.sha1(raw.encode()).hexdigest()[:16]
        assert s.signal_id == expected_id


# ── Quality score ─────────────────────────────────────────────────────────────


class TestQualityScore:
    def test_quality_score_inherits_confluence_score(self):
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=0.73)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        assert result[0].quality_score == pytest.approx(0.73)

    def test_quality_score_clamped_to_one(self):
        """confluence_score > 1.0 would be a bug but quality_score is clamped."""
        projs = [_make_proj("p1", direction="support")]
        zone = _make_zone("z1", ["p1"], score=1.0)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        assert result[0].quality_score <= 1.0


# ── Provenance ────────────────────────────────────────────────────────────────


class TestProvenance:
    def test_provenance_contains_projection_ids(self):
        projs = [
            _make_proj("p1", direction="support"),
            _make_proj("p2", direction="support"),
        ]
        zone = _make_zone("z1", ["p1", "p2"], score=0.5)
        result = generate_signals([zone], projs, _DATASET_VERSION)
        prov = result[0].provenance
        assert "p1" in prov
        assert "p2" in prov

    def test_provenance_contains_module_names(self):
        projs = [
            _make_proj("p1", module="jttl", direction="support"),
            _make_proj("p2", module="measured_moves", direction="support"),
        ]
        zone = _make_zone("z1", ["p1", "p2"], score=0.5, module_counts={"jttl": 1, "measured_moves": 1})
        result = generate_signals([zone], projs, _DATASET_VERSION)
        prov = result[0].provenance
        assert "module:jttl" in prov
        assert "module:measured_moves" in prov
