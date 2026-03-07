# Phase 3A Review — Adjusted Angles Module

**Date:** 2026-03-07
**Reviewer:** automated
**Verdict:** PASS

---

## Scope reviewed

| File | Purpose |
|------|---------|
| `modules/adjusted_angles.py` | Adjusted-angle conversion, normalisation, family bucketing |
| `research/run_phase3_smoke.py` | End-to-end smoke-run script (Phase 2 impulses → angles) |
| `tests/test_adjusted_angles.py` | 86 angle tests |
| `PROJECT_STATUS.md` | Phase 3A completion record |
| `ASSUMPTIONS.md` | Assumptions 21–22 |
| `DECISIONS.md` | 2026-03-07 angle basis and gap policy |

---

## Check 1 — Phase 3 scope only

**Result: PASS**

No Phase 4+ drift detected.  Grep across all three Phase 3 files for
`projection`, `confluence`, `signal`, `backtest`, `TradeSignal`, `ForecastZone`
returned zero matches.

The code contains:
- No projection-zone generation (Phase 3 remaining / Phase 4)
- No confluence scoring (Phase 4)
- No confirmation / trade-signal logic (Phase 5)
- No backtest / ablation logic (Phase 6)
- No advanced geometric modules (Phase 7)

All imports are restricted to Phase 1 data/coordinate layer and Phase 2 impulse
module.  The smoke script consumes Phase 2 CSV outputs and the processed dataset
(for `get_angle_scale_basis`); it does not produce downstream trading artifacts.

`PROJECT_STATUS.md` explicitly states: "No Phase 4+ work (projections,
confluence, signals, backtest) has been started."

---

## Check 2 — Uses `core/coordinate_system.get_angle_scale_basis()` as the single authority

**Result: PASS**

### Module design

`modules/adjusted_angles.py` never computes its own scale basis.  Every public
function that needs the scale accepts a `scale_basis: Dict[str, Any]` parameter
and reads `scale_basis["price_per_bar"]`.

The module docstring (lines 20–22) states:

> The scale basis is computed once per dataset via
> `core.coordinate_system.get_angle_scale_basis(df)` and must be passed
> into every function here.  No angle function computes its own scale basis.

### Smoke script

`research/run_phase3_smoke.py` calls `get_angle_scale_basis(df,
atr_warmup_rows=...)` exactly once per dataset (line 179) and passes the result
into `compute_impulse_angles`.  No alternative scale computation exists.

### Tests

Test helper `_scale(ppb)` produces a dict matching the structure returned by
`get_angle_scale_basis`.  No test bypasses the `scale_basis` parameter.

---

## Check 3 — Deterministic + reproducible outputs

**Result: PASS**

- All computations use deterministic `math` stdlib functions (`atan`, `tan`,
  `degrees`, `radians`, `log`).  No randomness, no hash-order sensitivity,
  no floating-point non-determinism sources.
- `compute_impulse_angles` processes the input list in order and uses
  deterministic dict operations.
- Two dedicated determinism tests:
  - `TestSlopeToAngleDeg::test_deterministic` — same inputs → same output
  - `TestComputeImpulseAngles::test_deterministic_output` — batch repeated
    calls produce identical `angle_deg`, `angle_deg_log`, and `angle_family`

---

## Check 4 — Handles missing-bar situations explicitly (6H gaps)

**Result: PASS**

### Module-level gap policy

`modules/adjusted_angles.py` operates on `Impulse` objects that already carry
`delta_t` as a bar-index delta.  No raw DataFrame or timestamp access is
required.  The module docstring "Gap policy" section (lines 46–49) states:

> Angle computations operate on Impulse objects that already carry bar-index
> deltas.  No raw DataFrame access is required.  For the 6H dataset
> (missing_bar_count > 0), angles are computed using `delta_t` (bar-index
> delta), which is gap-safe (Assumption 22).

### Smoke script

`research/run_phase3_smoke.py` reads `missing_bar_count` from the manifest
(line 163) and logs a descriptive message for 6H datasets (lines 165–174):

> Phase 3 angle computation uses bar_index deltas (gap-safe).
> No impulses are skipped at this stage; gaps were already handled in Phase 2.

### Documentation

- ASSUMPTIONS.md Assumption 22: "All adjusted-angle computations use `delta_t`
  (bar-index delta) from the stored Impulse data."
- DECISIONS.md 2026-03-07: "Gap policy for Phase 3: Use `delta_t` (bar-index
  delta) from Impulse; no DataFrame access required; gap-safe for 6H."

### Layered gap defence

Phase 2 already excludes impulses that cross gaps (via `skip_on_gap=True`).
Phase 3 inherits gap-clean impulses and uses bar-index `delta_t` — a two-layer
defence that is explicitly documented.

---

## Check 5 — Tests cover round-trip correctness and edge cases

**Result: PASS**

### Round-trip tests

| Test | Cases | Tolerance |
|------|-------|-----------|
| `test_slope_angle_slope` | 20 parametrized (5 slope × 4 ppb) | rel_tol=1e-9 |
| `test_angle_slope_angle` | 7 parametrized angles | abs_tol=1e-9 |
| `test_round_trip_angle_normalized_within_range` | 6 impulses via `compute_impulse_angles` | bounds check |

### Edge-case tests

| Edge case | Test | Behaviour |
|-----------|------|-----------|
| `delta_t == 0` | `test_delta_t_zero_raises` | `ValueError` raised |
| `delta_t < 0` | `test_delta_t_negative_skipped` | Skipped (not in output) |
| `price_per_bar <= 0` | `test_negative_price_per_bar_raises` (×2) | `ValueError` raised |
| `abs(angle) >= 90` | `test_exactly_90_raises`, `test_beyond_90_raises` | `ValueError` raised |
| Very large `delta_p` | `test_output_strictly_within_90` | Output in (-90, 90) |
| Empty input | `test_empty_input_returns_empty` | Returns `[]` |
| Invalid price_mode | `test_invalid_price_mode_raises` | `ValueError` raised |
| Impulse dataclass object | `test_impulse_object_accepted` | Calls `to_dict()` |
| Mixed valid/invalid batch | `test_multiple_impulses_correct_count` | Invalid dropped |
| Downward impulse | `test_downward_impulse_negative_angle` | Negative angle |
| Horizontal impulse | `test_horizontal_zero_angle` | 0° |
| Normalize large/negative angles | 4 tests | (-90, 90] bounds |
| Tolerance boundary (bucket) | `test_at_tolerance_boundary_included`, `test_just_outside_tolerance_returns_none` | In/out correctly |
| Tolerance boundary (congruent) | `test_at_boundary_congruent`, `test_just_outside_tolerance_not_congruent` | In/out correctly |

### Coverage summary

86 tests in `tests/test_adjusted_angles.py`:
- `TestSlopeToAngleDeg`: 11 tests
- `TestAngleDegToSlope`: 6 tests
- `TestRoundTrip`: 27 tests (parametrized)
- `TestNormalizeAngle`: 9 tests
- `TestGetAngleFamilies`: 6 tests
- `TestBucketAngleToFamily`: 7 tests
- `TestAreAnglesCongruent`: 6 tests
- `TestComputeImpulseAngles`: 14 tests

---

## Test summary

| Test file | Tests | Status |
|---|---|---|
| `test_adjusted_angles.py` | 86 | ✅ All pass |
| All tests (full suite) | 248 | ✅ All pass |

---

## Smoke-run results (price_mode=raw)

| Dataset | Method | Impulses | ppb (ATR) | Angles | 1x1 (45°) | 1x2 (26.6°) | 1x8 (7.1°) | Unclassified |
|---|---|---|---|---|---|---|---|---|
| 1D | pivot n=5 | 481 | 897.0 | 481 | 13 (2.7%) | 48 (10.0%) | 163 (33.9%) | 142 (29.5%) |
| 1D | zigzag 20% | 138 | 897.0 | 138 | 5 (3.6%) | 18 (13.0%) | 50 (36.2%) | 29 (21.0%) |
| 6H | pivot n=5 | 1,897 | 341.6 | 1,897 | 72 (3.8%) | 182 (9.6%) | 625 (32.9%) | 561 (29.6%) |
| 6H | zigzag 5% | 1,588 | 341.6 | 1,588 | 55 (3.5%) | 169 (10.6%) | 521 (32.8%) | 376 (23.7%) |

6H gap note: `missing_bar_count=1`; angle computation uses `delta_t` (bar-index
delta) — gap-safe.  No impulses skipped at this stage.

---

## Remaining issues

None.

---

## Verdict

**PASS** — Phase 3A (adjusted angles) is complete.  Phase 4 (confluence engine)
may **not** begin yet; the remaining Phase 3 modules (measured moves, JTTL,
square-root levels, time counts, log levels) must be completed first.  The next
task should be the next Phase 3 sub-module.
