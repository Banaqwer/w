# Decisions - Jenkins Quant Project

This file records the project's frozen high-level decisions.

## Current approved decisions

### Environment
- Python is the official research, testing, and backtesting environment.
- TradingView is not the official source of truth for backtests or final research results.

### TradingView and MCP
- The user's TradingView <-> Claude MCP bridge is an approved acquisition layer.
- MCP may be used to extract official raw historical candle datasets and metadata.
- Official experiments must run on saved, normalized, versioned datasets after extraction.

### MVP market scope
- MVP market: BTC/USD
- Official TradingView symbol: `COINBASE:BTCUSD`
- Instrument type: Spot

### Time conventions
- Official timezone: UTC
- Official daily close: 00:00 UTC
- Official main research timeframe: Daily
- Official confirmation timeframe: 4H
- Official higher-structure timeframe: Weekly

### 4H policy
- Use direct native 4H extraction from the MCP bridge if available, stable, and historically complete enough for research.
- If direct 4H extraction is not reliable enough, use a documented Python resampling pipeline from a lower official base timeframe.
- Do not mix direct 4H and resampled 4H in the same MVP experiment family.

### Weekly policy
- Weekly bars must use a fixed UTC-based weekly boundary.
- Default interpretation: Monday 00:00 UTC to next Monday 00:00 UTC.

### Data storage
- Raw MCP exports are stored under `data/raw/tradingview_mcp/<symbol>/<timeframe>/`
- Processed research datasets are stored under `data/processed/<dataset_version>/`
- Extraction metadata is stored under `data/metadata/extractions/`

### Dataset naming
- Raw datasets: `tvmcp_<symbol>_<timeframe>_<timezone>_<pull-date>`
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
