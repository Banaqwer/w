# Project Status - Jenkins Quant Project

## Current phase
- Phase 2 — Structural pivot and impulse engine (IN PROGRESS — 2026-03-06)

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

## Notes
Phase 1C is complete. Official live datasets are now in place.
Phase 2 (structural pivot and impulse engine) is now **IN PROGRESS** as of 2026-03-06.

---

## Phase 2 — IN PROGRESS (started 2026-03-06)

### What was implemented

#### A) Origin selection — `modules/origin_selection.py`

Two detectors, both fully configurable:

1. **N-bar pivot** (`method="pivot"`, `pivot_n=N`)
   A bar is a pivot-high when its `high` strictly exceeds the `high` of every bar
   within N bars before and after it.  Same rule for pivot-low using `low`.
   Configurable: `pivot_n`, `min_quality`, `atr_warmup_rows`.

2. **Percent-threshold zigzag** (`method="zigzag"`, `threshold_pct=X`)
   Detects swing reversals when price moves at least X% from the last confirmed
   extreme.  ATR-based mode is also available (`threshold_atr=Y`).
   Configurable: `threshold_pct`, `threshold_atr`, `zigzag_price_field`, `atr_warmup_rows`.

`Origin` dataclass fields: `origin_time`, `origin_price`, `bar_index`,
`origin_type` (high/low), `detector_name`, `quality_score`.

`select_origins()` is the unified entry-point dispatcher.

#### B) Impulse detection — `modules/impulse.py`

`detect_impulses()` accepts a processed OHLCV DataFrame and a list of Origins.
For each origin it searches forward for the running extreme (highest high for upward
impulses, lowest low for downward), with early-stop on `reversal_pct` pullback.

`Impulse` dataclass fields (fully compatible with Phase 0 / CLAUDE.md spec):
`impulse_id`, `origin_time`, `origin_price`, `extreme_time`, `extreme_price`,
`origin_bar_index`, `extreme_bar_index`, `delta_t`, `delta_p`,
`slope_raw`, `slope_log`, `direction`, `quality_score`, `detector_name`,
`gap_in_window`.

**Gap handling for 6H data:**
- `skip_on_gap=True` (recommended when `missing_bar_count > 0`): any forward-search
  window containing a bar_index gap (increment > 1) is skipped; no impulse is produced.
- `skip_on_gap=False`: gaps are ignored; `gap_in_window=True` is flagged on the Impulse.
- The smoke script reads the manifest's `missing_bar_count` and sets `skip_on_gap`
  automatically.

#### C) Phase 2 smoke script — `research/run_phase2_smoke.py`

Runs origin selection + impulse detection on both 1D (required) and 6H (optional).
Reads dataset versions from `configs/default.yaml`.
Checks `missing_bar_count` from the 6H manifest and activates `skip_on_gap` accordingly.
Writes outputs to `reports/phase2/`.

#### D) Tests

- `tests/test_phase2_origin_selection.py` — 29 tests for pivot and zigzag detectors
- `tests/test_phase2_impulse.py` — 22 tests for impulse detection and gap handling
- All 143 tests pass (92 Phase 1 + 51 Phase 2).

#### E) Documentation

- `ASSUMPTIONS.md` updated with Assumptions 19–26 (Phase 2 decisions).
- `PROJECT_STATUS.md` updated (this section).

### How to run the Phase 2 smoke script

From the repository root (after `pip install -e ".[dev]"`):

```bash
# Full run: 1D (required) + 6H (optional, gap-aware)
python -m research.run_phase2_smoke

# Skip the 6H run
python -m research.run_phase2_smoke --skip-6h

# Custom config path
python -m research.run_phase2_smoke --config configs/default.yaml
```

Outputs are written to:
- `reports/phase2/origins_proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1.json`
- `reports/phase2/impulses_proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1.json`
- `reports/phase2/origins_proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1.json`
- `reports/phase2/impulses_proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1.json`

### Example output counts (2026-03-06 live dataset)

| Dataset | Rows | Missing bars | skip_on_gap | Pivot origins | Zigzag origins | Pivot impulses | Zigzag impulses |
|---|---|---|---|---|---|---|---|
| 1D (2026-03-06) | 3 883 | 0 | False | 481 | 1 488 | 465 | 1 314 |
| 6H (2026-03-06) | 15 525 | 1 | True | 1 923 | 3 022 | 1 887 | 2 828 |

Parameters used: `pivot_n=5`, `zigzag_pct=3.0%`, `max_lookahead=200`, `reversal_pct=20%`.

### Open Phase 2 items

1. **Impulse quality tuning** — The `quality_score` formula (Assumption 20) uses a fixed
   3× ATR normalisation factor.  This will be cross-checked against visually prominent
   BTC/USD impulses during Phase 3 validation and may be revised.
2. **Zigzag `zigzag_price_field` validation** — The stored `origin_price` for zigzag
   origins is from `close` by default.  Phase 3 angle modules may prefer `high`/`low`.
   This is config-driven and can be changed without re-running origin selection from scratch.
3. **Origin deduplication** — If both pivot and zigzag detectors are run, the same
   structural point may appear twice.  Downstream callers (Phase 3+) should deduplicate
   if needed.  No deduplication is applied at the Phase 2 level (Assumption 25).
4. **Reversal-pct tuning** — The default `reversal_pct=20%` was chosen to avoid
   premature truncation on BTC/USD daily data.  Structural research in Phase 3 may
   reveal a better value.

### Immediate next actions for Phase 2 completion

Phase 2 is structurally functional.  The following steps remain before declaring it
complete:
- Cross-check a sample of detected impulses against TradingView chart (visual sanity)
- Decide on a deduplication/ranking policy for multi-detector origin sets
- Confirm Phase 3 (projection stack) is ready to consume the Impulse output format
