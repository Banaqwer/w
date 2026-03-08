# Phase 4 Review — Angle-Family Generator Addition

**Date:** 2026-03-08
**Reviewer:** automated
**Verdict:** PASS

---

## Scope reviewed

| File | Purpose |
|------|---------|
| `signals/generators_angle_families.py` | Angle-family price projection generator (9 canonical Jenkins fan lines) |
| `signals/confluence.py` | Confluence engine (clustering + scoring) |
| `research/run_phase4_smoke.py` | End-to-end Phase 4 smoke-run script |
| `tests/test_generator_angle_families.py` | 27 angle-family generator tests |
| `tests/test_confluence_engine.py` | 23 confluence engine tests |
| `PROJECT_STATUS.md` | Phase 4 status and record |

---

## Check 1 — Phase 4 scope only

**Status: ✅ PASS**

- `signals/generators_angle_families.py` outputs only `Projection` objects (lines 207–218).
  No trade signals, entries, exits, or backtest logic present.
- `signals/confluence.py` outputs only `ConfluenceZone` objects (lines 196–204).
  No confirmation, execution, or backtest logic.
- `research/run_phase4_smoke.py` runs generators and confluence only.
  Line 495 explicitly states: `"NOTE: Phase 5 (confirmation, signals, execution, backtest) NOT started."`
- No imports from any Phase 5+ modules anywhere in the reviewed files.

---

## Check 2 — Determinism + reproducibility

**Status: ✅ PASS**

- **No randomness:** No `random`, `shuffle`, `sample`, or `numpy.random` usage in any reviewed file.
- **Stable ordering:** `get_angle_families()` returns families in fixed descending-angle order
  (`modules/adjusted_angles.py` lines 76–86). The generator iterates families, horizons, and
  sign directions deterministically (`generators_angle_families.py` lines 156–165).
- **Stable clustering:** Union-find in `confluence.py` (lines 118–135) produces identical
  component assignments for identical input order. Zones are sorted by `confluence_score`
  descending (line 151), which is deterministic.
- **Tests confirm:** `tests/test_generator_angle_families.py::TestDeterminism` (lines 290–306)
  and `tests/test_confluence_engine.py::TestDeterminism` (lines 259–283) explicitly verify
  same input → same output.

---

## Check 3 — Angle-family logic consistent with Phase 3A

**Status: ✅ PASS**

### Same 9 canonical families
- Generator imports `get_angle_families()` from `modules/adjusted_angles.py` (line 61).
- `get_angle_families()` returns all 9 families: 8×1, 4×1, 3×1, 2×1, 1×1, 1×2, 1×3, 1×4, 1×8
  (defined in `_ANGLE_FAMILIES` at `modules/adjusted_angles.py` lines 76–86).
- Generator iterates all 9 on line 156: `for fam in families:`.

### Same normalization and bucketing
- Generator only processes impulses where `angle_family is not None` (line 131–133),
  meaning `compute_impulse_angles()` → `bucket_angle_to_family()` has already applied
  `normalize_angle()` to the (-90, 90] interval and matched within tolerance.
- No independent normalization or re-bucketing in the generator — correct delegation.

### No incorrect scale_basis recomputation
- `scale_basis` is a function parameter (line 74), not computed internally.
- `angle_deg_to_slope(fam_angle * effective_sign, scale_basis)` at line 172 passes
  the external `scale_basis` — no recomputation inside loops.
- In `research/run_phase4_smoke.py`, `get_angle_scale_basis(df)` is called once per
  dataset (line 358), outside all generator loops. The result is passed to
  `_run_angle_families_projections()` (line 379–381) which forwards it unchanged.

---

## Check 4 — Projection semantics

**Status: ✅ PASS**

### Price-only projections
- `projected_time = None` (line 211) — correct for price-only.
- `time_band = (None, None)` (line 186) — correct null handling.

### Price bands
- `price_band = (target * (1 - band_pct), target * (1 + band_pct))` at lines 182–185.
  Default `band_pct = 0.01` (±1%). Correct symmetric band.

### Horizon logic
- Horizons validated as positive integers (lines 118–120).
- Default `[90]` bars (line 68).
- Horizon recorded in metadata: `metadata["horizon_bars"] = horizon` (line 200).
- Target price formula: `extreme_price + slope * horizon` (line 178). Correct.

### Direction hint
- Above extreme → `"resistance"` (line 190)
- Below extreme → `"support"` (line 192)
- Equal → `"ambiguous"` (line 194)
- All values in `_VALID_DIRECTION_HINTS` set (`signals/projections.py` line 56).

---

## Check 5 — Confluence impact

**Status: ✅ PASS**

### `_MAX_MODULE_TYPES` change 4→5
- `signals/confluence.py` line 79: `_MAX_MODULE_TYPES = 5`.
- Comment confirms: `# MVP: measured_moves, jttl, sqrt_levels, time_counts, angle_families`.
- This correctly accounts for all 5 MVP generators.

### Diversity scoring updated correctly
- `diversity_score = distinct_modules / _MAX_MODULE_TYPES` (line 218).
  With 5 as denominator, a zone with all 5 modules scores `diversity = 1.0`. Correct.
- Score formula: `n_score × diversity_score × avg_raw_score` (line 223). Unchanged.

### No regressions in overlap/clustering logic
- `_are_connected()` (line 230): price OR time overlap. Unchanged.
- `_price_overlap()` (lines 235–246): both price bands non-None and intersecting. Unchanged.
- `_time_overlap()` (lines 249–257): both time bands fully-bounded and intersecting. Unchanged.
- Price-only + time-only never merged (no shared dimension). Confirmed by test at line 177–182.
- Angle-family projections are price-only (`time_band=(None, None)`), so they merge only
  via price overlap with other price-bearing projections. No new bridging paths introduced.

---

## Issue found and fixed

| # | Severity | File | Line | Description | Resolution |
|---|----------|------|------|-------------|------------|
| 1 | Minor | `research/run_phase4_smoke.py` | 68 | `Any` missing from `typing` import; used in type annotations on lines 275 and 354. No runtime impact (`from __future__ import annotations` defers evaluation) but incorrect for static analysis. | Fixed: added `Any` to import. |

---

## Test results

```
pytest -q → 606 passed (457 Phase 1–3 + 149 Phase 4), 0 failed
```

All 27 angle-family generator tests and 23 confluence engine tests pass.

---

## Verdict

**PASS**

Phase 4 change set (angle-family generator addition) is correct, consistent with Phase 3A,
deterministic, properly scoped, and fully tested.

**Phase 5 may begin.**

---

## Remaining items (non-blocking)

- Recency weight in confluence scoring is neutral (1.0) — deferred to post-MVP.
- `min_cluster_size` defaults to 1 (all projections form zones) — tuning deferred.
- Confluence O(n²) clustering acceptable at MVP scale; interval tree upgrade if >10k projections.
