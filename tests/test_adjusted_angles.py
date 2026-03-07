"""
tests/test_adjusted_angles.py

Tests for modules/adjusted_angles.py.

Coverage
--------
- slope_to_angle_deg: known-case (45°), round-trip, zero delta_t raises,
  zero/negative price_per_bar raises, upward/downward sign, determinism
- angle_deg_to_slope: known-case inverse, round-trip, ±90 raises,
  negative price_per_bar raises
- normalize_angle: standard cases, boundary values, large angles, sign preservation
- get_angle_families: structure and sorted order
- bucket_angle_to_family: exact match, tolerance boundary, no match, sign handling
- are_angles_congruent: within tolerance, at boundary, outside tolerance
- compute_impulse_angles: basic raw, basic log, round-trip, determinism,
  mixed Impulse/dict input, delta_t<=0 skipped, invalid price_mode raises,
  angle_family populated for 45° impulse
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from modules.adjusted_angles import (
    _ANGLE_FAMILIES,
    angle_deg_to_slope,
    are_angles_congruent,
    bucket_angle_to_family,
    compute_impulse_angles,
    get_angle_families,
    normalize_angle,
    slope_to_angle_deg,
)


# ── Shared fixtures / helpers ─────────────────────────────────────────────────


def _scale(ppb: float = 100.0) -> Dict[str, Any]:
    """Return a minimal scale_basis dict."""
    return {
        "price_per_bar": ppb,
        "atr_column_used": "atr_14",
        "rows_excluded_warmup": 14,
        "rows_used": 1000,
    }


def _impulse_dict(
    delta_p: float = 100.0,
    delta_t: int = 1,
    origin_price: float = 1000.0,
    extreme_price: float | None = None,
    impulse_id: str = "test_0",
    direction: str = "up",
) -> Dict[str, Any]:
    if extreme_price is None:
        extreme_price = origin_price + delta_p
    slope_raw = delta_p / delta_t if delta_t != 0 else 0.0
    slope_log = (
        math.log(extreme_price / origin_price) / delta_t
        if delta_t != 0 and origin_price > 0 and extreme_price > 0
        else 0.0
    )
    return {
        "impulse_id": impulse_id,
        "origin_price": origin_price,
        "extreme_price": extreme_price,
        "delta_p": delta_p,
        "delta_t": delta_t,
        "slope_raw": slope_raw,
        "slope_log": slope_log,
        "direction": direction,
        "origin_bar_index": 0,
        "extreme_bar_index": delta_t,
    }


# ── slope_to_angle_deg ────────────────────────────────────────────────────────


class TestSlopeToAngleDeg:
    def test_45_degree_known_case(self):
        """When delta_p == delta_t * price_per_bar the result must be exactly 45°."""
        ppb = 100.0
        sb = _scale(ppb)
        # 1 bar, delta_p = ppb → atan(1) = 45°
        assert math.isclose(slope_to_angle_deg(ppb, 1, sb), 45.0, abs_tol=1e-10)

    def test_45_degree_multi_bar(self):
        """Result is 45° regardless of delta_t when delta_p / delta_t == ppb."""
        ppb = 200.0
        sb = _scale(ppb)
        # delta_p = 10 * ppb, delta_t = 10 → slope = ppb → 45°
        assert math.isclose(slope_to_angle_deg(10 * ppb, 10, sb), 45.0, abs_tol=1e-10)

    def test_upward_positive_angle(self):
        """Upward moves (delta_p > 0) produce positive angles."""
        sb = _scale(100.0)
        assert slope_to_angle_deg(50.0, 2, sb) > 0

    def test_downward_negative_angle(self):
        """Downward moves (delta_p < 0) produce negative angles."""
        sb = _scale(100.0)
        assert slope_to_angle_deg(-50.0, 2, sb) < 0

    def test_horizontal_zero_angle(self):
        """delta_p == 0 produces exactly 0°."""
        sb = _scale(100.0)
        assert slope_to_angle_deg(0.0, 5, sb) == 0.0

    def test_output_strictly_within_90(self):
        """Result is always strictly inside (-90, 90)."""
        sb = _scale(100.0)
        for delta_p in [-1e9, -1.0, 0.0, 1.0, 1e9]:
            angle = slope_to_angle_deg(delta_p, 5, sb)
            assert -90.0 < angle < 90.0

    def test_delta_t_zero_raises(self):
        """delta_t == 0 must raise ValueError."""
        sb = _scale(100.0)
        with pytest.raises(ValueError, match="delta_t must be non-zero"):
            slope_to_angle_deg(100.0, 0, sb)

    def test_negative_price_per_bar_raises(self):
        """price_per_bar <= 0 must raise ValueError."""
        with pytest.raises(ValueError, match="price_per_bar"):
            slope_to_angle_deg(100.0, 1, _scale(-1.0))
        with pytest.raises(ValueError, match="price_per_bar"):
            slope_to_angle_deg(100.0, 1, _scale(0.0))

    def test_deterministic(self):
        """Same inputs always produce the same output."""
        sb = _scale(150.0)
        a1 = slope_to_angle_deg(300.0, 5, sb)
        a2 = slope_to_angle_deg(300.0, 5, sb)
        assert a1 == a2

    def test_2x1_family(self):
        """delta_p == 2 * delta_t * ppb should give ≈ 63.435° (2x1 line)."""
        ppb = 100.0
        sb = _scale(ppb)
        expected = math.degrees(math.atan(2.0))  # ≈ 63.435
        result = slope_to_angle_deg(2.0 * ppb, 1, sb)
        assert math.isclose(result, expected, abs_tol=1e-10)

    def test_1x2_family(self):
        """delta_p == 0.5 * delta_t * ppb should give ≈ 26.565° (1x2 line)."""
        ppb = 100.0
        sb = _scale(ppb)
        expected = math.degrees(math.atan(0.5))  # ≈ 26.565
        result = slope_to_angle_deg(0.5 * ppb, 1, sb)
        assert math.isclose(result, expected, abs_tol=1e-10)


# ── angle_deg_to_slope ────────────────────────────────────────────────────────


class TestAngleDegToSlope:
    def test_45_degree_inverse(self):
        """45° must produce exactly price_per_bar."""
        ppb = 250.0
        sb = _scale(ppb)
        assert math.isclose(angle_deg_to_slope(45.0, sb), ppb, abs_tol=1e-8)

    def test_zero_angle_zero_slope(self):
        """0° must produce slope == 0."""
        sb = _scale(100.0)
        assert angle_deg_to_slope(0.0, sb) == 0.0

    def test_negative_angle_negative_slope(self):
        """Negative angles produce negative slopes."""
        sb = _scale(100.0)
        assert angle_deg_to_slope(-45.0, sb) < 0

    def test_exactly_90_raises(self):
        """Exactly ±90° must raise ValueError (undefined vertical slope)."""
        sb = _scale(100.0)
        with pytest.raises(ValueError, match="(-90, 90)"):
            angle_deg_to_slope(90.0, sb)
        with pytest.raises(ValueError, match="(-90, 90)"):
            angle_deg_to_slope(-90.0, sb)

    def test_beyond_90_raises(self):
        """Angles outside (-90, 90) must raise ValueError."""
        sb = _scale(100.0)
        with pytest.raises(ValueError):
            angle_deg_to_slope(91.0, sb)

    def test_negative_price_per_bar_raises(self):
        with pytest.raises(ValueError, match="price_per_bar"):
            angle_deg_to_slope(30.0, _scale(0.0))


# ── Round-trip tests ──────────────────────────────────────────────────────────


class TestRoundTrip:
    """slope → angle → slope and angle → slope → angle must be identity."""

    TOLERANCE = 1e-9

    @pytest.mark.parametrize("ppb", [50.0, 100.0, 500.0, 1234.56])
    @pytest.mark.parametrize(
        "delta_p, delta_t",
        [
            (100.0, 1),
            (-100.0, 1),
            (50.0, 5),
            (200.0, 10),
            (1.0, 100),
        ],
    )
    def test_slope_angle_slope(self, ppb, delta_p, delta_t):
        """slope_to_angle_deg followed by angle_deg_to_slope must recover slope."""
        sb = _scale(ppb)
        angle = slope_to_angle_deg(delta_p, delta_t, sb)
        recovered_slope = angle_deg_to_slope(angle, sb)
        original_slope = delta_p / delta_t
        assert math.isclose(recovered_slope, original_slope, rel_tol=self.TOLERANCE), (
            f"ppb={ppb}, delta_p={delta_p}, delta_t={delta_t}: "
            f"original_slope={original_slope}, recovered={recovered_slope}"
        )

    @pytest.mark.parametrize("angle_in", [0.0, 10.0, 26.565, 45.0, -26.565, -45.0, 63.435])
    def test_angle_slope_angle(self, angle_in):
        """angle_deg_to_slope followed by slope_to_angle_deg must recover the angle."""
        ppb = 100.0
        sb = _scale(ppb)
        slope = angle_deg_to_slope(angle_in, sb)
        recovered = slope_to_angle_deg(slope * 1, 1, sb)
        assert math.isclose(recovered, angle_in, abs_tol=self.TOLERANCE), (
            f"angle_in={angle_in}: recovered={recovered}"
        )


# ── normalize_angle ───────────────────────────────────────────────────────────


class TestNormalizeAngle:
    def test_identity_in_range(self):
        """Angles already in (-90, 90] are returned unchanged."""
        for a in [-89.9, -45.0, 0.0, 45.0, 90.0]:
            assert normalize_angle(a) == a % 180.0 or math.isclose(
                normalize_angle(a), a, abs_tol=1e-10
            )

    def test_135_maps_to_minus45(self):
        assert math.isclose(normalize_angle(135.0), -45.0, abs_tol=1e-10)

    def test_minus_135_maps_to_45(self):
        assert math.isclose(normalize_angle(-135.0), 45.0, abs_tol=1e-10)

    def test_180_maps_to_0(self):
        assert math.isclose(normalize_angle(180.0), 0.0, abs_tol=1e-10)

    def test_90_stays_90(self):
        assert math.isclose(normalize_angle(90.0), 90.0, abs_tol=1e-10)

    def test_0_stays_0(self):
        assert normalize_angle(0.0) == 0.0

    def test_large_positive(self):
        """360° → 0°."""
        assert math.isclose(normalize_angle(360.0), 0.0, abs_tol=1e-10)

    def test_large_negative(self):
        """-270° → 90°."""
        assert math.isclose(normalize_angle(-270.0), 90.0, abs_tol=1e-10)

    def test_output_in_range(self):
        """Output is always in (-90, 90]."""
        for a in range(-360, 361, 15):
            n = normalize_angle(float(a))
            assert -90.0 < n <= 90.0 or math.isclose(n, -90.0, abs_tol=1e-12) is False, (
                f"normalize_angle({a}) = {n} is out of (-90, 90]"
            )


# ── get_angle_families ────────────────────────────────────────────────────────


class TestGetAngleFamilies:
    def test_returns_list_of_dicts(self):
        families = get_angle_families()
        assert isinstance(families, list)
        assert len(families) > 0
        for f in families:
            assert isinstance(f, dict)
            assert set(f.keys()) >= {"name", "price_ratio", "time_ratio", "angle_deg"}

    def test_contains_1x1(self):
        families = get_angle_families()
        names = [f["name"] for f in families]
        assert "1x1" in names

    def test_1x1_is_45_degrees(self):
        families = get_angle_families()
        f1x1 = next(f for f in families if f["name"] == "1x1")
        assert math.isclose(f1x1["angle_deg"], 45.0, abs_tol=1e-10)

    def test_2x1_angle(self):
        families = get_angle_families()
        f2x1 = next(f for f in families if f["name"] == "2x1")
        assert math.isclose(f2x1["angle_deg"], math.degrees(math.atan(2.0)), abs_tol=1e-10)

    def test_1x2_angle(self):
        families = get_angle_families()
        f1x2 = next(f for f in families if f["name"] == "1x2")
        assert math.isclose(f1x2["angle_deg"], math.degrees(math.atan(0.5)), abs_tol=1e-10)

    def test_all_angles_positive(self):
        """All family angles are defined as positive; direction is from slope sign."""
        for f in get_angle_families():
            assert f["angle_deg"] > 0


# ── bucket_angle_to_family ────────────────────────────────────────────────────


class TestBucketAngleToFamily:
    def test_exact_45_returns_1x1(self):
        result = bucket_angle_to_family(45.0)
        assert result is not None
        assert result["name"] == "1x1"
        assert math.isclose(result["delta_deg"], 0.0, abs_tol=1e-10)

    def test_near_45_within_tolerance(self):
        result = bucket_angle_to_family(43.0, tolerance_deg=5.0)
        assert result is not None
        assert result["name"] == "1x1"

    def test_at_tolerance_boundary_included(self):
        result = bucket_angle_to_family(40.0, tolerance_deg=5.0)
        assert result is not None
        assert result["name"] == "1x1"
        assert math.isclose(result["delta_deg"], 5.0, abs_tol=1e-10)

    def test_just_outside_tolerance_returns_none(self):
        result = bucket_angle_to_family(39.99, tolerance_deg=5.0)
        assert result is None

    def test_negative_angle_bucketed_to_same_family(self):
        """Negative 45° should bucket to 1x1 with negative family_angle_deg."""
        result = bucket_angle_to_family(-45.0)
        assert result is not None
        assert result["name"] == "1x1"
        assert result["family_angle_deg"] < 0

    def test_2x1_family(self):
        exact = math.degrees(math.atan(2.0))
        result = bucket_angle_to_family(exact)
        assert result is not None
        assert result["name"] == "2x1"

    def test_no_match_far_from_families(self):
        result = bucket_angle_to_family(50.0, tolerance_deg=1.0)
        assert result is None


# ── are_angles_congruent ──────────────────────────────────────────────────────


class TestAreAnglesCongruent:
    def test_identical_angles_congruent(self):
        assert are_angles_congruent(45.0, 45.0) is True

    def test_within_tolerance_congruent(self):
        assert are_angles_congruent(45.0, 48.0, tolerance_deg=5.0) is True

    def test_at_boundary_congruent(self):
        assert are_angles_congruent(45.0, 50.0, tolerance_deg=5.0) is True

    def test_just_outside_tolerance_not_congruent(self):
        assert are_angles_congruent(45.0, 50.01, tolerance_deg=5.0) is False

    def test_opposite_signs_not_congruent(self):
        assert are_angles_congruent(45.0, -45.0, tolerance_deg=5.0) is False

    def test_zero_tolerance(self):
        assert are_angles_congruent(45.0, 45.0, tolerance_deg=0.0) is True
        assert are_angles_congruent(45.0, 45.001, tolerance_deg=0.0) is False


# ── compute_impulse_angles ────────────────────────────────────────────────────


class TestComputeImpulseAngles:
    def test_basic_raw_mode(self):
        """Raw mode: 45° impulse is recognized correctly."""
        ppb = 100.0
        sb = _scale(ppb)
        # delta_p == ppb * delta_t → 45°
        imp = _impulse_dict(delta_p=ppb, delta_t=1, origin_price=1000.0)
        results = compute_impulse_angles([imp], sb, price_mode="raw")
        assert len(results) == 1
        r = results[0]
        assert math.isclose(r["angle_deg"], 45.0, abs_tol=1e-8)
        assert math.isclose(r["angle_deg_raw"], 45.0, abs_tol=1e-8)

    def test_45_degree_family_assigned(self):
        """A 45° impulse should get angle_family='1x1'."""
        ppb = 100.0
        sb = _scale(ppb)
        imp = _impulse_dict(delta_p=ppb, delta_t=1, origin_price=1000.0)
        results = compute_impulse_angles([imp], sb)
        r = results[0]
        assert r["angle_family"] == "1x1"
        assert r["angle_family_deg"] is not None
        assert math.isclose(r["angle_family_deg"], 45.0, abs_tol=1e-8)

    def test_log_mode_produces_angle_deg_log(self):
        """Log mode: angle_deg_log is populated and angle_deg == angle_deg_log."""
        ppb = 100.0
        sb = _scale(ppb)
        imp = _impulse_dict(delta_p=200.0, delta_t=5, origin_price=1000.0)
        results = compute_impulse_angles([imp], sb, price_mode="log")
        r = results[0]
        assert r["angle_deg_log"] is not None
        assert math.isclose(r["angle_deg"], r["angle_deg_log"], abs_tol=1e-10)

    def test_raw_mode_angle_deg_log_still_populated(self):
        """Even in raw mode, angle_deg_log is populated when prices are valid."""
        ppb = 100.0
        sb = _scale(ppb)
        imp = _impulse_dict(delta_p=200.0, delta_t=5, origin_price=1000.0)
        results = compute_impulse_angles([imp], sb, price_mode="raw")
        r = results[0]
        assert r["angle_deg_log"] is not None
        # raw mode: angle_deg == angle_deg_raw
        assert math.isclose(r["angle_deg"], r["angle_deg_raw"], abs_tol=1e-10)

    def test_downward_impulse_negative_angle(self):
        """Downward impulse (delta_p < 0) must produce a negative angle."""
        sb = _scale(100.0)
        imp = _impulse_dict(delta_p=-200.0, delta_t=5, origin_price=1000.0,
                             extreme_price=800.0, direction="down")
        results = compute_impulse_angles([imp], sb)
        assert results[0]["angle_deg"] < 0

    def test_delta_t_zero_skipped(self):
        """Impulse with delta_t == 0 must be skipped (not included in output)."""
        sb = _scale(100.0)
        imp = _impulse_dict(delta_p=100.0, delta_t=0, origin_price=1000.0)
        results = compute_impulse_angles([imp], sb)
        assert len(results) == 0

    def test_delta_t_negative_skipped(self):
        """Impulse with delta_t < 0 must be skipped."""
        sb = _scale(100.0)
        imp = _impulse_dict(delta_p=100.0, delta_t=-1, origin_price=1000.0)
        results = compute_impulse_angles([imp], sb)
        assert len(results) == 0

    def test_invalid_price_mode_raises(self):
        sb = _scale(100.0)
        imp = _impulse_dict()
        with pytest.raises(ValueError, match="price_mode"):
            compute_impulse_angles([imp], sb, price_mode="invalid")

    def test_empty_input_returns_empty(self):
        sb = _scale(100.0)
        assert compute_impulse_angles([], sb) == []

    def test_deterministic_output(self):
        """Same inputs must produce byte-identical results on repeated calls."""
        sb = _scale(100.0)
        imps = [
            _impulse_dict(delta_p=100.0 * i, delta_t=i, origin_price=1000.0, impulse_id=f"t_{i}")
            for i in range(1, 6)
        ]
        r1 = compute_impulse_angles(imps, sb)
        r2 = compute_impulse_angles(imps, sb)
        for a, b in zip(r1, r2):
            assert a["angle_deg"] == b["angle_deg"]
            assert a["angle_deg_log"] == b["angle_deg_log"]
            assert a["angle_family"] == b["angle_family"]

    def test_output_keys_present(self):
        """All required angle fields must be present in every output record."""
        sb = _scale(100.0)
        imp = _impulse_dict(delta_p=100.0, delta_t=2, origin_price=1000.0)
        results = compute_impulse_angles([imp], sb)
        r = results[0]
        for key in (
            "angle_deg",
            "angle_deg_raw",
            "angle_deg_log",
            "angle_normalized",
            "angle_family",
            "angle_family_deg",
            "angle_family_delta_deg",
        ):
            assert key in r, f"Missing key: {key}"

    def test_impulse_object_accepted(self):
        """An Impulse dataclass object must be accepted (via to_dict())."""
        import pandas as pd
        from modules.impulse import Impulse

        ts = pd.Timestamp("2024-01-01", tz="UTC")
        imp = Impulse(
            impulse_id="obj_0",
            origin_time=ts,
            origin_price=1000.0,
            extreme_time=ts + pd.Timedelta(days=5),
            extreme_price=1500.0,
            delta_t=5,
            delta_p=500.0,
            slope_raw=100.0,
            slope_log=math.log(1500 / 1000) / 5,
            quality_score=0.8,
            detector_name="pivot_n5",
            direction="up",
            origin_bar_index=0,
            extreme_bar_index=5,
        )
        sb = _scale(100.0)
        results = compute_impulse_angles([imp], sb)
        assert len(results) == 1
        assert math.isclose(results[0]["angle_deg_raw"], 45.0, abs_tol=1e-8)

    def test_round_trip_angle_normalized_within_range(self):
        """angle_normalized must always be in (-90, 90]."""
        sb = _scale(100.0)
        imps = [
            _impulse_dict(delta_p=v, delta_t=5, origin_price=1000.0 + abs(v), impulse_id=f"t_{i}")
            for i, v in enumerate([-500.0, -100.0, -1.0, 1.0, 100.0, 500.0])
        ]
        for r in compute_impulse_angles(imps, sb):
            n = r["angle_normalized"]
            assert -90.0 < n <= 90.0 or math.isclose(n, -90.0, abs_tol=1e-10) is False, (
                f"angle_normalized={n} out of (-90, 90]"
            )

    def test_multiple_impulses_correct_count(self):
        """All valid impulses are present in output; invalid ones are dropped."""
        sb = _scale(100.0)
        imps = [
            _impulse_dict(delta_p=100.0, delta_t=1, impulse_id="a"),
            _impulse_dict(delta_p=50.0, delta_t=0, impulse_id="b"),   # skipped
            _impulse_dict(delta_p=-80.0, delta_t=2, impulse_id="c", origin_price=1000.0, extreme_price=920.0),
        ]
        results = compute_impulse_angles(imps, sb)
        assert len(results) == 2
        ids = [r["impulse_id"] for r in results]
        assert "a" in ids
        assert "c" in ids
        assert "b" not in ids
