# Phase 1C Review — PASS (2026-03-06)

## Status: PASS

Phase 1C "ingest from repo raw" pipeline executed and accepted.

## What changed

New module `data/ingest_from_raw.py` added.  Reads the official live 1H raw
file committed to the repo and produces all three official MVP processed
datasets (no network required).

Raw files moved from repo root to canonical location:
- `data/raw/coinbase_rest/COINBASE_BTCUSD/1H/cbrest_COINBASE_BTCUSD_1H_UTC_2026-03-06.csv`
- `data/raw/coinbase_rest/COINBASE_BTCUSD/1H/cbrest_COINBASE_BTCUSD_1H_UTC_2026-03-06.parquet`

## Artifacts produced

| Dataset | Version | Rows | Source |
|---------|---------|------|--------|
| Primary research (1D) | `proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1` | 3 883 | Resampled from 1H repo raw |
| Confirmation (6H)     | `proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1` | 15 525 | Resampled from 1H repo raw |
| Structural (1W)       | `proc_COINBASE_BTCUSD_1W_UTC_2026-03-06_v1` | 555   | Resampled from 1D processed |

Each dataset has:
- Processed Parquet under `data/processed/<version>/`
- Manifest JSON with `validation_passed: true`
- All required derived fields: `bar_index`, `log_close`, `hl_range`, `true_range`, `atr_14`

## Validation notes

- **1D**: fully continuous (no gaps), validation passed with strict settings.
- **6H**: 1 gap of 12h (2018-08-10 exchange maintenance); `fail_on_missing_bar`
  relaxed to warn-only for 6H since the source 1H data has 20 isolated
  exchange-maintenance gaps.  All other checks pass.
- **1W**: resampled from 1D; no gaps.

## Data range

- Source 1H: 2015-07-20 21:00 UTC → 2026-03-06 00:00 UTC (93 098 bars)
- 1D: 2015-07-20 → 2026-03-06 (3 883 bars)
- 6H: 2015-07-20 18:00 UTC → 2026-03-06 00:00 UTC (15 525 bars)
- 1W: 2015-07-20 → 2026-03-02 (555 bars, Monday-aligned)

## Tests

92/92 tests pass (65 existing + 27 new/updated for `data/ingest_from_raw.py` and manifest schema).

## Reproducibility

```bash
python -m data.ingest_from_raw \
    --symbol COINBASE_BTCUSD --timeframe 1H \
    --pull-date 2026-03-06 --overwrite
```

## Config updated

`configs/default.yaml`:
- `dataset.current_version`: `proc_COINBASE_BTCUSD_1D_UTC_2026-03-06_v1`
- `dataset.version_6h`: `proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1`
- `dataset.version_1w`: `proc_COINBASE_BTCUSD_1W_UTC_2026-03-06_v1`

---

## Review checklist (2026-03-06 independent review)

### Verdict: **PASS**
### May Phase 2 begin? **Yes**

### Artifacts exist + validation

- [x] All three datasets exist (`data/processed/proc_COINBASE_BTCUSD_{1D,6H,1W}_UTC_2026-03-06_v1/`)
- [x] All three manifests exist (`.../..._manifest.json`)
- [x] `validation_passed: true` in all three manifests

### Manifest completeness

- [x] `derived_fields` present in all three manifests
  - 1D/6H: `bar_index, calendar_day_index, trading_day_index, log_close, hl_range, true_range, atr_14`
  - 1W: `[]` (no derived fields — resampled from 1D; appropriate per weekly policy)
- [x] `atr_warmup_rows` present (1D/6H: 14, 1W: 0)
- [x] `bar_index_epoch_timestamp` present in all three
- [x] `start_timestamp` and `end_timestamp` present in all three
- [x] Row counts (`row_count_raw`, `row_count_processed`) present in all three

### Missing-bar exception

- [x] 6H manifest records 1 missing bar:
  ```json
  "missing_bar_count": 1,
  "missing_bar_policy": "relaxed (fail_on_missing_bar=False, max_allowed=5)",
  "missing_bar_details": ["~1 missing bar(s) after 2018-08-10T00:00:00+00:00 (gap=0 days 12:00:00)"]
  ```
- [x] Tolerance explicitly documented in `DECISIONS.md` (2026-03-06 change log)
- [x] Tolerance explicitly documented in `ASSUMPTIONS.md` (Assumption 18)
- [x] Exception does not silently violate default policy:
  - Default in `configs/default.yaml` remains `fail_on_missing_bar: true`, `max_allowed_missing_bars: 0`
  - Override applied only in `data/ingest_from_raw.py` via `_VALIDATION_OVERRIDE_6H`

### Repo data commit policy safety

- [x] Decision recorded in `DECISIONS.md` (2026-03-06 — repo data commit policy)
- [x] Total committed data footprint: ~12 MB (within safe limits)
- [x] Stale root-level data files removed from tracking (`cbrest_*` at repo root)
- [x] `.gitignore` updated with `/cbrest_*` and `/proc_*` to prevent future root-level commits
- [x] Upgrade path documented: Git LFS if repo exceeds 100 MB

### Conditions for Phase 2

- Do not make performance claims until walk-forward testing is complete (Phase 6)
- Downstream modules depending on gap-free 6H data should check `missing_bar_count`
  in the manifest before consuming the dataset
