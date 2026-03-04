# Data Specification - Jenkins Quant Project

## Purpose
This file defines the official data rules for the Jenkins quant MVP.

The goal is to prevent drift caused by:
- mixed data vendors
- inconsistent timestamps
- different daily closes
- inconsistent resampling
- silent missing-bar handling
- ad hoc live MCP queries being treated as official datasets

All research results must be generated from data that follows this specification.

## 1. Primary research universe

### Primary MVP market
- BTC/USD

### Official MVP TradingView symbol
- `COINBASE:BTCUSD`

### Primary research timeframe
- Daily

### Secondary execution / confirmation timeframe
- 4H

### Higher-structure validation timeframe
- Weekly

### Secondary validation markets after MVP
- EUR/USD
- SPY or ES
- Gold

Do not expand to secondary markets until the BTC/USD MVP stack is stable and documented.

## 2. Official source-of-truth rule

The official source of truth for data-driven outputs is the Python research environment operating on saved, validated datasets.

TradingView plus the user's MCP bridge may be used for:
- current-bar snapshot sanity checks (via `coin_analysis`)
- chart inspection
- visual validation and comparison to source charts
- optional later Pine Script translation

TradingView/MCP is not the official source of truth for:
- ad hoc signals
- backtests run directly from live bridge queries
- final ablation results
- final performance reports

## 3. Official MVP acquisition policy

For MVP, the approved acquisition method for bulk historical OHLCV data is the
**Coinbase REST API via the `ccxt` Python library**.

This replaces the previously stated "TradingView MCP bridge" bulk acquisition role.
The `tradingview-mcp` server does not provide bulk historical OHLCV arrays (see
`docs/data/mcp_extraction_runbook.md` §2 and `DECISIONS.md` 2026-03-04 change log).

**Official acquisition configuration:**
- Python library: `ccxt`
- Exchange: `coinbase` (Coinbase Advanced Trade)
- Symbol (ccxt format): `BTC/USD`
- Canonical TradingView reference symbol: `COINBASE:BTCUSD`
- Timeframes: `1d` (primary), `4h` (confirmation), `1h` (4H resampling base if needed)
- Weekly: Python resampling from `1d` processed dataset
- Timestamps: UTC, normalized at ingestion

**Retained TradingView MCP bridge role:**
- `coin_analysis` tool: current-bar snapshot for sanity checks
- Visual chart inspection and validation
- Not used for bulk historical data production

This means:
- official OHLCV history is acquired via `ccxt` + Coinbase REST API
- raw extracts are saved to `data/raw/coinbase_rest/<symbol>/<timeframe>/`
- official experiments must use saved raw extracts, not live API calls
- saved raw → normalized processed datasets → versioned dataset identifiers
- every extraction must have logged extraction metadata

### Official MVP acquisition definition
- Official acquisition library: `ccxt`
- Official exchange: `coinbase`
- Official chart reference symbol: `COINBASE:BTCUSD`
- Official market type: `Spot`
- If derivatives are later tested, they must be treated as separate experiments
- Continuous-contract method: `N/A for MVP`

## 4. Required fields

Every dataset used for the core system must include:
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

If a source export does not provide volume, document it clearly and mark the dataset accordingly.

## 5. Required derived fields

Every ingestion pipeline must derive and store:
- `bar_index`
- `calendar_day_index`
- `trading_day_index`
- `log_close`
- `hl_range`
- `true_range`
- `atr_n` for configured values
- resampled timeframe identifiers if applicable

These derived fields must be reproducible from the raw input.

## 6. Timezone convention

### Official MVP timezone
- UTC

Reason:
- crypto trades continuously
- UTC avoids ambiguous local-session handling
- UTC makes daily and intraday indexing easier to standardize

If the team later wants to test a New York or exchange-specific close, that must be treated as a separate experiment and documented explicitly.

### Required behavior
- all timestamps must be normalized to UTC at ingestion
- timezone conversion must happen before any resampling
- no mixed local timestamps are allowed inside the official research dataset

## 7. Daily bar-close convention

### Official MVP daily close
- 00:00 UTC bar boundary

This means the daily bar should represent one full UTC day.

No alternative daily close conventions may be mixed into MVP research.

If later experiments test a different daily close:
- they must be labeled separately
- they must not overwrite MVP results
- they must be documented in `DECISIONS.md`

## 8. Intraday bar convention

### Official 4H policy
Use direct native 4H extraction from the Coinbase REST API via `ccxt` if native 4H historical candles are available and complete enough for research use.

If native 4H extraction is not sufficiently deep or complete, the fallback is a documented Python resampling pipeline from the 1H native pull via `ccxt`.

Do not mix direct 4H and resampled 4H within the same official MVP experiment family.

### Official 4H convention
- 4H bars must align exactly to UTC boundaries
- no mixed intraday session definitions
- any resampling logic must be documented and reproducible

## 9. Weekly bar convention

### Official weekly convention
Weekly bars must use one fixed UTC-based resampling boundary from the official dataset.

Default interpretation:
- a weekly bar begins Monday 00:00 UTC and ends immediately before the next Monday 00:00 UTC

If the team chooses another fixed weekly boundary, it must be:
- documented
- kept consistent across all MVP experiments
- recorded in `DECISIONS.md`

## 10. Missing-bar policy

Missing bars must never be silently ignored.

### Required checks
At ingestion, validate:
- timestamp continuity
- duplicate timestamps
- missing bars
- out-of-order rows
- obviously corrupted OHLC relationships

### Required logging
If a missing or irregular bar is found, log:
- symbol
- timeframe
- missing timestamp(s)
- neighboring rows
- action taken

### MVP handling rule
- do not forward-fill OHLC bars
- do not invent synthetic bars unless explicitly running a labeled repair experiment
- if continuity breaks materially, fail validation and flag the dataset for review

This is especially important because time counts, row counts, and square-out logic are sensitive to continuity.

## 11. OHLC integrity rules

Every ingested bar must pass these checks:
- `low <= open <= high` or flagged
- `low <= close <= high` or flagged
- `high >= low`
- timestamp exists and is unique within the symbol/timeframe series

If any check fails:
- quarantine the row
- log the issue
- do not silently continue

## 12. Resampling rules

If resampling is performed in Python, the same rules must be used across the repo.

### Standard OHLCV aggregation
- open = first
- high = max
- low = min
- close = last
- volume = sum

### Required documentation
Every resampled dataset must record:
- source timeframe
- target timeframe
- timezone
- exact resampling boundary
- number of rows before and after

No ad hoc resampling is allowed in notebooks without recording the method.

## 13. Historical depth requirements

### Daily
- minimum 10 years of history where available
- more is preferred

### Weekly
- as much history as possible for long-structure validation

### 4H
- enough history to support meaningful confirmation testing after forecast zones are generated on daily data

If the chosen acquisition workflow cannot meet these thresholds, document the limitation.

## 14. Adjustment policy

### Crypto
- generally no corporate-action adjustment required
- still validate for obvious bad ticks or data corruption

### Equities
If equities are used later:
- define adjusted vs unadjusted policy explicitly
- keep the chosen policy fixed within each experiment
- do not compare adjusted and unadjusted results as if they were the same dataset

## 15. Symbol normalization policy

Every market used in the project must have a clearly defined canonical symbol.

### Current canonical symbols
- BTC/USD canonical symbol: `COINBASE:BTCUSD`
- EUR/USD canonical symbol: `TO DEFINE WHEN ADDED`
- SPY/ES canonical symbol: `TO DEFINE WHEN ADDED`
- Gold canonical symbol: `TO DEFINE WHEN ADDED`

Also document:
- spot vs futures vs CFD vs perpetual
- source exchange if relevant
- contract roll rules if applicable

## 16. Dataset storage policy

Raw Coinbase REST API exports must be stored under:

- `data/raw/coinbase_rest/<symbol>/<timeframe>/`

Validated processed research datasets must be stored under:

- `data/processed/<dataset_version>/`

Extraction metadata must be stored under:

- `data/metadata/extractions/`

Official backtests and validation reports may use only processed, versioned, validated datasets, not ad hoc live MCP queries.

## 17. Dataset version naming policy

Raw Coinbase REST extraction datasets must use this format:

- `cbrest_<symbol>_<timeframe>_<timezone>_<pull-date>`

Processed official research datasets must use this format:

- `proc_<symbol>_<timeframe>_<timezone>_<source-date>_v<revision>`

Examples:
- `cbrest_COINBASE_BTCUSD_1D_UTC_2026-03-04.csv`
- `cbrest_COINBASE_BTCUSD_4H_UTC_2026-03-04.csv`
- `proc_COINBASE_BTCUSD_1D_UTC_2026-03-04_v1`
- `proc_COINBASE_BTCUSD_4H_UTC_2026-03-04_v1`

Every experiment must reference the exact processed dataset version used.

## 18. Extraction metadata requirements

Every raw extraction must record:
- extraction timestamp
- canonical symbol (TradingView reference and acquisition-source symbol)
- timeframe
- timezone assumption
- bar count
- first bar timestamp
- last bar timestamp
- extraction method (e.g. `coinbase_rest_ccxt`)
- user/session note if relevant
- checksum or hash if possible

Metadata should be saved alongside the raw file or in `data/metadata/extractions/`.

## 19. Validation checklist before research use

A dataset is not approved for research until all items below are checked:

- [ ] official acquisition source is recorded
- [ ] symbol is recorded
- [ ] timezone normalized
- [ ] daily close convention confirmed
- [ ] duplicates checked
- [ ] missing bars checked
- [ ] OHLC integrity checked
- [ ] row count recorded
- [ ] resampling method documented
- [ ] derived indexes created
- [ ] dataset version saved
- [ ] extraction metadata saved

If any box is unchecked, the dataset is not approved for official experiments.

## 20. Experiment labeling rules

Every experiment run must label:
- market
- symbol
- timeframe(s)
- acquisition layer
- timezone
- bar-close convention
- dataset version
- resampling method
- module set used

This is mandatory so results can be compared honestly.

## 21. MVP defaults

Use these defaults unless a documented decision changes them:
- market: BTC/USD
- TradingView reference symbol: `COINBASE:BTCUSD`
- acquisition library: `ccxt`
- acquisition exchange: `coinbase`
- acquisition symbol (ccxt): `BTC/USD`
- timezone: UTC
- daily close: 00:00 UTC
- main timeframe: Daily
- execution timeframe: 4H (direct native pull from Coinbase REST)
- higher timeframe: Weekly (Python resampling from Daily)
- source-of-truth environment: Python
- TradingView MCP role: current-bar snapshot sanity checks only
- raw storage path: `data/raw/coinbase_rest/<symbol>/<timeframe>/`
- missing bars: detect, log, fail validation if material
- OHLC fill-forward: not allowed in official MVP dataset

## 22. Open fields to finalize before first run
Complete these before development begins:
- ~~the exact MCP extraction command/workflow~~ **RESOLVED** — Coinbase REST API via `ccxt` (see §3)
- ~~whether 4H is pulled directly in all cases or resampled in fallback conditions~~ **RESOLVED** — direct native 4H via `ccxt`; resample from 1H if depth insufficient (see §8)
- ~~data storage path implementation in the repo~~ **RESOLVED** — `data/raw/coinbase_rest/` (see §16)
- the first dataset version to use for MVP
- whether weekly is always resampled from daily or optionally pulled directly

Until these are filled, no experiment should be treated as official.
