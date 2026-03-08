# Phase 5 Review — Signal / Confirmation Layer

**Date:** 2026-03-08
**Reviewer:** automated
**Verdict:** PASS

---

## Scope reviewed

| File | Purpose |
|------|---------|
| `signals/signal_types.py` | Phase 5 output schema: EntryRegion, InvalidationRule, SignalCandidate, ConfirmationResult |
| `signals/signal_generation.py` | Convert ConfluenceZone + Projection → SignalCandidate (deterministic, config-driven) |
| `signals/confirmations.py` | Pure confirmation check functions (candle_direction, zone_rejection, strict_multi_candle) |
| `research/run_phase5_smoke.py` | End-to-end Phase 5 smoke script: Phase 4 JSON → Phase 5 JSON |
| `tests/test_signal_types.py` | 37 tests: schema validation, deterministic signal_id, to_dict() |
| `tests/test_signal_generation.py` | 43 tests: bias, threshold, invalidation, gap policy, determinism, provenance |
| `tests/test_confirmations.py` | 39 tests: all checks, edge cases, gap-policy integration, determinism |
| `PROJECT_STATUS.md` | Phase 5 status and record |

---

## Check 1 — Phase 5 scope only (no backtest/PnL/performance)

**Status: ✅ PASS**

- `signals/signal_types.py` defines data structures only. No execution, order management,
  or PnL logic. No imports from any Phase 6+ module.
- `signals/signal_generation.py` converts ConfluenceZones into SignalCandidates. No trade
  execution, position tracking, or performance measurement. Line 171: docstring explicitly
  states "No execution logic, no order management, no PnL accounting."
- `signals/confirmations.py` contains pure check functions that return structured
  ConfirmationResult objects. No side effects, no execution, no PnL.
- `research/run_phase5_smoke.py` line 387: explicitly prints
  `"NOTE: Phase 6 backtest engine NOT started."`.
- No imports from backtest, execution, or performance modules anywhere in reviewed files.

---

## Check 2 — Deterministic signal generation (same inputs → same signals)

**Status: ✅ PASS**

- **No randomness:** No `random`, `shuffle`, `sample`, or `numpy.random` usage in any
  reviewed file. Confirmed by searching all Phase 5 source files.
- **Stable signal_id:** `signal_id = sha1(zone_id|bias|dataset_version)[:16]`
  (`signal_generation.py` lines 296–297). Same formula in `SignalCandidate._make_id()`
  (`signal_types.py` line 244). Test at `test_signal_generation.py::TestDeterminism`
  (lines 403–427) confirms reproducibility and hash correctness.
- **Stable bias:** `_determine_bias()` counts direction_hints deterministically via dict
  accumulation. Same counts → same comparison → same bias. No set iteration or hash ordering.
- **Stable ordering:** Signals preserve zone order (which is sorted by `confluence_score`
  descending from confluence engine). Provenance list is explicitly sorted (line 272–278).
- **Stable confirmations:** `run_all_confirmations()` iterates `signal.confirmations_required`
  in list order, dispatching to named check functions. All checks are pure functions.
- **Verified empirically:** Smoke script run twice produces byte-identical JSON output.
  Confirmed by comparing fresh outputs in two separate runs.

---

## Check 3 — Signals are well-specified (entry region, invalidation, confirmations)

**Status: ✅ PASS**

### Entry region
- Every SignalCandidate has an `EntryRegion` with `price_low` and `price_high`
  derived from `zone.price_window` (lines 256–261). Zones without `price_window` are
  skipped (line 228–230). Optional `time_earliest`/`time_latest` from `zone.time_window`.
- `EntryRegion.__post_init__` validates `price_low <= price_high` and
  `time_earliest <= time_latest` (lines 89–102).

### Invalidation
- Long signals get `close_below_zone` at `zone.price_window[0]` (lines 363–368).
- Short signals get `close_above_zone` at `zone.price_window[1]` (lines 369–373).
- Neutral signals get both bracketing rules (lines 376–386).
- Time invalidation added when `zone.time_window` is set (lines 388–393).
- Buffer parameter propagated to all price-based rules.
- `InvalidationRule.__post_init__` validates condition ∈ {close_below_zone,
  close_above_zone, time_expired} and buffer ≥ 0 (lines 157–164).

### Confirmations
- Base checks always: `["candle_direction", "zone_rejection"]` (line 267).
- Gap-triggered: `"strict_multi_candle"` appended when `missing_bar_count > 0` (lines 268–269).
- All checks tested: 10 tests for candle_direction, 7 for zone_rejection, 8+ for
  strict_multi_candle, 5+ for run_all_confirmations.

### Quality score
- `quality_score = min(1.0, max(0.0, zone.confluence_score))` (line 308).
  Clamped to [0, 1]. Directly inherits confluence_score per Assumption 28.

### Provenance
- `provenance = sorted(projection_ids) + ["module:<name>" for each distinct module]`
  (lines 272–278). Auditable and deterministic.

---

## Check 4 — Gap-aware behavior for 6H when missing_bar_count > 0

**Status: ✅ PASS**

### Signal generation
- `generate_signals()` reads `missing_bar_count` from manifest dict (line 183).
- When > 0: appends `"strict_multi_candle"` to `confirmations_required` (lines 268–269),
  sets `metadata["gap_note"]` and `metadata["missing_bar_count"]` (lines 287–293).
- Test at `test_signal_generation.py::TestGapPolicy` (lines 361–398): 5 tests covering
  gap/no-gap, strict_multi_candle presence, metadata recording.

### Confirmation checks
- `check_candle_direction()`: when `missing_bar_count > 0`, adds `gap_note` to metadata
  (lines 127–131). Does not alter pass/fail logic — the separate `strict_multi_candle`
  check handles the stricter requirement.
- `check_zone_rejection()`: when `missing_bar_count > 0`, adds `gap_note` to metadata
  (lines 212–216). Same principle: informational note, not logic change.
- `check_strict_multi_candle()`: requires N consecutive bars (default 2) all closing in
  bias direction (lines 338–348). This is the substantive gap-aware check.
- Test at `test_confirmations.py::TestGapPolicyIntegration` (lines 429–447): 3 tests
  confirming gap_note presence/absence in candle_direction and zone_rejection.

### Smoke script
- `run_phase5_smoke.py` reads manifest (line 281), logs missing_bar_count (lines 283–288),
  passes it to `generate_signals()` and `run_all_confirmations()`.
- Verified with real dataset: `proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1` has
  `missing_bar_count=1` → all 75 signals include `strict_multi_candle` in
  `confirmations_required`.

---

## Check 5 — Smoke script produces JSON artifacts under reports/phase5/

**Status: ✅ PASS**

- `run_phase5_smoke.py` writes two JSON files per dataset version:
  - `reports/phase5/signals_<version>.json` (line 321, 324–326)
  - `reports/phase5/confirmations_<version>.json` (line 322, 327–329)
- Output directory created if missing (`_ensure_dir()` at line 251).
- Both files present in repository: confirmed by `ls reports/phase5/`.
- JSON structure verified: each signal includes `signal_id`, `bias`, `entry_region`,
  `invalidation`, `confirmations_required`, `quality_score`, `provenance`, `metadata`.
- Re-running the smoke script produces byte-identical output (determinism confirmed).

### Smoke-run results (2026-03-08)

| Stat | Value |
|------|-------|
| Zones loaded | 110 |
| Signals produced | 75 |
| Missing bars | 1 |
| Bias: long | 43 |
| Bias: short | 32 |
| Bias: neutral | 0 |
| candle_direction pass rate | 47/75 (62.7%) |
| zone_rejection pass rate | 1/75 (1.3%) |
| strict_multi_candle pass rate | 43/75 (57.3%) |

Low `zone_rejection` rate (1/75) is expected — confirmation window uses the last 30 bars
of the dataset, while most zones are historical and outside recent price range. Not a bug.

---

## Issue found and fixed

| # | Severity | File | Line | Description | Resolution |
|---|----------|------|------|-------------|------------|
| 1 | Minor | `signals/signal_generation.py` | 320–326 | `_determine_bias` docstring said "strictly > other categories combined" but code does `support_n > resist_n` (simple comparison). The docstring implied an absolute majority rule, but the implementation is a plurality rule where support is compared only against resistance. | Fixed: updated docstring to accurately describe the plurality comparison. |

---

## Test results

```
pytest -q → 725 passed (606 Phase 1–4 + 119 Phase 5), 0 failed
```

Phase 5 tests: 37 (signal_types) + 43 (signal_generation) + 39 (confirmations) = 119 tests.

---

## Verdict

**PASS**

Phase 5 (signal / confirmation layer) is correctly implemented, deterministic,
well-specified, gap-aware, properly scoped to Phase 5 only, and fully tested.

**Phase 6 (backtest engine) may begin next.**

---

## Remaining items (non-blocking)

- `quality_score` inherits `confluence_score` directly — refinement deferred to Phase 6+.
- Confirmation window uses last N bars (smoke-test default) — proper walk-forward windows
  deferred to Phase 6 backtest framework.
- `zone_rejection` pass rate is low (1/75) with recent confirmation window — expected
  for historical zones; not a bug.
- `signal_id` hash is computed redundantly in `_zone_to_signal` and `SignalCandidate._make_id()`
  (same formula in two places) — minor DRY concern, non-blocking.
