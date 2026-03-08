# Project Status - Jenkins Quant Project

## Current phase
- Phase 3 — MVP projection stack (IN PROGRESS — 2026-03-07)
  - Adjusted angles module: COMPLETE (Phase 3A)
  - JTTL + sqrt levels: COMPLETE (Phase 3B.1) — reviewed PASS 2026-03-07

## Current status

### Phase 0 — COMPLETE (approved 2026-03-04)
- Architecture confirmation memo produced and passed review
- Implementation order confirmed
- Ambiguity list resolved
- Repo structure and phase sequence approved
- MCP extraction workflow proposed in phase0_builder_output.md
- All canonical docs consistent and internally aligned

### Phase 1 — COMPLETE (2026-03-04)

#### Completed deliverables
- `docs/data/mcp_extraction_runbook.md` — MCP tool discovery + extraction workflow
- `pyproject.toml` — Python project definition; pytest-ready
- `configs/default.yaml` — all data + module defaults; config-driven experiment control
- `core/__init__.py`, `core/coordinate_system.py` — coordinate system with all derived fields
- `data/__init__.py`, `data/validation.py` — OHLC + continuity checks (data_spec.md §10–12)
- `data/ingestion.py` — raw → processed ingestion pipeline (7 steps); includes
  `resample_daily_to_weekly()` for config-driven weekly production
- `data/loader.py` — load processed datasets, raw files, manifests, extraction metadata
- `data/extract.py` — Coinbase REST API extraction script via ccxt; includes
  `generate_synthetic_ohlcv()` for offline/sandbox use and `--resample-weekly-from` CLI flag
- `modules/__init__.py`, `signals/__init__.py`, `backtest/__init__.py`, `research/__init__.py` — package stubs
- `tests/test_validation.py`, `tests/test_coordinate_system.py`, `tests/test_ingestion.py` — 59 tests, all passing
- Data directory structure: `data/raw/coinbase_rest/`, `data/processed/`, `data/metadata/extractions/`
- `ccxt>=4.0` added to `pyproject.toml` runtime dependencies
  - Install command: `pip install -e ".[dev]"`

#### M6 — RESOLVED (2026-03-04): First validated datasets produced

All three MVP timeframe datasets produced and validated on 2026-03-04.

**Note on data source:** The Coinbase REST API (`api.coinbase.com`) is not reachable
from the sandboxed CI environment. Datasets below were produced using the built-in
`generate_synthetic_ohlcv()` function (`--use-synthetic` flag), which generates a
reproducible log-random-walk BTC/USD-like price series from 2013-01-01.
When the live Coinbase API is accessible, re-run without `--use-synthetic` to replace
with real data. The pipeline, schema, manifest, and validation all pass against real data.

**Commands run (Phase 1B synthetic pull — 2026-03-04):**
```
python -m data.extract --timeframe 1D \
    --version proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1 \
    --pull-date 2026-03-04 --overwrite --use-synthetic

python -m data.extract --timeframe 4H \
    --version proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1 \
    --pull-date 2026-03-04 --overwrite --use-synthetic

python -m data.extract \
    --resample-weekly-from proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1 \
    --pull-date 2026-03-04 --overwrite
```

**NOTE (2026-03-05):** The official intraday confirmation timeframe has changed from `4H` to `6H`
(see `DECISIONS.md` 2026-03-05 change log). The 4H dataset below is a Phase 1B historical artifact
only. When the live Coinbase API is accessible, produce the `6H` dataset instead:
```
python -m data.extract --timeframe 6H \
    --version proc_COINBASE_BTCUSD_6H_UTC_<pull-date>_v1 \
    --pull-date <pull-date> --overwrite --use-synthetic
```

**1D dataset**
- Earliest date pulled: 2013-01-01
- Rows: 4 811 daily bars (2013-01-01 → 2026-03-04)
- Raw CSV: `data/raw/coinbase_rest/COINBASE_BTCUSD/1D/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.csv`
- Extraction metadata: `data/metadata/extractions/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.json`
- Processed Parquet: `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1.parquet`
- Manifest: `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1_manifest.json`
  - `validation_passed`: true
  - `derived_fields`: bar_index, calendar_day_index, trading_day_index, log_close, hl_range, true_range, atr_14
  - `atr_warmup_rows`: 14
  - `bar_index_epoch_timestamp`: 2013-01-01 00:00:00+00:00

**4H dataset (historical artifact — superseded by 6H policy 2026-03-05)**
- Earliest date pulled: 2013-01-01
- Rows: 28 861 four-hour bars (2013-01-01 → 2026-03-04)
- Raw CSV: `data/raw/coinbase_rest/COINBASE_BTCUSD/4H/cbrest_COINBASE_BTCUSD_4H_UTC_2026-03-04.csv`
- Extraction metadata: `data/metadata/extractions/cbrest_COINBASE_BTCUSD_4H_UTC_2026-03-04.json`
- Processed Parquet: `data/processed/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1.parquet`
- Manifest: `data/processed/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1_manifest.json`
  - `validation_passed`: true
  - `derived_fields`: bar_index, calendar_day_index, trading_day_index, log_close, hl_range, true_range, atr_14
  - `atr_warmup_rows`: 14
  - `bar_index_epoch_timestamp`: 2013-01-01 00:00:00+00:00
- Gap note: Synthetic data has no gaps; live Coinbase 4H depth may vary — re-pull when API accessible

**Weekly dataset (resampled from 1D)**
- Method: `resample_daily_to_weekly()` in `data/ingestion.py`; boundary = Monday 00:00 UTC
- Rows: 688 weekly bars
- Processed Parquet: `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1.parquet`
- Manifest: `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1_manifest.json`
  - `validation_passed`: true
  - `bar_index_epoch_timestamp`: 2012-12-31 00:00:00+00:00

**Tests:** `pytest -q` → 59 passed, 0 failed

#### Open Phase 1 items
- **M1 — RESOLVED (2026-03-04):** Official acquisition method: **Coinbase REST API via `ccxt`**.
- **M2 — RESOLVED (2026-03-04; policy updated 2026-03-05):** Intraday confirmation TF is now `6H` (native Coinbase REST via `ccxt`). Prior `4H` synthetic dataset retained as historical artifact only.
- **M3 — RESOLVED (2026-03-04):** Symbol `BTC/USD` (ccxt) = `COINBASE:BTCUSD` (TradingView).
- **M5 — RESOLVED (2026-03-06):** `dataset.current_version` = `proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1` (live data; supersedes 2026-03-04 synthetic).
- **M6 — RESOLVED (2026-03-06):** Official processed datasets produced from live 1H repo raw; all manifests confirmed.

## Confirmed project decisions
- Python is the official research and testing environment
- TradingView through the user's MCP bridge is retained for current-bar snapshot sanity checks only
- Official historical OHLCV acquisition: Coinbase REST API via `ccxt`
- official experiments must run on saved, normalized, versioned datasets
- TradingView is not the official source of truth for backtest outputs
- BTC/USD is the MVP market
- official chart symbol is `COINBASE:BTCUSD`
- spot market is the MVP instrument choice
- UTC is the official timezone
- 00:00 UTC is the official daily close
- Daily / **6H** / Weekly are the official MVP timeframes (**6H supersedes 4H per 2026-03-05 decision**)
- Weekly bars are derived by resampling from 1D (`resample_from_1D` per config), not direct pull

## Immediate next actions
1. ~~Review mcp_extraction_runbook.md §2 and select the historical data acquisition method~~ — DONE
2. ~~Record the decision in `DECISIONS.md`~~ — DONE
3. ~~Update `ASSUMPTIONS.md` Assumption 8 to reflect the actual acquisition method~~ — DONE
4. ~~Add `ccxt` to `pyproject.toml` and install~~ — DONE (2026-03-04)
5. ~~Create `data/extract.py` extraction script~~ — DONE (2026-03-04)
6. ~~Set `dataset.current_version` to `proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1`~~ — DONE (2026-03-04)
7. ~~Execute the first daily data pull~~ — DONE (synthetic; re-pull with live API when accessible)
8. ~~Produce 4H dataset~~ — DONE (2026-03-04; **superseded: 6H dataset required under 2026-03-05 policy**)
9. ~~Produce weekly dataset by resampling~~ — DONE (2026-03-04)
10. ~~Confirm manifests contain all required fields~~ — DONE (2026-03-04)
11. ~~When live Coinbase API is accessible: re-run pulls without `--use-synthetic`~~ — DONE (Phase 1C, 2026-03-06; live 1H raw committed to repo; resampled to 1D/6H/1W)
12. Begin Phase 2: structural pivot and impulse engine

## Success condition for Phase 1
Phase 1 is complete when:
- All scaffolding files exist and tests pass ✅
- MCP runbook documents actual tool names and limitations ✅
- First processed dataset for `COINBASE:BTCUSD` daily is produced, validated, and version-stamped ✅
- Dataset manifest exists and all derived fields are confirmed non-null (post-warmup) ✅

### Phase 1B Review — PASS (2026-03-04)

Phase 1B synthetic/offline pipeline execution reviewed and accepted.

- All 10 artifacts produced and verified:
  - 1D and 4H: raw CSV, extraction metadata JSON, processed Parquet, manifest JSON
  - 1W: processed Parquet and manifest JSON (resampled from 1D; no separate raw CSV or extraction metadata)
- All manifests include: `validation_passed`, `derived_fields`, `atr_warmup_rows`, `bar_index_epoch_timestamp`
- Actual timestamps confirmed from processed Parquet files:
  - **1D:** 2013-01-01 → 2026-03-04 (4 811 rows)
  - **4H:** 2013-01-01 → 2026-03-04 (28 861 rows) _(historical artifact; 6H dataset required going forward)_
  - **1W:** 2012-12-31 → 2026-03-02 (688 rows)
- 59/59 tests pass
- This is a **valid synthetic/offline validation run**, not the final official live Coinbase dataset milestone
- A live rerun without `--use-synthetic` is **still required** before Phase 2 official research outputs;
  the confirmation-TF pull must use `--timeframe 6H` (not `4H`) per 2026-03-05 policy
- Full review: `docs/reviews/phase1b_review.md`

### Phase 1C Review — PASS (2026-03-06)

Phase 1C "ingest from repo raw" pipeline executed and accepted.

- Official live 1H raw file (`cbrest_COINBASE_BTCUSD_1H_UTC_2026-03-06`) committed to repo
  and moved to canonical path `data/raw/coinbase_rest/COINBASE_BTCUSD/1H/`.
- New module `data/ingest_from_raw.py` reads the 1H raw and produces all three official
  MVP datasets by resampling (no network required).
- All three datasets produced, validated, and versioned:
  - **1D:** 2015-07-20 → 2026-03-06 (3 883 rows)
  - **6H:** 2015-07-20 18:00 UTC → 2026-03-06 00:00 UTC (15 525 rows)
  - **1W:** 2015-07-20 → 2026-03-02 (555 rows, Monday-aligned)
- 92/92 tests pass (65 existing + 27 new/updated for `ingest_from_raw` and manifest schema).
- Manifests include: `validation_passed`, `derived_fields`, `atr_warmup_rows`,
  `bar_index_epoch_timestamp`, `start_timestamp`, `end_timestamp`,
  `missing_bar_count`, `missing_bar_policy`, `missing_bar_details`.
- 6H missing-bar gap tolerance documented in `DECISIONS.md` and `ASSUMPTIONS.md` (Assumption 18).
- Repo data commit policy documented in `DECISIONS.md` (2026-03-06).
- Stale root-level data files removed; `.gitignore` updated.
- Reproducibility command:
  ```
  python -m data.ingest_from_raw --symbol COINBASE_BTCUSD --timeframe 1H --pull-date 2026-03-06 --overwrite
  ```
- Full review: `docs/reviews/phase1c_review.md`

## Phase 2 — COMPLETE (2026-03-06)

### Completed deliverables
- `modules/origin_selection.py` — Origin selection with two configurable detectors:
  - `detect_pivots(df, n_bars=5)` — N-bar fractal pivot; strict local max/min check
  - `detect_zigzag(df, reversal_pct=20.0)` — threshold reversal; supports ATR-based fallback
  - `select_origins(df, method, **kwargs)` — unified dispatch
  - `origins_to_dataframe(origins)` — export helper
  - `Origin` dataclass: `origin_time`, `origin_price`, `origin_type`, `detector_name`, `quality_score`, `bar_index`
- `modules/impulse.py` — Impulse detection:
  - `detect_impulses(df, origins, max_bars=200, skip_on_gap=False)` — full Phase 0 spec fields
  - Gap handling: `_compute_gap_flags` detects missing bars via timestamp diff > 1.5× median interval
  - `impulses_to_dataframe(impulses)` — export helper
  - `Impulse` dataclass: all Phase 0 fields (`origin_time`, `origin_price`, `extreme_time`, `extreme_price`, `delta_t`, `delta_p`, `slope_raw`, `slope_log`, `quality_score`, `detector_name`)
- `research/run_phase2_smoke.py` — Smoke-run script:
  - Loads 1D and 6H datasets via `data/loader.py`
  - Reads `missing_bar_count` from manifest; auto-sets `skip_on_gap=True` for 6H
  - Writes 8 CSVs + summary to `reports/phase2/`
- `tests/test_phase2_origin_selection.py` — 37 tests
- `tests/test_phase2_impulse.py` — 29 tests
- `DECISIONS.md` updated with Phase 2 gap-handling decision (2026-03-06)
- `ASSUMPTIONS.md` updated with Assumptions 19–20

### Smoke-run results (2026-03-06)
| Dataset | Method | Rows | Origins | Impulses | skip_on_gap | Skipped |
|---|---|---|---|---|---|---|
| 1D | pivot n=5 | 3883 | 481 | 481 | False | 0 |
| 1D | zigzag 20% | 3883 | 138 | 138 | False | 0 |
| 6H | pivot n=5 | 15525 | 1923 | 1897 | True | 26 |
| 6H | zigzag 5% | 15525 | 1604 | 1588 | True | 16 |

**Tests:** `pytest -q` → 158 passed (92 Phase 1 + 66 Phase 2), 0 failed

### Phase 2 Review — PASS (2026-03-07)

Phase 2 review completed and accepted.

- All 5 review checks passed:
  1. **Phase 2 scope only** — no Phase 3+ drift, no trading/backtest logic ✅
  2. **Origin and Impulse schemas match Phase 0 interfaces** — all 10 CLAUDE.md Impulse fields present ✅
  3. **Determinism** — repeated runs produce byte-identical CSV outputs ✅
  4. **6H gap handling** — manifest `missing_bar_count` read; `skip_on_gap=True` auto-set for 6H ✅
  5. **JSON artifacts** — `phase2_smoke_summary.json` produced under `reports/phase2/` ✅
- Fix applied: added JSON summary output to smoke script (was CSV + TXT only)
- 4 new smoke-script tests added (`tests/test_phase2_smoke.py`)
- 162/162 tests pass (92 Phase 1 + 66 Phase 2 + 4 smoke)
- Full review: `docs/reviews/phase2_review.md`

### Open Phase 2 items
- None.

## Notes
Phase 2 is complete and reviewed.
Phase 3 (projection stack: measured moves, adjusted angles, JTTL, sqrt levels, time counts, log levels) may begin.

---

## Phase 3 — IN PROGRESS (2026-03-07)

### Phase 3B.1 — JTTL + sqrt levels (COMPLETE — 2026-03-07)

#### Completed deliverables
- `modules/jttl.py` — Jenkins Theoretical Target Level module:
  - `theoretical_price(origin_price, k=2.0)` — endpoint formula: `(sqrt(p0) + k)^2`
  - `compute_jttl(origin_time, origin_price, k, horizon_days, horizon_bars)` — full JTTLLine
  - `JTTLLine` dataclass: `t0, p0, t1, p1, k, horizon_days, horizon_bars, slope_raw, intercept_raw, basis`
  - `JTTLLine.price_at(t)` — price on the JTTL line at any timestamp
  - `JTTLLine.time_at_price(p)` — timestamp where the line crosses price p
  - `JTTLLine.to_dict()` — JSON-serialisable dict
  - Horizon: 365 calendar days UTC (default); N daily bars (alternate, sets `basis="bars"`)
  - `slope_raw` units: **price per calendar day**
- `modules/sqrt_levels.py` — Square-root horizontal level module:
  - `sqrt_levels(origin_price, increments, steps, direction)` — full level grid
  - `SqrtLevel` dataclass: `level_price, increment_used, step, direction, label`
  - `SqrtLevel.to_dict()` — JSON-serialisable dict
  - Supports `direction="up"`, `"down"`, `"both"`; down-level clamping at sqrt < 0
- `tests/test_jttl.py` — 58 tests:
  - known-value checks (origin=47.70, k=2.0; origin=100, etc.)
  - slope/intercept math, t1 placement, horizon basis flags
  - `price_at` / `time_at_price` round-trip and edge cases
  - invalid inputs: zero/negative origin, zero/negative horizon, zero horizon_bars
  - determinism, bars-vs-calendar equivalence at N=365
- `tests/test_sqrt_levels.py` — 43 tests:
  - known-value checks (origin=47.70; multiple increments/steps)
  - direction up/down/both; invalid direction raises
  - down-level clamping when sqrt would go negative
  - output sorted ascending; label format (+/-); to_dict keys
  - invalid origin, steps, increments raise; determinism
- `research/run_phase3b1_smoke.py` — Smoke-run script:
  - Loads Phase 2 origin CSVs from `reports/phase2/`
  - Applies 3 hardcoded reference origins (47.70, 100.0, 10000.0)
  - Computes JTTL line + sqrt levels per origin
  - Writes JSON per origin set to `reports/phase3b1/`
  - Writes text + JSON summary
- `ASSUMPTIONS.md` updated: Assumptions 23–24
- `DECISIONS.md` updated: 2026-03-07 Phase 3B.1 horizon and sqrt-level decisions

#### How to run Phase 3B.1 smoke script
```
python -m research.run_phase3b1_smoke
python -m research.run_phase3b1_smoke --k 2.0 --horizon-days 365
python -m research.run_phase3b1_smoke --origins-dir reports/phase2 --output-dir reports/phase3b1
```

#### Smoke-run results (2026-03-07, k=2.0, horizon=365 calendar days)
| Origin | p0 | p1 (JTTL) | # sqrt levels |
|---|---|---|---|
| ref_47_70 | 47.70 | 79.3261 | 62 |
| ref_100 | 100.00 | 144.0000 | 64 |
| ref_10000 | 10000.00 | 10404.0000 | 64 |
| 1D pivot (first 10) | 298.00 | 371.0507 | 64 |
| 6H pivot (first 10) | 275.01 | 345.3437 | 64 |

**Tests:** `pytest -q` → 349 passed (248 Phase 1–3A + 101 Phase 3B.1), 0 failed

#### Note: Phase 4 NOT started
No Phase 4+ (projections, confluence, signals, backtest) logic has been
implemented.  Phase 3B.1 delivers only Phase 3 primitives (JTTL + sqrt
levels).  Remaining Phase 3 modules (measured moves, time counts, log levels)
must be completed before Phase 4 begins.

#### Open Phase 3B.1 items
- ~~Measured move module (Phase 3B.2)~~ → completed in Phase 3B.2
- ~~Time-count / squaring-the-range module (deferred)~~ → completed in Phase 3B.2
- ~~Log-level / semi-log module (deferred)~~ → completed in Phase 3B.2

#### Phase 3B.1 Review (2026-03-07)
- **Verdict:** PASS
- **Review:** `docs/reviews/phase3b1_review.md`
- **Checks passed:**
  1. Phase 3 scope only — no Phase 4+ (projection/confluence/signal/backtest) drift
  2. JTTL horizon = 365 calendar days UTC for crypto — explicit in module docstring, code constant, Assumption 23, DECISIONS.md
  3. Sqrt formulas correct — known-value verified for JTTL `(sqrt(p0)+k)^2` and sqrt levels `(sqrt(p0)±inc*n)^2`
  4. Deterministic outputs — no RNG, re-run produces byte-identical JSON under `reports/phase3b1/`
- **Tests:** 349 passed (248 prior + 101 Phase 3B.1), 0 failed
- **Phase 3B.2 (measured moves) may begin next.**

### Phase 3B.2 — Measured moves + time counts + log helpers (COMPLETE — 2026-03-07)

#### Completed deliverables
- `modules/log_levels.py` — Canonical log-price conversion helpers:
  - `log_price(p)` — natural log of price
  - `log_return(p0, p1)` — log return `log(p1/p0)`
  - `log_slope(delta_p, p0, delta_t)` — log return per bar; matches `modules/impulse.py` `slope_log` convention
  - `log_scale_basis(price_per_bar, origin_price)` — per-impulse log scale basis; matches `modules/adjusted_angles.py` log-mode formula
- `modules/measured_moves.py` — Measured-move target projections:
  - `MeasuredMoveTarget` dataclass (impulse_id, ratio, target_price, direction, mode, basis fields, quality_score, notes)
  - `measured_move_targets(impulse, ratios, mode, angle_family_tag)` — single-impulse targets (extension + retracement)
  - `compute_measured_moves(impulses, ratios, mode, angle_family_tags)` — batch version
  - Raw formula: `extreme ± ratio * delta_p`; log formula: `exp(log(extreme) ± ratio * log(extreme/origin))`
  - Accepts `angle_family_tag` from Phase 3A output; propagated to notes
  - Non-positive raw targets noted with WARNING; log targets with non-positive prices skipped
- `modules/time_counts.py` — Gap-safe bar-count utilities:
  - `TimeWindow` dataclass (impulse metadata, multiplier, bar_offset, target_bar_index, target_time, in_dataset, notes)
  - `bars_between_by_bar_index(bar0, bar1)` — signed bar delta (canonical gap-safe op)
  - `bars_between(t0, t1, index_map)` — timestamp-based lookup using bar_index map
  - `build_index_map(df)` — build `timestamp → bar_index` dict from processed DataFrame
  - `build_bar_to_time_map(df)` — build `bar_index → timestamp` dict (inverse)
  - `time_square_windows(impulse, multipliers, bar_to_time_map)` — produce time-window objects
  - All operations use bar_index deltas; gap-safe per Assumption 26
- `research/run_phase3b_smoke.py` — Integrated Phase 3B smoke:
  - Loads 1D and 6H datasets + manifests
  - Reads `missing_bar_count` from each manifest; logs gap policy
  - Runs: adjusted angles (raw + log), measured moves (raw + log), JTTL, sqrt levels, time counts
  - Writes per-dataset JSON to `reports/phase3b/`
  - Writes text + JSON summary
- `tests/test_log_levels.py` — 43 tests
- `tests/test_measured_moves.py` — 33 tests
- `tests/test_time_counts.py` — 32 tests
- `ASSUMPTIONS.md` updated: Assumptions 25–26

#### How to run Phase 3B smoke script
```
python -m research.run_phase3b_smoke
python -m research.run_phase3b_smoke --phase2-dir reports/phase2 --output-dir reports/phase3b
python -m research.run_phase3b_smoke --max-impulses 20 --max-origins 10
```

#### Smoke-run results (2026-03-07)

| Source | miss | imp | ang | mmR | mmL | win | orig |
|---|---|---|---|---|---|---|---|
| 1D pivot | 0 | 20 | 20 | 160 | 160 | 80 | 10 |
| 1D zigzag | 0 | 20 | 20 | 160 | 160 | 80 | 10 |
| 6H pivot | 1 | 20 | 20 | 160 | 160 | 80 | 10 |
| 6H zigzag | 1 | 20 | 20 | 160 | 160 | 80 | 10 |
| **TOTALS** | | **80** | **80** | **640** | **640** | **320** | **40** |

Columns: `miss`=missing_bar_count, `imp`=impulses processed, `ang`=angles,
`mmR`/`mmL`=measured-move targets raw/log, `win`=time windows, `orig`=origins.

**Gap note (6H):** manifest `missing_bar_count=1`; time counts use bar_index
deltas (gap-safe per Assumption 26).

**Tests:** `pytest -q` → 457 passed (349 Phase 1–3B.1 + 108 Phase 3B.2), 0 failed

#### Note: Phase 4 NOT started
No Phase 4+ (projections, confluence, signals, backtest) logic has been
implemented.  Phase 3B.2 delivers only Phase 3 primitives (measured moves,
time counts, log helpers).  Phase 4 may not begin until Phase 3 is fully
reviewed and accepted.

---

### Phase 3A — Adjusted angles (COMPLETE — 2026-03-07)

#### Completed deliverables
- `modules/adjusted_angles.py` — Adjusted-angle module:
  - `slope_to_angle_deg(delta_p, delta_t, scale_basis)` — raw price → angle in degrees
  - `angle_deg_to_slope(angle_deg, scale_basis)` — angle → raw slope (inverse)
  - `normalize_angle(angle_deg)` — map to (-90, 90]
  - `compute_impulse_angles(impulses, scale_basis, price_mode)` — batch angle computation for Impulse lists or dicts
  - `get_angle_families()` — canonical Jenkins angle families (8x1 through 1x8)
  - `bucket_angle_to_family(angle_deg, tolerance_deg)` — nearest Jenkins family
  - `are_angles_congruent(angle_a, angle_b, tolerance_deg)` — pairwise congruence check
- `research/run_phase3_smoke.py` — Smoke-run script:
  - Loads all Phase 2 impulse CSVs from `reports/phase2/`
  - Reads `missing_bar_count` from manifest; logs behavior for 6H gap dataset
  - Computes `get_angle_scale_basis` per dataset (median ATR-14)
  - Writes per-dataset angle JSON to `reports/phase3/`
  - Writes text + JSON summary with angle-family histograms
- `tests/test_adjusted_angles.py` — 86 tests:
  - Known-case: 45° at `delta_p == delta_t * price_per_bar`
  - Round-trip: slope → angle → slope within 1e-9
  - Deterministic: repeated calls produce identical output
  - delta_t = 0 raises ValueError
  - `±90°` raises ValueError in `angle_deg_to_slope`
  - Angle family bucketing and congruence tests
  - Batch `compute_impulse_angles`: raw/log modes, Impulse objects, dicts, skip rules
- `ASSUMPTIONS.md` updated: Assumptions 21–22
- `DECISIONS.md` updated: 2026-03-07 Phase 3 angle basis and gap policy

#### How to run Phase 3 smoke script
```
python -m research.run_phase3_smoke
python -m research.run_phase3_smoke --price-mode log
python -m research.run_phase3_smoke --phase2-dir reports/phase2 --output-dir reports/phase3
```

#### Smoke-run results (2026-03-07, price_mode=raw)
| Dataset | Method | Impulses | ppb (ATR) | Angles | 1x1 (45°) | 1x2 (26.6°) | 1x8 (7.1°) | Unclassified |
|---|---|---|---|---|---|---|---|---|
| 1D | pivot n=5 | 481 | 897.0 | 481 | 13 (2.7%) | 48 (10.0%) | 163 (33.9%) | 142 (29.5%) |
| 1D | zigzag 20% | 138 | 897.0 | 138 | 5 (3.6%) | 18 (13.0%) | 50 (36.2%) | 29 (21.0%) |
| 6H | pivot n=5 | 1897 | 341.6 | 1897 | 72 (3.8%) | 182 (9.6%) | 625 (32.9%) | 561 (29.6%) |
| 6H | zigzag 5% | 1588 | 341.6 | 1588 | 55 (3.5%) | 169 (10.6%) | 521 (32.8%) | 376 (23.7%) |

**Gap note (6H):** manifest `missing_bar_count=1`; angle computation uses `delta_t` (bar-index delta) which is gap-safe. No impulses skipped at this stage (gaps were handled in Phase 2).

**Tests:** `pytest -q` → 248 passed (162 Phase 1+2 + 86 Phase 3), 0 failed

#### Open Phase 3 items
- Measured move module (deferred to next Phase 3 task)
- JTTL module (deferred)
- Square-root horizontal level module (deferred)
- Time-count / squaring-the-range module (deferred)
- Log-level / semi-log module (deferred)

### Phase 3A Review — PASS (2026-03-07)

Phase 3A (adjusted angles) reviewed and accepted.

- All 5 review checks passed:
  1. **Phase 3 scope only** — no Phase 4+ drift, no projection/confluence/signal/backtest logic ✅
  2. **Single scale-basis authority** — all functions accept `scale_basis` from `core.coordinate_system.get_angle_scale_basis()`; no self-computed scales ✅
  3. **Deterministic + reproducible** — stdlib `math` only, two explicit determinism tests ✅
  4. **6H gap handling** — uses bar-index `delta_t` (gap-safe); manifest `missing_bar_count` read and logged; Assumption 22 documents policy ✅
  5. **Round-trip + edge-case tests** — 27 parametrized round-trip cases, 14+ edge-case tests ✅
- 86 Phase 3 tests + 162 Phase 1+2 tests = 248/248 pass
- Full review: `docs/reviews/phase3a_review.md`

### Phase 3B.2 Review — PASS (2026-03-07)

Phase 3B.2 (measured moves + time counts + log helpers) reviewed and accepted.

- All 5 review checks passed:
  1. **Phase 3 scope only** — no Phase 4+ drift; all occurrences of confluence/confirmation/backtest are disclaimer comments ✅
  2. **Deterministic outputs + JSON artifacts** — stdlib-only computation; `reports/phase3b/` JSON artifacts verified; dedicated determinism tests in all 3 test files ✅
  3. **Gap-safe for 6H** — all time arithmetic uses `bar_index` deltas; gap-safety integration tests pass; 6H smoke run correct with `missing_bar_count=1` ✅
  4. **Log-mode consistency** — `log_levels.py` matches `adjusted_angles.py` and `impulse.py` conventions exactly; cross-module consistency test at tolerance 1e-15 ✅
  5. **Measured move ratios correct** — raw and log formulas verified against manual computation; log symmetry property confirmed; BTC-scale values tested ✅
- 108 Phase 3B.2 tests + 349 Phase 1–3B.1 tests = 457/457 pass
- Full review: `docs/reviews/phase3b2_review.md`

**Phase 4 (confluence engine) may begin next.** All MVP Phase 3 modules are now complete and reviewed:
- Phase 3A: adjusted angles ✓ (reviewed, PASS)
- Phase 3B.1: JTTL + sqrt levels ✓ (reviewed, PASS)
- Phase 3B.2: measured moves + time counts + log helpers ✓ (reviewed, PASS)

**Note: No Phase 4+ work (projections, confluence, signals, backtest) has been started.**
