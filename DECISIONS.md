# Decisions - Jenkins Quant Project

This file records the project's frozen high-level decisions.

## Current approved decisions

### Environment
- Python is the official research, testing, and backtesting environment.
- TradingView is not the official source of truth for backtests or final research results.

### TradingView and MCP
- The user's TradingView <-> Claude MCP bridge is retained for current-bar snapshot sanity checks only.
- ~~MCP may be used to extract official raw historical candle datasets and metadata.~~ **SUPERSEDED 2026-03-04** — `tradingview-mcp` cannot provide bulk historical OHLCV. See 2026-03-04 change log.
- Official historical OHLCV acquisition: Coinbase REST API via `ccxt` (see 2026-03-04 change log).
- Official experiments must run on saved, normalized, versioned datasets after extraction.

### MVP market scope
- MVP market: BTC/USD
- Official TradingView symbol: `COINBASE:BTCUSD`
- Instrument type: Spot

### Time conventions
- Official timezone: UTC
- Official daily close: 00:00 UTC
- Official main research timeframe: Daily
- Official confirmation timeframe: 6H (**supersedes 4H — see 2026-03-05 change log**)
- Official higher-structure timeframe: Weekly

### 6H policy
- Pull native 6H candles directly from Coinbase REST API (`ccxt` `fetch_ohlcv`, timeframe `6h`).
- If native 6H history is shallower than required, resample from 1H native pull.
- Do not mix native 6H and resampled 6H within the same official MVP experiment family.
- ~~4H policy~~ — **SUPERSEDED 2026-03-05** by 6H policy. See 2026-03-05 change log.

### Weekly policy
- Weekly bars must use a fixed UTC-based weekly boundary.
- Default interpretation: Monday 00:00 UTC to next Monday 00:00 UTC.

### Data storage
- Raw Coinbase REST exports are stored under `data/raw/coinbase_rest/<symbol>/<timeframe>/` (see 2026-03-04 change log)
- Processed research datasets are stored under `data/processed/<dataset_version>/`
- Extraction metadata is stored under `data/metadata/extractions/`

### Dataset naming
- Raw datasets: `cbrest_<symbol>_<timeframe>_<timezone>_<pull-date>` (see 2026-03-04 change log)
- Processed datasets: `proc_<symbol>_<timeframe>_<timezone>_<source-date>_v<revision>`

### Data integrity
- Missing bars must be detected and logged.
- No silent OHLC fill-forward is allowed in the official MVP dataset.
- Every official experiment must reference an exact processed dataset version.

## Change-control rule
If any decision in this file changes:
1. record the date
2. describe the old rule
3. describe the new rule
4. explain why the change was made
5. note whether prior experiments are affected

---

## Change log

### 2026-03-06 — Phase 2: gap-handling rule for impulse detection

**Decision: When `missing_bar_count > 0` in a dataset manifest, pass `skip_on_gap=True` to `detect_impulses`.  Origins whose forward window crosses a detected gap are silently skipped; no Impulse is produced for them.**

| Property | Value |
|---|---|
| Gap detection rule | timestamp diff > 1.5 × median inter-bar interval |
| 6H dataset (`missing_bar_count=1`) | `skip_on_gap=True` (auto-set by smoke script) |
| 1D dataset (`missing_bar_count=0`) | `skip_on_gap=False` |
| Affected origins (6H pivot) | 26 skipped out of 1923 |
| Affected origins (6H zigzag 5 %) | 16 skipped out of 1604 |

**Rationale:**
1. A missing bar creates a false price-jump in the window, which would inflate `delta_p`, `slope_raw`, and `slope_log`.
2. Silently skipping is simpler and safer than attempting to interpolate across the gap.
3. The rule is documented so any downstream module can replicate it.

**Prior experiments affected:** None — Phase 2 is the first use of impulse detection.

---

### 2026-03-06 — Phase 1C: repo data commit policy

**Decision: Raw and processed datasets are committed to the repository for MVP reproducibility.**

| Property | Value |
|---|---|
| Raw 1H source | Committed (`data/raw/coinbase_rest/`) |
| Processed Parquet | Committed (`data/processed/`) |
| Manifests (JSON) | Committed (`data/processed/<version>/`) |
| Extraction metadata | Git-ignored (`data/metadata/extractions/`) |
| Maximum acceptable repo data footprint | ~50 MB (review if exceeded) |
| Recommended upgrade path | Git LFS if repo size exceeds 100 MB |

**Rationale:**
1. Total committed data footprint is currently ~12 MB — well within GitHub's limits.
2. Committing data ensures anyone cloning the repo can reproduce Phase 2+
   experiments without re-running extraction (Coinbase REST API unreachable in CI).
3. Manifests are always committed as the metadata source of truth.
4. If the data grows substantially (additional timeframes, markets, or longer
   history), migrate raw/processed files to Git LFS and commit only manifests.

**Prior experiments affected:** None.

---

### 2026-03-06 — Phase 1C: 6H missing-bar tolerance for resampled-from-1H datasets

**Decision: A small number of exchange-maintenance gaps in the 6H dataset are tolerated when resampling from 1H source data.**

The default validation policy (`fail_on_missing_bar: true`, `max_allowed_missing_bars: 0`)
is overridden for 6H resampled-from-1H datasets with
`fail_on_missing_bar: False`, `max_allowed_missing_bars: 5`.

**Observed gap (Phase 1C, `proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1`):**
- 1 missing 6H bar after `2018-08-10T00:00:00+00:00` (12-hour gap)
- Cause: Coinbase exchange maintenance window

**Recording in manifest:**
Every manifest now includes `missing_bar_count`, `missing_bar_policy`, and
`missing_bar_details` fields.  The 6H manifest records the exact gap
timestamp and policy override for reproducibility.

**Rationale:**
1. The 1H source data from the Coinbase REST API contains isolated exchange-maintenance
   gaps that are outside project control.
2. A single missing 6H bar out of 15 525 is immaterial to structural research.
3. The tolerance is capped at 5 bars; any dataset exceeding that fails validation.
4. Strict policy remains the default; the override is applied only in
   `data/ingest_from_raw.py` for 6H resampled-from-1H datasets.

**Prior experiments affected:** None — this is the first official 6H dataset.

---

### 2026-03-05 — Intraday confirmation timeframe changed from 4H to 6H

**Superseded rule:**
> "Official confirmation timeframe: 4H"
> "Pull native 4H candles directly from Coinbase REST API (`ccxt` `fetch_ohlcv`, timeframe `4h`).
>  If native 4H history is shallower than required, resample from 1H native pull.
>  Do not mix native 4H and resampled 4H within the same official MVP experiment family."

**Decision: Official intraday confirmation timeframe is now 6H**

Native Coinbase `6H` is the official intraday confirmation timeframe for MVP.
The previous `4H` confirmation workflow is replaced with `6H`.

| Property | Old value | New value |
|---|---|---|
| Confirmation timeframe | `4H` | `6H` |
| ccxt fetch timeframe | `4h` | `6h` |
| Dataset naming | `..._4H_...` | `..._6H_...` |
| Config key | `method_4h` | `method_6h` |
| Resample fallback | from 1H | from 1H |

**Rationale:**
- Native `6H` is directly available from Coinbase REST API via `ccxt`.
- `6H` provides better structural alignment for the Jenkins framework confirmation logic.
- Operational decision recorded per change-control rule.

**Updated 6H policy:**
- Pull native 6H candles directly from Coinbase REST API (`ccxt` `fetch_ohlcv`, timeframe `6h`).
- If native 6H history is shallower than required, resample from 1H native pull.
- Do not mix native 6H and resampled 6H within the same official MVP experiment family.

**Dataset naming examples under new policy:**
- Raw: `cbrest_COINBASE_BTCUSD_6H_UTC_<pull-date>.csv`
- Processed: `proc_COINBASE_BTCUSD_6H_UTC_<pull-date>_v1`

**Prior experiments affected:**
The Phase 1B synthetic 4H dataset (`proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1`) was produced
before this decision and is retained as a historical artifact only.
It must not be used for official research under the new policy.
Any new confirmation-timeframe dataset must use the `6H` naming and `6h` ccxt timeframe.

---

### 2026-03-04 — M1 Resolution: official historical OHLCV acquisition method

**Superseded rule:**
> "The user's TradingView <-> Claude MCP bridge is an approved acquisition layer.
> MCP may be used to extract official raw historical candle datasets and metadata."

**Finding:**
`tradingview-mcp` provides only a single current-bar snapshot per symbol via
`coin_analysis`. It has no tool that returns N historical OHLCV bars as an array.
Bulk historical extraction via the MCP bridge is not possible with the current
server implementation. See `docs/data/mcp_extraction_runbook.md` §2 for full
discovery details. This invalidates Assumption 3 and Assumption 8 in `ASSUMPTIONS.md`.

**Decision: Official MVP historical OHLCV acquisition — Coinbase REST API via `ccxt`**

| Property | Value |
|---|---|
| Python library | `ccxt` |
| Exchange | `coinbase` (Coinbase Advanced Trade) |
| Symbol (ccxt format) | `BTC/USD` |
| Equivalent TradingView reference symbol | `COINBASE:BTCUSD` |
| API authentication required | No — public historical OHLCV endpoint |
| Timeframes available natively | `1d`, `6h`, `4h`, `1h`, `1w` and lower |
| UTC timestamp alignment | Native — Coinbase API returns UTC millisecond timestamps |
| Expected daily history depth | ~2015 to present |
| Expected 4H history depth | ~2017 to present |
| Expected 6H history depth | ~2017 to present |
| Cost | Free public API |

**Rationale:**
1. Coinbase is the canonical exchange for the project symbol (`COINBASE:BTCUSD`).
   The REST API is the direct upstream source of that TradingView data series.
2. The API is official, stable, publicly documented, and version-controlled by Coinbase.
3. `ccxt` provides a consistent Python interface, handles pagination automatically,
   normalises timestamps to UTC milliseconds, and is actively maintained.
4. No API key is required for reading public historical OHLCV candles.
5. History depth satisfies `data_spec.md §13` requirement of ≥ 10 years for daily.
6. Coinbase is a well-regulated US exchange; data quality and gap handling are known
   and documentable.

**Revised TradingView MCP bridge role:**
Retained for current-bar snapshot sanity checks only (`coin_analysis`).
Not used for bulk historical dataset production.

**Updated raw storage path (replaces previous policy in this file and `data_spec.md §16`):**
- Previous: `data/raw/tradingview_mcp/<symbol>/<timeframe>/`
- New: `data/raw/coinbase_rest/<symbol>/<timeframe>/`

**Updated raw dataset file-naming prefix (replaces `tvmcp_` prefix in `data_spec.md §17`):**
- Previous: `tvmcp_<symbol>_<timeframe>_<timezone>_<pull-date>`
- New: `cbrest_<symbol>_<timeframe>_<timezone>_<pull-date>`
- Example: `cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.csv`

**Processed dataset naming:** unchanged — `proc_<symbol>_<timeframe>_<timezone>_<source-date>_v<revision>`.

**Updated 4H policy (replaces "4H policy" section above; subsequently superseded by 6H policy — see 2026-03-05 change log):**
- Pull native 4H candles directly from Coinbase REST API (`ccxt` `fetch_ohlcv`, timeframe `4h`).
- If native 4H history is shallower than required, resample from 1H native pull.
- Do not mix native 4H and resampled 4H within the same official MVP experiment family.

**Prior experiments affected:** None — no official dataset pull had occurred before this decision.
