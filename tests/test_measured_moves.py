"""
tests/test_measured_moves.py

Tests for modules/measured_moves.py.

Coverage
--------
- MeasuredMoveTarget.to_dict: all keys present, JSON-serialisable
- measured_move_targets:
  - raw mode: known values for extension and retracement
  - log mode: known values, log-space symmetry
  - delta_p = 0 returns empty list
  - invalid mode raises ValueError
  - non-positive ratios skipped
  - angle_family_tag propagated to notes
  - upward and downward impulses
- compute_measured_moves:
  - empty list input returns empty
  - batch produces correct count (len(impulses) * len(ratios) * 2 directions)
  - invalid mode raises ValueError
  - angle_family_tags dict propagates to notes
  - determinism
- Edge cases: very large prices, very small delta_p, ratio=0 skipped
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd
import pytest

from modules.measured_moves import (
    MeasuredMoveTarget,
    compute_measured_moves,
    measured_move_targets,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────

_T0 = pd.Timestamp("2020-01-01 00:00:00", tz="UTC")
_T1 = pd.Timestamp("2020-04-01 00:00:00", tz="UTC")


def _make_impulse(
    origin_price: float = 100.0,
    extreme_price: float = 200.0,
    origin_bar: int = 0,
    extreme_bar: int = 50,
    direction: str = "up",
    quality_score: float = 0.8,
    impulse_id: str = "test_0",
) -> Dict[str, Any]:
    """Return a plain-dict impulse for testing."""
    delta_p = extreme_price - origin_price
    delta_t = extreme_bar - origin_bar
    return {
        "impulse_id": impulse_id,
        "delta_p": delta_p,
        "delta_t": delta_t,
        "origin_price": origin_price,
        "extreme_price": extreme_price,
        "origin_time": _T0,
        "extreme_time": _T1,
        "origin_bar_index": origin_bar,
        "extreme_bar_index": extreme_bar,
        "quality_score": quality_score,
        "direction": direction,
    }


# ── MeasuredMoveTarget.to_dict ────────────────────────────────────────────────


class TestToDict:
    def test_all_keys_present(self):
        imp = _make_impulse()
        targets = measured_move_targets(imp, ratios=[1.0], mode="raw")
        assert len(targets) >= 1
        d = targets[0].to_dict()
        expected_keys = {
            "impulse_id", "ratio", "target_price", "direction", "mode",
            "origin_price", "origin_time", "extreme_price", "extreme_time",
            "origin_bar_index", "extreme_bar_index", "quality_score", "notes",
        }
        assert set(d.keys()) == expected_keys

    def test_json_serialisable(self):
        import json
        imp = _make_impulse()
        targets = measured_move_targets(imp, ratios=[1.0], mode="raw")
        # Must not raise
        json.dumps([t.to_dict() for t in targets], default=str)


# ── Raw mode: extension targets ───────────────────────────────────────────────


class TestRawExtension:
    """Verify raw-mode extension formula: target = extreme + ratio * delta_p."""

    def test_upward_ratio_1(self):
        """origin=100, extreme=200, delta_p=100, ratio=1 → target=300."""
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[1.0], mode="raw")
        exts = [t for t in targets if t.direction == "extension"]
        assert len(exts) == 1
        assert exts[0].target_price == pytest.approx(300.0, rel=1e-10)

    def test_upward_ratio_0_5(self):
        """origin=100, extreme=200, delta_p=100, ratio=0.5 → target=250."""
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[0.5], mode="raw")
        exts = [t for t in targets if t.direction == "extension"]
        assert exts[0].target_price == pytest.approx(250.0, rel=1e-10)

    def test_upward_ratio_2(self):
        """origin=100, extreme=200, delta_p=100, ratio=2 → target=400."""
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[2.0], mode="raw")
        exts = [t for t in targets if t.direction == "extension"]
        assert exts[0].target_price == pytest.approx(400.0, rel=1e-10)

    def test_downward_ratio_1(self):
        """origin=200, extreme=100, delta_p=-100, ratio=1 → target=0."""
        imp = _make_impulse(200.0, 100.0, direction="down")
        targets = measured_move_targets(imp, ratios=[1.0], mode="raw")
        exts = [t for t in targets if t.direction == "extension"]
        assert exts[0].target_price == pytest.approx(0.0, abs=1e-10)

    def test_downward_extension_note_non_positive(self):
        """Extension target ≤ 0 for large downward impulse should note warning."""
        imp = _make_impulse(200.0, 50.0, direction="down")
        # delta_p = -150; extreme=50; extension target = 50 + 2*(-150) = -250
        targets = measured_move_targets(imp, ratios=[2.0], mode="raw")
        exts = [t for t in targets if t.direction == "extension"]
        assert exts[0].target_price < 0
        assert "WARNING" in exts[0].notes


# ── Raw mode: retracement targets ─────────────────────────────────────────────


class TestRawRetracement:
    """Verify raw-mode retracement formula: target = extreme - ratio * delta_p."""

    def test_upward_ratio_0_5(self):
        """origin=100, extreme=200, delta_p=100, ratio=0.5 → target=150."""
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[0.5], mode="raw")
        rets = [t for t in targets if t.direction == "retracement"]
        assert rets[0].target_price == pytest.approx(150.0, rel=1e-10)

    def test_upward_ratio_1(self):
        """origin=100, extreme=200, ratio=1 → retracement to origin=100."""
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[1.0], mode="raw")
        rets = [t for t in targets if t.direction == "retracement"]
        assert rets[0].target_price == pytest.approx(100.0, rel=1e-10)

    def test_upward_ratio_1_5(self):
        """origin=100, extreme=200, ratio=1.5 → target=200-150=50 (below origin)."""
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[1.5], mode="raw")
        rets = [t for t in targets if t.direction == "retracement"]
        assert rets[0].target_price == pytest.approx(50.0, rel=1e-10)

    def test_downward_ratio_0_5(self):
        """origin=200, extreme=100, delta_p=-100, ratio=0.5 → target=150."""
        imp = _make_impulse(200.0, 100.0, direction="down")
        targets = measured_move_targets(imp, ratios=[0.5], mode="raw")
        rets = [t for t in targets if t.direction == "retracement"]
        assert rets[0].target_price == pytest.approx(150.0, rel=1e-10)

    def test_downward_ratio_1(self):
        """origin=200, extreme=100, ratio=1 → retracement back to origin=200."""
        imp = _make_impulse(200.0, 100.0, direction="down")
        targets = measured_move_targets(imp, ratios=[1.0], mode="raw")
        rets = [t for t in targets if t.direction == "retracement"]
        assert rets[0].target_price == pytest.approx(200.0, rel=1e-10)


# ── Log mode: extension and retracement targets ───────────────────────────────


class TestLogMode:
    """Verify log-mode formula: target = exp(log(extreme) ± ratio * log(extreme/origin))."""

    def test_upward_extension_ratio_1(self):
        """
        origin=100, extreme=200, log_delta=log(2).
        extension ratio=1: target = exp(log(200) + log(2)) = exp(log(400)) = 400.
        """
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[1.0], mode="log")
        exts = [t for t in targets if t.direction == "extension"]
        assert exts[0].target_price == pytest.approx(400.0, rel=1e-10)

    def test_upward_retracement_ratio_1(self):
        """
        origin=100, extreme=200, log_delta=log(2).
        retracement ratio=1: target = exp(log(200) - log(2)) = exp(log(100)) = 100.
        """
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[1.0], mode="log")
        rets = [t for t in targets if t.direction == "retracement"]
        assert rets[0].target_price == pytest.approx(100.0, rel=1e-10)

    def test_upward_extension_ratio_0_5(self):
        """
        origin=100, extreme=200.
        log_delta = log(2).
        extension 0.5: exp(log(200) + 0.5*log(2)) = 200 * sqrt(2) ≈ 282.84...
        """
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[0.5], mode="log")
        exts = [t for t in targets if t.direction == "extension"]
        expected = 200.0 * math.sqrt(2.0)
        assert exts[0].target_price == pytest.approx(expected, rel=1e-10)

    def test_log_mode_label(self):
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[1.0], mode="log")
        assert all(t.mode == "log" for t in targets)

    def test_log_symmetry(self):
        """
        In log mode, extension(1.0) and retracement(1.0) should satisfy:
        geometric mean of their targets = extreme^2 / origin
        Actually: ext_price * ret_price = extreme^2.
        """
        imp = _make_impulse(100.0, 200.0)
        targets = measured_move_targets(imp, ratios=[1.0], mode="log")
        ext_price = next(t.target_price for t in targets if t.direction == "extension")
        ret_price = next(t.target_price for t in targets if t.direction == "retracement")
        # exp(log(E)+log_d) * exp(log(E)-log_d) = exp(2*log(E)) = E^2
        assert ext_price * ret_price == pytest.approx(200.0 ** 2, rel=1e-10)


# ── delta_p = 0 ───────────────────────────────────────────────────────────────


class TestDeltaPZero:
    def test_returns_empty_list(self):
        imp = _make_impulse(100.0, 100.0)  # extreme == origin → delta_p = 0
        targets = measured_move_targets(imp, ratios=[1.0, 2.0], mode="raw")
        assert targets == []


# ── Invalid inputs ────────────────────────────────────────────────────────────


class TestInvalidInputs:
    def test_invalid_mode_raises(self):
        imp = _make_impulse()
        with pytest.raises(ValueError, match="mode"):
            measured_move_targets(imp, ratios=[1.0], mode="linear")

    def test_compute_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode"):
            compute_measured_moves([_make_impulse()], mode="bad")

    def test_nonpositive_ratio_skipped(self):
        imp = _make_impulse()
        targets = measured_move_targets(imp, ratios=[0.0, -1.0, 1.0], mode="raw")
        # Only ratio=1.0 produces targets (0 and -1.0 are skipped)
        ratios_used = {t.ratio for t in targets}
        assert 0.0 not in ratios_used
        assert -1.0 not in ratios_used
        assert 1.0 in ratios_used


# ── angle_family_tag propagation ──────────────────────────────────────────────


class TestAngleFamilyTag:
    def test_tag_in_notes(self):
        imp = _make_impulse()
        targets = measured_move_targets(
            imp, ratios=[1.0], mode="raw", angle_family_tag="1x1"
        )
        for t in targets:
            assert "angle_family=1x1" in t.notes

    def test_no_tag_no_notes(self):
        imp = _make_impulse()
        targets = measured_move_targets(imp, ratios=[1.0], mode="raw")
        # Without a tag, notes should not mention angle_family
        for t in targets:
            assert "angle_family" not in t.notes


# ── compute_measured_moves (batch) ────────────────────────────────────────────


class TestComputeMeasuredMoves:
    def test_empty_impulses_returns_empty(self):
        result = compute_measured_moves([], ratios=[1.0])
        assert result == []

    def test_count_two_impulses_two_ratios(self):
        """2 impulses × 2 ratios × 2 directions = 8 targets."""
        impulses = [_make_impulse(impulse_id=f"test_{i}") for i in range(2)]
        targets = compute_measured_moves(impulses, ratios=[0.5, 1.0], mode="raw")
        assert len(targets) == 2 * 2 * 2

    def test_count_default_ratios(self):
        """1 impulse × 4 default ratios × 2 directions = 8 targets."""
        targets = compute_measured_moves([_make_impulse()], mode="raw")
        assert len(targets) == 1 * 4 * 2

    def test_batch_log_mode(self):
        impulses = [_make_impulse(impulse_id="log_test")]
        targets = compute_measured_moves(impulses, ratios=[1.0], mode="log")
        assert all(t.mode == "log" for t in targets)

    def test_angle_tags_dict(self):
        imp = _make_impulse(impulse_id="imp_0")
        targets = compute_measured_moves(
            [imp],
            ratios=[1.0],
            mode="raw",
            angle_family_tags={"imp_0": "2x1"},
        )
        for t in targets:
            assert "angle_family=2x1" in t.notes

    def test_deterministic(self):
        impulses = [_make_impulse()]
        r1 = [t.target_price for t in compute_measured_moves(impulses, ratios=[0.5, 1.0])]
        r2 = [t.target_price for t in compute_measured_moves(impulses, ratios=[0.5, 1.0])]
        assert r1 == r2

    def test_default_ratios(self):
        """Default ratios are [0.5, 1.0, 1.5, 2.0]."""
        targets = compute_measured_moves([_make_impulse()])
        ratios_found = sorted({t.ratio for t in targets})
        assert ratios_found == [0.5, 1.0, 1.5, 2.0]

    def test_quality_score_propagated(self):
        imp = _make_impulse(quality_score=0.75)
        targets = compute_measured_moves([imp], ratios=[1.0])
        for t in targets:
            assert t.quality_score == pytest.approx(0.75, rel=1e-10)


# ── Realistic BTC-like values ─────────────────────────────────────────────────


class TestRealisticValues:
    def test_btc_upward_impulse(self):
        """
        Simulate a BTC impulse: origin=3000, extreme=60000.
        Raw extension ratio=1.0 → 60000 + 57000 = 117000.
        Raw retracement ratio=0.5 → 60000 - 28500 = 31500.
        """
        imp = _make_impulse(3000.0, 60000.0)
        targets = measured_move_targets(imp, ratios=[0.5, 1.0], mode="raw")

        ext_1 = next(t for t in targets if t.direction == "extension" and t.ratio == 1.0)
        ret_05 = next(t for t in targets if t.direction == "retracement" and t.ratio == 0.5)

        assert ext_1.target_price == pytest.approx(117000.0, rel=1e-10)
        assert ret_05.target_price == pytest.approx(31500.0, rel=1e-10)
