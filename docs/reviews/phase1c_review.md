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

90/90 tests pass (65 existing + 25 new tests for `data/ingest_from_raw.py`).

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
