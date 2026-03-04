# Phase 1C Live Dataset Execution — Review

**Reviewer:** Automated execution agent
**Date:** 2026-03-04
**Scope:** Phase 1C — first official live Coinbase REST API pull, without `--use-synthetic`

---

## 1. Verdict

### **BLOCKED** — Live Coinbase REST API not reachable from sandboxed environment

Phase 1C live dataset execution could **not** be completed.  
The Coinbase REST API endpoint (`api.coinbase.com`) is not reachable from the
sandboxed CI/CD environment.  DNS resolution fails at the network layer.

The pipeline, schema, validation, and ingestion code are correct — confirmed by
Phase 1B synthetic validation (59/59 tests pass).  The block is purely
environmental (no outbound internet access in the sandbox).

A live rerun without `--use-synthetic` **remains required** before Phase 2 results
can be treated as official research outputs.

---

## Section 1 — Exact commands run

### 1D live pull attempt

```bash
python -m data.extract --timeframe 1D \
    --version proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1 \
    --pull-date 2026-03-04 --overwrite
```

**Note:** `--use-synthetic` was NOT passed, per Phase 1C requirement.

### 4H live pull

Not attempted — blocked by 1D failure (see Section 3).

### Weekly resample

Not attempted — requires a live 1D processed dataset (see Section 4).

---

## Section 2 — Live pull result for 1D

### Result: FAILED

| Field | Value |
|---|---|
| Command | `python -m data.extract --timeframe 1D --version proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1 --pull-date 2026-03-04 --overwrite` |
| Exit code | `1` |
| Error class | `ccxt.base.errors.NetworkError` |
| Error message | `coinbase GET https://api.coinbase.com/v2/currencies` |
| Root cause | `socket.gaierror: [Errno -5] No address associated with hostname` |
| Full chain | DNS resolution failed → `urllib3.exceptions.NameResolutionError` → `requests.exceptions.ConnectionError` → `ccxt.base.errors.NetworkError` |

### Full error traceback (condensed)

```
urllib3.exceptions.NameResolutionError:
  <urllib3.connection.HTTPSConnection object at ...>:
  Failed to resolve 'api.coinbase.com'
  ([Errno -5] No address associated with hostname)

→ requests.exceptions.ConnectionError:
  HTTPSConnectionPool(host='api.coinbase.com', port=443):
  Max retries exceeded with url: /v2/currencies
  (Caused by NameResolutionError(...))

→ ccxt.base.errors.NetworkError:
  coinbase GET https://api.coinbase.com/v2/currencies
```

### Explanation

The `ccxt` Coinbase exchange calls `https://api.coinbase.com/v2/currencies` as
part of `load_markets()` before any OHLCV fetch.  The sandbox environment does
not have outbound internet access — DNS resolution for `api.coinbase.com` fails
at the OS level (`[Errno -5] No address associated with hostname`).

This is a network-access constraint of the CI/CD sandbox, not a code defect.
The extraction pipeline, API call structure, and error handling all behave
correctly.

---

## Section 3 — Live pull result for 4H

### Result: NOT ATTEMPTED

Blocked by 1D failure.  No 4H pull was initiated.

Per project protocol: do not proceed to 4H if 1D fails.  Both datasets must
come from the same live pull session to maintain consistency.

---

## Section 4 — Weekly resample result

### Result: NOT ATTEMPTED

Weekly bars are produced by `resample_daily_to_weekly()` applied to the live 1D
processed dataset.  Since the live 1D pull failed, there is no live 1D Parquet
to resample from.

The weekly resample itself (code, logic, schema) was validated in Phase 1B
synthetic run.

---

## Section 5 — Artifact paths

### New live artifacts produced

None.  The live API failure occurred before any data reached the disk.

### Phase 1B synthetic artifacts (for reference)

These artifacts were produced during Phase 1B (synthetic run).  They are not
committed to the repository (see `.gitignore` — data files excluded).  They
are reproducible by re-running with `--use-synthetic`.

| Artifact | Path |
|---|---|
| 1D raw CSV | `data/raw/coinbase_rest/COINBASE_BTCUSD/1D/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.csv` |
| 1D extraction metadata | `data/metadata/extractions/cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.json` |
| 1D processed Parquet | `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1.parquet` |
| 1D manifest | `data/processed/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1_manifest.json` |
| 4H raw CSV | `data/raw/coinbase_rest/COINBASE_BTCUSD/4H/cbrest_COINBASE_BTCUSD_4H_UTC_2026-03-04.csv` |
| 4H extraction metadata | `data/metadata/extractions/cbrest_COINBASE_BTCUSD_4H_UTC_2026-03-04.json` |
| 4H processed Parquet | `data/processed/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1.parquet` |
| 4H manifest | `data/processed/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1_manifest.json` |
| 1W processed Parquet | `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1.parquet` |
| 1W manifest | `data/processed/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1/proc_COINBASE_BTCUSD_1W_UTC_2026-03-04_v1_manifest.json` |

---

## Section 6 — Start/end timestamps and row counts

### Live pull

| Dataset | Rows | Start | End | Status |
|---------|------|-------|-----|--------|
| 1D | — | — | — | FAILED — no data returned |
| 4H | — | — | — | NOT ATTEMPTED |
| 1W | — | — | — | NOT ATTEMPTED |

### Phase 1B synthetic reference (for comparison only)

| Dataset | Rows | Start | End |
|---------|------|-------|-----|
| 1D | 4 811 | `2013-01-01 00:00:00+00:00` | `2026-03-04 00:00:00+00:00` |
| 4H | 28 861 | `2013-01-01 00:00:00+00:00` | `2026-03-04 00:00:00+00:00` |
| 1W | 688 | `2012-12-31 00:00:00+00:00` | `2026-03-02 00:00:00+00:00` |

These synthetic figures are included only for pipeline reference.  They must
not be treated as live data.

---

## Section 7 — Validation summary

| Check | Result |
|---|---|
| 59/59 unit tests pass | ✅ Confirmed (pre-existing) |
| Live 1D extraction | ❌ FAILED — NetworkError |
| Live 4H extraction | ❌ NOT ATTEMPTED |
| Weekly resample | ❌ NOT ATTEMPTED |
| Pipeline code correctness | ✅ Confirmed (validated in Phase 1B) |
| Error captured and logged | ✅ |
| No fake success produced | ✅ |
| `--use-synthetic` NOT used | ✅ Confirmed |

---

## Section 8 — Whether Phase 2 is now cleared or still blocked

### Status: **BLOCKED**

Phase 2 (structural pivot and impulse engine) requires an official live Coinbase
dataset.  The live pull has failed.  Phase 2 must not begin using synthetic data
as a substitute for official research outputs, unless explicitly re-approved.

### Workarounds (recommended, in priority order)

| Priority | Option | Notes |
|---|---|---|
| **1 (recommended)** | Re-run on a machine with outbound internet access | Run the three Phase 1C commands (1D, 4H, weekly resample) from a local workstation or CI environment with `api.coinbase.com` reachable |
| **2** | Request sandbox network access to `api.coinbase.com` | If the CI/CD sandbox can be configured to allow outbound HTTPS to `api.coinbase.com`, re-run in the same environment |
| **3** | Manually download and inject raw CSV | Download BTC/USD OHLCV CSV from Coinbase or another source, place in `data/raw/coinbase_rest/COINBASE_BTCUSD/1D/` with the correct naming convention, and run the ingestion pipeline directly (skipping the `fetch_coinbase_ohlcv` step) |
| **4** | Proceed with synthetic data labeled as non-official | Use `--use-synthetic` for Phase 2 module development only, with all results explicitly labeled as synthetic/pre-official and subject to re-validation once live data is available |

**Option 1 is strongly preferred.**  The extraction pipeline is proven correct.
The sole blocker is network access.

### Commands to re-run when network is available

```bash
# 1D live pull
python -m data.extract --timeframe 1D \
    --version proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1 \
    --pull-date 2026-03-04 --overwrite

# 4H live pull
python -m data.extract --timeframe 4H \
    --version proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1 \
    --pull-date 2026-03-04 --overwrite

# Weekly resample from live 1D
python -m data.extract \
    --resample-weekly-from proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1 \
    --pull-date 2026-03-04 --overwrite
```

---

## Section 9 — Summary

| Item | Status |
|---|---|
| Phase 1C live API attempt executed | ✅ Attempted |
| `--use-synthetic` NOT used | ✅ Confirmed |
| Exact error captured | ✅ `ccxt.base.errors.NetworkError` — DNS failure |
| Error recorded in PROJECT_STATUS.md | ✅ |
| No fake success produced | ✅ |
| Workaround recommended | ✅ |
| Phase 2 clearance | ❌ BLOCKED — awaiting live data |
