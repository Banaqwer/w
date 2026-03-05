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
