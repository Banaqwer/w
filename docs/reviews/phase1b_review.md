# Phase 1B Dataset-Execution Review

**Reviewer:** Automated review agent
**Date:** 2026-03-04
**Scope:** Phase 1B pipeline execution — synthetic/offline validation run

---

## 1. Verdict

### **PASS** — Phase 1B synthetic validation is accepted

Phase 1B pipeline execution is **acceptable as a synthetic/offline validation run**.

A **live rerun without `--use-synthetic`** is still required before Phase 2 results
can be considered official. The pipeline, schema, manifests, and validation all
function correctly. The outstanding item is replacing synthetic data with real
Coinbase REST API data once API access is available.

---

## 2. Artifact Inventory

All 10 required artifacts were produced and verified:

| # | Artifact | Path | Status |
|---|----------|------|--------|
| 1 | 1D raw CSV | `data/raw/coinbase_rest/COINBASE_BTCUSD/1D/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.csv` | ✅ Present (294 585 bytes) |
| 2 | 1D extraction metadata JSON | `data/metadata/extractions/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.json` | ✅ Present |
| 3 | 1D processed Parquet | `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1.parquet` | ✅ Present (400 292 bytes) |
| 4 | 1D manifest JSON | `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1_manifest.json` | ✅ Present |
| 5 | 4H raw CSV | `data/raw/coinbase_rest/COINBASE_BTCUSD/4H/cbrest_COINBASE_BTCUSD_4H_UTC_2026-03-04.csv` | ✅ Present (2 443 483 bytes) |
| 6 | 4H extraction metadata JSON | `data/metadata/extractions/cbrest_COINBASE_BTCUSD_4H_UTC_2026-03-04.json` | ✅ Present |
| 7 | 4H processed Parquet | `data/processed/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1.parquet` | ✅ Present (2 842 946 bytes) |
| 8 | 4H manifest JSON | `data/processed/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1_manifest.json` | ✅ Present |
| 9 | 1W processed Parquet | `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1.parquet` | ✅ Present (33 167 bytes) |
| 10 | 1W manifest JSON | `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1_manifest.json` | ✅ Present |

---

## 3. Manifest Field Verification

### 1D Manifest

| Field | Value | Status |
|-------|-------|--------|
| `validation_passed` | `true` | ✅ |
| `derived_fields` | `["bar_index", "calendar_day_index", "trading_day_index", "log_close", "hl_range", "true_range", "atr_14"]` | ✅ |
| `atr_warmup_rows` | `14` | ✅ |
| `bar_index_epoch_timestamp` | `"2013-01-01 00:00:00+00:00"` | ✅ |

### 4H Manifest

| Field | Value | Status |
|-------|-------|--------|
| `validation_passed` | `true` | ✅ |
| `derived_fields` | `["bar_index", "calendar_day_index", "trading_day_index", "log_close", "hl_range", "true_range", "atr_14"]` | ✅ |
| `atr_warmup_rows` | `14` | ✅ |
| `bar_index_epoch_timestamp` | `"2013-01-01 00:00:00+00:00"` | ✅ |

### 1W Manifest

| Field | Value | Status |
|-------|-------|--------|
| `validation_passed` | `true` | ✅ |
| `derived_fields` | `[]` (expected — weekly is resampled, no separate coordinate system) | ✅ |
| `atr_warmup_rows` | `0` (expected — resampled dataset) | ✅ |
| `bar_index_epoch_timestamp` | `"2012-12-31 00:00:00+00:00"` (Monday before 2013-01-01) | ✅ |

---

## 4. Actual Start/End Timestamps (from processed Parquet files)

| Dataset | Rows | Start Timestamp | End Timestamp |
|---------|------|-----------------|---------------|
| **1D** | 4 811 | `2013-01-01 00:00:00+00:00` | `2026-03-04 00:00:00+00:00` |
| **4H** | 28 861 | `2013-01-01 00:00:00+00:00` | `2026-03-04 00:00:00+00:00` |
| **1W** | 688 | `2012-12-31 00:00:00+00:00` | `2026-03-02 00:00:00+00:00` |

**Notes:**
- 1W start date is `2012-12-31` (Monday) because the first daily bar (2013-01-01, a Tuesday)
  falls within the week starting Monday 2012-12-31 — consistent with `W-MON` resampling.
- 1W end date is `2026-03-02` (Monday) — the last complete weekly bar boundary before the
  pull date of 2026-03-04.
- All timestamps are UTC-aware (`+00:00`).

---

## 5. Processed Dataset Column Schema

### 1D and 4H (full coordinate system)

```
timestamp, open, high, low, close, volume,
bar_index, calendar_day_index, trading_day_index,
log_close, hl_range, true_range, atr_14
```

All 13 columns present. ✅

### 1W (resampled — OHLCV only)

```
timestamp, open, high, low, close, volume
```

6 columns — expected for a resampled dataset (no separate coordinate system computed). ✅

---

## 6. Extraction Metadata Verification

Both 1D and 4H extraction metadata JSONs contain:

| Field | 1D Value | 4H Value |
|-------|----------|----------|
| `extraction_method` | `"synthetic_generated"` | `"synthetic_generated"` |
| `bar_count` | `4811` | `28861` |
| `first_bar_timestamp` | `"2013-01-01 00:00:00+00:00"` | `"2013-01-01 00:00:00+00:00"` |
| `last_bar_timestamp` | `"2026-03-04 00:00:00+00:00"` | `"2026-03-04 00:00:00+00:00"` |
| `timezone_assumption` | `"UTC"` | `"UTC"` |
| `checksum_sha256` | present | present |
| `user_note` | `"Synthetic data — offline/sandbox pull — 2026-03-04"` | `"Synthetic data — offline/sandbox pull — 2026-03-04"` |

Extraction method is clearly marked as `"synthetic_generated"`, not `"coinbase_rest_ccxt"`. ✅

---

## 7. Test Suite Results

```
59 passed, 0 failed (pytest 9.0.2, Python 3.12.3)
```

All tests in `test_validation.py` (18), `test_coordinate_system.py` (22), and
`test_ingestion.py` (19) pass. ✅

---

## 8. Synthetic vs. Live-Data Assessment

### This run IS:
- ✅ A valid synthetic/offline validation run
- ✅ Full end-to-end pipeline execution using `--use-synthetic` (generate_synthetic_ohlcv)
- ✅ All validation checks, derived fields, and manifest generation working correctly
- ✅ Extraction metadata clearly marks `extraction_method: "synthetic_generated"`
- ✅ User notes clearly state `"Synthetic data — offline/sandbox pull"`

### This run is NOT:
- ❌ The final official live Coinbase dataset milestone
- ❌ Using real market OHLCV data from the Coinbase REST API
- ❌ Spot-checked against TradingView `COINBASE:BTCUSD` chart (per Assumption 16 testing requirements)

---

## 9. Remaining Action Before Phase 2 Can Use Official Data

1. When the live Coinbase REST API (`api.coinbase.com`) is accessible, re-run:
   ```bash
   python -m data.extract --timeframe 1D \
       --version proc_COINBASE_BTCUSD_1D_UTC_<date>_v1 \
       --pull-date <date> --overwrite

   python -m data.extract --timeframe 4H \
       --version proc_COINBASE_BTCUSD_4H_UTC_<date>_v1 \
       --pull-date <date> --overwrite

   python -m data.extract \
       --resample-weekly-from proc_COINBASE_BTCUSD_1D_UTC_<date>_v1 \
       --pull-date <date> --overwrite
   ```
2. Spot-check ≥ 20 bars against TradingView `COINBASE:BTCUSD` daily chart.
3. Log any discrepancies > 0.1% in `DECISIONS.md`.
4. Update `configs/default.yaml` `dataset.current_version` to the new version string.

---

## 10. Summary

| Check | Result |
|-------|--------|
| All 10 artifacts produced | ✅ |
| Manifests include `validation_passed` | ✅ |
| Manifests include `derived_fields` | ✅ |
| Manifests include `atr_warmup_rows` | ✅ |
| Manifests include `bar_index_epoch_timestamp` | ✅ |
| Actual timestamps reported for 1D, 4H, 1W | ✅ |
| 59/59 tests pass | ✅ |
| Synthetic validation run (not live data) | ✅ Confirmed |
| Pipeline code, schema, validation correct | ✅ |
| Live rerun still required | ✅ Acknowledged |

**Verdict: PASS**

- Phase 1B synthetic validation is **accepted**.
- A live rerun without `--use-synthetic` is **still required** before Phase 2 results
  can be treated as official research outputs.
