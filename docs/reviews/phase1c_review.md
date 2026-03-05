# Phase 1C Review — First Official Dataset Pull Under 6H Timeframe Policy

**Date:** 2026-03-05
**Reviewer note:** Automated milestone execution. Results documented per problem-statement requirements.

---

## Objective

Run the first official dataset pull under the updated timeframe policy:

- `1D` — primary (live Coinbase REST via ccxt)
- `6H` — confirmation/execution (live Coinbase REST via ccxt; replaces `4H`)
- `1W` — structural (resampled from `1D`)

---

## Live Pull Attempt — FAILED (sandbox network restriction)

### 1D live attempt

```
python -m data.extract --timeframe 1D \
    --version proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1 \
    --pull-date 2026-03-05 --overwrite
```

**Result:** `FAILED`

**Error:**
```
ccxt.base.errors.NetworkError: coinbase GET https://api.coinbase.com/v2/currencies
```

**Cause:** The Coinbase REST API (`api.coinbase.com`) is not reachable from the sandboxed
CI/agent environment. DNS resolution or outbound HTTPS is blocked. This is the same
condition recorded in Phase 1B (2026-03-04).

The 6H live pull was not attempted after the 1D failure.

---

## Synthetic Fallback — Phase 1C Datasets Produced

Per the established protocol (see `PROJECT_STATUS.md` Phase 1B note and `data/extract.py`
docstring), when the live API is unreachable the `--use-synthetic` flag is used to produce
structurally-identical datasets for pipeline and test validation. The schema, manifest,
validation logic, and derived fields are identical to what a live pull would produce.

---

## Commands Run

```bash
# Step 1 — 1D synthetic pull
python -m data.extract \
    --timeframe 1D \
    --version proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1 \
    --pull-date 2026-03-05 \
    --overwrite \
    --use-synthetic

# Step 2 — 6H synthetic pull (official confirmation TF under 2026-03-05 policy)
python -m data.extract \
    --timeframe 6H \
    --version proc_COINBASE_BTCUSD_6H_UTC_2026-03-05_v1 \
    --pull-date 2026-03-05 \
    --overwrite \
    --use-synthetic

# Step 3 — 1W resampled from processed 1D
python -m data.extract \
    --resample-weekly-from proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1 \
    --pull-date 2026-03-05 \
    --overwrite

# Step 4 — tests
python -m pytest tests/ -q
```

---

## Artifact Paths and Row Counts

### 1D dataset

| Field | Value |
|-------|-------|
| **dataset_version** | `proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1` |
| **raw CSV** | `data/raw/coinbase_rest/COINBASE_BTCUSD/1D/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-05.csv` |
| **extraction metadata** | `data/metadata/extractions/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-05.json` |
| **processed Parquet** | `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1.parquet` |
| **manifest** | `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1_manifest.json` |
| **start timestamp** | `2013-01-01 00:00:00+00:00` |
| **end timestamp** | `2026-03-05 00:00:00+00:00` |
| **row count** | **4 812** |
| **data source** | synthetic (live API unreachable) |

### 6H dataset

| Field | Value |
|-------|-------|
| **dataset_version** | `proc_COINBASE_BTCUSD_6H_UTC_2026-03-05_v1` |
| **raw CSV** | `data/raw/coinbase_rest/COINBASE_BTCUSD/6H/cbrest_COINBASE_BTCUSD_6H_UTC_2026-03-05.csv` |
| **extraction metadata** | `data/metadata/extractions/cbrest_COINBASE_BTCUSD_6H_UTC_2026-03-05.json` |
| **processed Parquet** | `data/processed/proc_COINBASE_BTCUSD_6H_UTC_2026-03-05_v1/proc_COINBASE_BTCUSD_6H_UTC_2026-03-05_v1.parquet` |
| **manifest** | `data/processed/proc_COINBASE_BTCUSD_6H_UTC_2026-03-05_v1/proc_COINBASE_BTCUSD_6H_UTC_2026-03-05_v1_manifest.json` |
| **start timestamp** | `2013-01-01 00:00:00+00:00` |
| **end timestamp** | `2026-03-05 00:00:00+00:00` |
| **row count** | **19 245** |
| **data source** | synthetic (live API unreachable) |

### 1W dataset (resampled from 1D)

| Field | Value |
|-------|-------|
| **dataset_version** | `proc_COINBASE_BTCUSD_1W_UTC_2026-03-05_v1` |
| **processed Parquet** | `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-05_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-05_v1.parquet` |
| **manifest** | `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-05_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-05_v1_manifest.json` |
| **start timestamp** | `2012-12-31 00:00:00+00:00` |
| **end timestamp** | `2026-03-02 00:00:00+00:00` |
| **row count** | **688** |
| **source** | resampled from `proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1` |

---

## Manifest Field Confirmation

All manifests contain:

| Field | 1D | 6H | 1W |
|-------|----|----|-----|
| `validation_passed` | `true` | `true` | `true` |
| `derived_fields` | bar_index, calendar_day_index, trading_day_index, log_close, hl_range, true_range, atr_14 | same | `[]` (1W has no ATR warmup) |
| `atr_warmup_rows` | 14 | 14 | 0 |
| `bar_index_epoch_timestamp` | `2013-01-01 00:00:00+00:00` | `2013-01-01 00:00:00+00:00` | `2012-12-31 00:00:00+00:00` |
| `coordinate_system_version` | `v1` | `v1` | `v1` |
| `source_raw_file` | present | present | points to 1D Parquet |
| `source_metadata` | present | present | `"resampled_from_daily"` |

---

## pytest Results

```
pytest -q
65 passed in 0.82s
```

All 65 tests pass (up from 59 in Phase 1B; 6 additional tests from test suite expansion).

---

## Phase 1C Milestone Assessment

| Item | Status |
|------|--------|
| Live 1D pull attempted | ✅ Attempted; failed — NetworkError (sandbox blocks api.coinbase.com) |
| Live 6H pull attempted | N/A — not attempted after 1D live failure per documented protocol |
| 1D synthetic fallback produced | ✅ 4 812 rows, 2013-01-01 → 2026-03-05, validation passed |
| 6H synthetic fallback produced | ✅ 19 245 rows, 2013-01-01 → 2026-03-05, validation passed |
| 1W resampled from 1D | ✅ 688 rows, 2012-12-31 → 2026-03-02, validation passed |
| All manifests contain required fields | ✅ |
| pytest -q passes | ✅ 65/65 |
| 6H timeframe policy applied | ✅ No 4H dataset produced |
| `configs/default.yaml` updated | ✅ `dataset.current_version` → `proc_COINBASE_BTCUSD_1D_UTC_2026-03-05_v1` |

**Phase 1C milestone status: CONDITIONALLY COMPLETE (synthetic/sandbox)**

The pipeline is fully validated with the updated 6H timeframe policy. A live Coinbase API
rerun without `--use-synthetic` is still required to produce the final production datasets.
When live API access is restored, re-run:

```bash
python -m data.extract --timeframe 1D \
    --version proc_COINBASE_BTCUSD_1D_UTC_<date>_v1 \
    --pull-date <date> --overwrite

python -m data.extract --timeframe 6H \
    --version proc_COINBASE_BTCUSD_6H_UTC_<date>_v1 \
    --pull-date <date> --overwrite

python -m data.extract \
    --resample-weekly-from proc_COINBASE_BTCUSD_1D_UTC_<date>_v1 \
    --pull-date <date> --overwrite
```

---

## Notes

- This is the first Phase 1C run under the **6H timeframe policy** (2026-03-05 decision).
  No 4H dataset was produced.
- The sandbox network restriction is persistent and expected. It is not a code defect.
- `generate_synthetic_ohlcv()` uses a fixed random seed (42) so outputs are reproducible.
- The `1W` weekly resample boundary is Monday 00:00 UTC, consistent with
  `configs/default.yaml` `weekly_boundary`.
