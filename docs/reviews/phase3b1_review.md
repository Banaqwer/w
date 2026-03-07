# Phase 3B.1 Review — JTTL + Sqrt Levels

**Date:** 2026-03-07
**Reviewer:** automated
**Verdict:** PASS

---

## Scope reviewed

| File | Purpose |
|------|---------|
| `modules/jttl.py` | Jenkins Theoretical Target Level — sqrt-transform line projection |
| `modules/sqrt_levels.py` | Square-root horizontal price level grid |
| `tests/test_jttl.py` | 58 JTTL tests |
| `tests/test_sqrt_levels.py` | 43 sqrt-level tests |
| `research/run_phase3b1_smoke.py` | End-to-end smoke-run (Phase 2 origins → JTTL + sqrt levels) |
| `PROJECT_STATUS.md` | Phase 3B.1 completion record |
| `ASSUMPTIONS.md` | Assumptions 23–24 |
| `DECISIONS.md` | 2026-03-07 Phase 3B.1 horizon and sqrt-level decisions |

---

## Check 1 — Phase 3 scope only

**Result: PASS**

No Phase 4+ drift detected.  Grep across all five Phase 3B.1 files for
`projection`, `confluence`, `signal`, `backtest`, `TradeSignal`, `ForecastZone`
returned zero functional matches.  All occurrences are in docstring/comment
clauses stating that Phase 4+ logic is **not** present.

The code contains:
- No projection-zone generation (Phase 4)
- No confluence scoring (Phase 4)
- No confirmation / trade-signal logic (Phase 5)
- No backtest / ablation logic (Phase 6)
- No advanced geometric modules (Phase 7)

`modules/jttl.py` imports: `logging`, `math`, `dataclasses`, `typing`,
`pandas`.  No Phase 2+ module imports.

`modules/sqrt_levels.py` imports: `logging`, `math`, `dataclasses`, `typing`.
No external dependencies at all.

`research/run_phase3b1_smoke.py` imports only `modules.jttl` and
`modules.sqrt_levels` — both Phase 3B.1 modules.

---

## Check 2 — JTTL horizon definition explicit for crypto

**Result: PASS**

### Module docstring (lines 37–54)

The module docstring contains a dedicated section:

> **"One Year" horizon mapping for crypto**
>
> The default horizon is **365 calendar days in UTC**.
>
> For a traditional equity market, "one year" might be 252 trading days.
> BTC/USD (and crypto generally) trades 24/7 with no exchange closures, so
> every calendar day is a trading day.  Using 365 calendar days accurately
> captures "one year" of continuous crypto exposure without any trading-day
> adjustment.

### Code-level enforcement

- `_CALENDAR_DAYS_PER_YEAR: int = 365` module constant (line 101)
- `compute_jttl` default parameter: `horizon_days: int = _CALENDAR_DAYS_PER_YEAR`
- Horizon endpoint: `t1 = origin_time + pd.Timedelta(days=active_horizon_days)`
  — uses **calendar days**, not trading bars
- `slope_raw` units: **price per calendar day** (explicitly documented in both
  module docstring and field docstring)
- `basis` field on `JTTLLine`: set to `"calendar_days"` or `"bars"` to make
  the active time system transparent

### Alternate horizon mode

`horizon_bars=N` overrides `horizon_days`.  For 1D data, N bars = N calendar
days (verified by test `test_bars_and_days_equivalent_at_365`).  The `basis`
field is set to `"bars"` to distinguish which mode was active.

### Assumption & decision references

- ASSUMPTIONS.md Assumption 23: "The default 'one year' horizon for the JTTL
  module is 365 calendar days in UTC."
- DECISIONS.md 2026-03-07: "JTTL default horizon = 365 calendar days UTC for
  crypto" with full rationale table.

### Test coverage for horizon

| Test | Verifies |
|------|----------|
| `test_365_calendar_days_default` | t1 = t0 + 365 days, basis = "calendar_days" |
| `test_n_bars_horizon` | t1 = t0 + N days, basis = "bars" |
| `test_bars_and_days_equivalent_at_365` | N=365 bars ≡ 365 calendar days |
| `test_custom_horizon_days` | horizon_days=180 produces correct t1 |
| `test_calendar_days_constant` | _CALENDAR_DAYS_PER_YEAR == 365 |

---

## Check 3 — Sqrt formulas correct and tested

**Result: PASS**

### JTTL theoretical price formula

Formula: `p1 = (sqrt(p0) + k) ** 2`

| origin_price | k | sqrt(p0) | expected p1 | computed p1 | Match |
|---|---|---|---|---|---|
| 47.70 | 2.0 | 6.9065 | 79.3261 | 79.3261 | ✓ |
| 100.00 | 2.0 | 10.0 | 144.0 | 144.0 | ✓ |
| 64.00 | 4.0 | 8.0 | 144.0 | 144.0 | ✓ |
| 100.00 | 0.0 | 10.0 | 100.0 | 100.0 | ✓ |
| 100.00 | -2.0 | 10.0 | 64.0 | 64.0 | ✓ |

### JTTL slope formula

`slope_raw = (p1 - p0) / horizon_days` — verified by
`test_slope_raw_formula` (tolerance 1e-12).

### Sqrt-level up formula

`level = (sqrt(p0) + inc * n) ** 2`

| p0 | inc | n | sqrt(p0)+inc×n | expected | Match |
|---|---|---|---|---|---|
| 100.0 | 1.0 | 1 | 11.0 | 121.0 | ✓ |
| 100.0 | 2.0 | 3 | 16.0 | 256.0 | ✓ |
| 47.70 | 1.0 | 1 | 7.9065 | 62.513 | ✓ |

### Sqrt-level down formula

`level = (sqrt(p0) - inc * n) ** 2` with clamping at val < 0

| p0 | inc | n | sqrt(p0)−inc×n | expected | Clamped? |
|---|---|---|---|---|---|
| 100.0 | 1.0 | 1 | 9.0 | 81.0 | No |
| 4.0 | 2.0 | 1 | 0.0 | 0.0 | No (boundary) |
| 4.0 | 2.0 | 2 | -2.0 | — | Yes (skipped) |

### Test coverage for formulas

| Test class | Count | What it verifies |
|---|---|---|
| `TestTheoreticalPrice` | 10 | Known values, k=0, negative k, zero origin, negative origin raises |
| `TestKnownValues` (sqrt) | 13 | Parametrized formula checks across increments and steps |
| `test_up_formula_parametrized` | 7 | Up levels: inc ∈ {0.25,0.5,0.75,1.0}, n ∈ {1..4} |
| `test_down_formula_parametrized` | 4 | Down levels: inc ∈ {0.25,0.5,1.0}, n ∈ {1,2} |

---

## Check 4 — Deterministic outputs and clear JSON artifacts

**Result: PASS**

### Determinism verification

1. **Code-level:** No `random`, `numpy.random`, or any stochastic imports in
   either module.  All computations are pure `math` stdlib functions.

2. **Test-level:** Dedicated determinism tests in both test files:
   - `TestTheoreticalPrice::test_deterministic` — same inputs → exact same output
   - `TestComputeJttl::test_deterministic` — identical p1, slope_raw, t1
   - `TestDeterminism::test_deterministic_up` — identical level prices
   - `TestDeterminism::test_deterministic_both` — identical full output

3. **Artifact-level:** Smoke script re-run produces byte-identical JSON output
   (verified via diff of two independent runs).

### JSON artifact structure

All artifacts written to `reports/phase3b1/`:

| File | Format | Items | Size |
|---|---|---|---|
| `reference_origins_jttl_sqrt.json` | JSON array | 3 | 32 KB |
| `origins_jttl_sqrt_..._1D_..._pivot.json` | JSON array | 10 | 113 KB |
| `origins_jttl_sqrt_..._1D_..._zigzag.json` | JSON array | 10 | 113 KB |
| `origins_jttl_sqrt_..._6H_..._pivot.json` | JSON array | 10 | 113 KB |
| `origins_jttl_sqrt_..._6H_..._zigzag.json` | JSON array | 10 | 113 KB |
| `phase3b1_smoke_summary.json` | JSON dict | 1 | 1 KB |
| `phase3b1_smoke_summary.txt` | Text | — | 2 KB |

### JSON schema per origin

```json
{
  "label": "ref_100",
  "origin_time": "2020-01-01 00:00:00+00:00",
  "origin_price": 100.0,
  "jttl": {
    "t0": "2020-01-01 00:00:00+00:00",
    "p0": 100.0,
    "t1": "2020-12-31 00:00:00+00:00",
    "p1": 144.0,
    "k": 2.0,
    "horizon_days": 365.0,
    "horizon_bars": null,
    "slope_raw": 0.12054794520547945,
    "intercept_raw": 100.0,
    "basis": "calendar_days"
  },
  "sqrt_levels": [
    {
      "level_price": 81.0,
      "increment_used": 1.0,
      "step": 1,
      "direction": "down",
      "label": "-1×1"
    }
  ]
}
```

### Summary JSON schema

```json
{
  "phase": "3B.1",
  "scope": "jttl + sqrt_levels",
  "k": 2.0,
  "horizon_days": 365,
  "increments": [0.25, 0.5, 0.75, 1.0],
  "steps": 8,
  "max_origins_per_file": 10,
  "runs": [...]
}
```

### Smoke-run reference results

| Origin | p0 | p1 (JTTL) | Formula check | # sqrt levels |
|---|---|---|---|---|
| ref_47_70 | 47.70 | 79.3261 | (√47.70+2)² ✓ | 62 |
| ref_100 | 100.00 | 144.0000 | (√100+2)² ✓ | 64 |
| ref_10000 | 10000.00 | 10404.0000 | (√10000+2)² ✓ | 64 |

ref_47_70 has 62 levels (not 64) because two down-levels are clamped
(sqrt(47.70) ≈ 6.91; at inc=1.0 step=7: val ≈ −0.09 < 0 → clamped).

---

## Test summary

| Test file | Tests | Status |
|---|---|---|
| `test_jttl.py` | 58 | ✅ All pass |
| `test_sqrt_levels.py` | 43 | ✅ All pass |
| Full suite | 349 | ✅ All pass (248 prior + 101 Phase 3B.1) |

---

## Remaining issues

None.

---

## Verdict

**PASS** — Phase 3B.1 (JTTL + sqrt levels) is complete.

Both modules are:
- mathematically correct (formulas verified against manual computation)
- explicitly documented for crypto 24/7 horizon (365 calendar days)
- fully deterministic (no RNG, verified by re-run comparison)
- producing clear JSON artifacts under `reports/phase3b1/`
- scoped to Phase 3 only (no Phase 4+ leakage)
- independently testable (101 tests, all passing)
- assumption- and decision-logged (Assumptions 23–24, DECISIONS.md 2026-03-07)

**Phase 3B.2 (measured moves) may begin next.**
