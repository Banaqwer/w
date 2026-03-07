# Phase 2 Review — Structural Pivot and Impulse Engine

**Date:** 2026-03-07
**Reviewer:** automated
**Verdict:** PASS

---

## Scope reviewed

| File | Purpose |
|------|---------|
| `modules/origin_selection.py` | Origin detection (pivot + zigzag) |
| `modules/impulse.py` | Impulse detection with gap handling |
| `research/run_phase2_smoke.py` | End-to-end smoke-run script |
| `tests/test_phase2_origin_selection.py` | 37 origin tests |
| `tests/test_phase2_impulse.py` | 29 impulse tests |
| `tests/test_phase2_smoke.py` | 4 smoke-script tests |
| `PROJECT_STATUS.md` | Phase 2 completion record |
| `ASSUMPTIONS.md` | Assumptions 19–20 |
| `DECISIONS.md` | 2026-03-06 gap-handling decision |

---

## Check 1 — Phase 2 scope only

**Result: PASS**

No Phase 3+ drift detected. The code contains:
- No projection logic (Phase 3)
- No confluence scoring (Phase 4)
- No confirmation / trade-signal logic (Phase 5)
- No backtest / ablation logic (Phase 6)
- No advanced geometric modules (Phase 7)

All imports are restricted to Phase 1 data layer (`data.loader`) and Phase 2 modules.

---

## Check 2 — Origin and Impulse schemas match Phase 0 interfaces

**Result: PASS**

### Impulse dataclass vs CLAUDE.md spec

| CLAUDE.md field | Impulse field | Status |
|---|---|---|
| `origin_time` | `origin_time` | ✅ |
| `origin_price` | `origin_price` | ✅ |
| `extreme_time` | `extreme_time` | ✅ |
| `extreme_price` | `extreme_price` | ✅ |
| `delta_t` | `delta_t` | ✅ |
| `delta_p` | `delta_p` | ✅ |
| `slope_raw` | `slope_raw` | ✅ |
| `slope_log` | `slope_log` | ✅ |
| `quality_score` | `quality_score` | ✅ |
| `detector_name` | `detector_name` | ✅ |

Additional fields beyond spec (acceptable extensions):
- `impulse_id` — unique key for downstream joins
- `direction` — "up"/"down"
- `origin_bar_index`, `extreme_bar_index` — coordinate system references

The Origin dataclass is not specified in CLAUDE.md Phase 0 interfaces (only Impulse,
Projection, ForecastZone, and TradeSignal are). Origin is a Phase 2 internal type that
feeds into the Impulse interface. Its fields are reasonable and well-documented.

---

## Check 3 — Determinism

**Result: PASS**

Two independent runs of `run_phase2_smoke.py` with the same dataset produced
byte-identical CSV outputs. The only difference in the TXT summary was the
output directory path. The JSON summary was also identical in content.

---

## Check 4 — 6H gap handling

**Result: PASS**

- `run_phase2_smoke.py` reads `missing_bar_count` from the manifest (line 102)
- When `missing_bar_count > 0`, `skip_on_gap=True` is automatically set (line 206)
- `detect_impulses` computes gap flags via `_compute_gap_flags` (timestamp diff > 1.5× median)
- Origins whose forward window crosses a detected gap are silently skipped
- 6H smoke run: 26 pivot origins and 16 zigzag origins correctly skipped
- 1D dataset: `missing_bar_count=0` → `skip_on_gap=False` → no skipping
- Warning logged when `missing_bar_count > 0` but `skip_on_gap=False` (line 111–117)

---

## Check 5 — Smoke script produces JSON artifacts under `reports/phase2/`

**Result: PASS (after fix)**

**Issue found:** The original smoke script produced only CSV files and a TXT summary
but no JSON artifact.

**Fix applied:** Added `json.dump(results, ...)` to write
`reports/phase2/phase2_smoke_summary.json` — a machine-readable array of run results.
Four new tests added in `tests/test_phase2_smoke.py` to verify the JSON is produced,
valid, and contains required keys.

---

## Test summary

| Test file | Tests | Status |
|---|---|---|
| `test_phase2_origin_selection.py` | 37 | ✅ All pass |
| `test_phase2_impulse.py` | 29 | ✅ All pass |
| `test_phase2_smoke.py` | 4 | ✅ All pass (new) |
| All tests (full suite) | 162 | ✅ All pass |

---

## Smoke-run results

| Dataset | Method | Rows | Origins | Impulses | skip_on_gap | Skipped |
|---|---|---|---|---|---|---|
| 1D | pivot n=5 | 3,883 | 481 | 481 | False | 0 |
| 1D | zigzag 20% | 3,883 | 138 | 138 | False | 0 |
| 6H | pivot n=5 | 15,525 | 1,923 | 1,897 | True | 26 |
| 6H | zigzag 5% | 15,525 | 1,604 | 1,588 | True | 16 |

---

## Remaining issues

None.

---

## Verdict

**PASS** — Phase 2 is complete. Phase 3 (MVP projection stack) may begin.
