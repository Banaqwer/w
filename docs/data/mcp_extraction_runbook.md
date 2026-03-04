# MCP Extraction Runbook — Jenkins Quant Project

**Status:** Phase 1 deliverable  
**Date produced:** 2026-03-04  
**Author:** Phase 1 Builder Agent

---

## Section 1 — Discovery Findings

### 1.1 MCP server identity

| Field | Value |
|---|---|
| Server name | `tradingview-mcp` |
| GitHub repository | `https://github.com/atilaahmettaner/tradingview-mcp` |
| Launch command (Claude Desktop config) | `uv tool run --from git+https://github.com/atilaahmettaner/tradingview-mcp.git tradingview-mcp` |
| Underlying libraries | `tradingview-ta` (TA_Handler, get_multiple_analysis), `tradingview-screener` (Query) |

### 1.2 Available tools

| Tool name | Parameters | Returns | Notes |
|---|---|---|---|
| `top_gainers` | `exchange`, `timeframe`, `limit` | list of symbol/changePercent/indicators dicts | Sorted highest → lowest % change |
| `top_losers` | `exchange`, `timeframe`, `limit` | list of symbol/changePercent/indicators dicts | Sorted lowest → highest % change |
| `bollinger_scan` | `exchange`, `timeframe`, `bbw_threshold`, `limit` | list of symbols with low Bollinger Band Width | Squeeze detection |
| `rating_filter` | `exchange`, `timeframe`, `rating`, `limit` | list of symbols matching a BB rating (-3 to +3) | Signal strength filter |
| `coin_analysis` | `symbol`, `exchange`, `timeframe` | dict with OHLC snapshot + indicators | **Primary tool for individual symbol lookup** |
| `consecutive_candles_scan` | `exchange`, `timeframe`, `min_candles`, `direction` | list of symbols with consecutive candle patterns | Pattern detection |
| `advanced_candle_pattern` | `exchange`, `timeframe`, `...` | list of multi-timeframe pattern results | Advanced pattern detection |
| `multi_changes` (internal helper) | `exchange`, `timeframes`, `base_timeframe`, `limit` | list of symbols with multi-TF change percentages | Multi-timeframe snapshot |
| `exchanges://list` | — | List of supported exchanges and markets | Resource endpoint |

### 1.3 Supported exchanges

Crypto: `KUCOIN`, `BINANCE`, `BYBIT`, `BITGET`, `OKX`, `COINBASE`, `GATEIO`, `HUOBI`, `BITFINEX`  
Traditional: `NASDAQ`, `NYSE`, `BIST`

### 1.4 Supported timeframes

`5m`, `15m`, `1h`, `4h`, `1D`, `1W`, `1M`

Note: the `tradingview-mcp` server uses `4h` (lowercase) while the project conventions
use `4H` (uppercase).  The ingestion layer must normalise timeframe strings before
storing filenames and metadata.

### 1.5 `coin_analysis` return payload

The primary tool for individual symbol data is `coin_analysis`.  It accepts:

```json
{
  "symbol": "BTCUSDT",
  "exchange": "COINBASE",
  "timeframe": "1D"
}
```

And returns a dict containing (as of 2026-03-04 source inspection):

```json
{
  "symbol": "COINBASE:BTCUSD",
  "exchange": "COINBASE",
  "timeframe": "1D",
  "open": 45000.0,
  "close": 46200.0,
  "high": 46800.0,
  "low": 44900.0,
  "volume": 12345678.0,
  "change_percent": 2.67,
  "rsi": 58.3,
  "macd": 123.4,
  "macd_signal": 110.2,
  "adx": 28.1,
  "sma20": 44000.0,
  "ema50": 43500.0,
  "ema200": 40000.0,
  "bb_upper": 48000.0,
  "bb_lower": 41000.0,
  "bb_width": 0.16,
  "stoch_k": 70.2,
  "stoch_d": 65.1,
  "bb_rating": 2,
  "recommendation": "BUY"
}
```

**Important:** `coin_analysis` returns a **single current/most-recent-bar snapshot**.
It does NOT return an array of historical OHLCV bars.

---

## Section 2 — Critical Limitation: No Bulk Historical OHLCV Export

**This is the primary open issue for Phase 1 data acquisition.**

The `tradingview-mcp` server does **not** provide a tool that returns N historical
OHLCV bars as an array.  All available tools return either:
- A single current-bar snapshot per symbol (`coin_analysis`)
- A ranked list of symbols with current indicators (`top_gainers`, `top_losers`, etc.)

For bulk historical candle extraction — which is required for backtesting,
coordinate-system construction, and all Phase 2+ modules — a different acquisition
strategy must be used.

### 2.1 Alternatives for historical data acquisition

| Option | Description | Pros | Cons |
|---|---|---|---|
| **A. `tvdatafeed` Python library** | Open-source library that wraps TradingView's internal API to extract historical OHLCV bars | Provides full OHLCV arrays; supports all TF; free; well-maintained | Unofficial API; may break on TradingView updates; requires authentication |
| **B. `yfinance`** | Yahoo Finance Python library for OHLCV history | Free; stable; wide coverage | Not COINBASE:BTCUSD specifically; must validate against TradingView |
| **C. Binance/Coinbase public REST API** | Direct REST calls for BTC/USD OHLCV history | Official; stable; free; full history | Not TradingView-sourced; symbol semantics differ slightly |
| **D. Manual CSV export from TradingView** | User exports a CSV from TradingView chart directly | Exact TradingView data | Manual step; not automated; no MCP integration |
| **E. Extended MCP bridge** | Build or extend the MCP server to expose historical candles using `tvdatafeed` or similar | Maintains MCP-based workflow | Additional development; non-trivial; server changes needed |

### 2.2 Recommended path for Phase 1

**Option C (Coinbase REST API) as primary + visual spot-check against TradingView** is
the most pragmatic choice for immediate forward progress:

1. Pull `COINBASE:BTCUSD` daily OHLCV from the Coinbase REST API (or Binance as fallback)
2. Run through the ingestion pipeline to produce a versioned processed dataset
3. Spot-check at least 20 reference bars against TradingView daily chart for consistency
4. Record any discrepancies in `DECISIONS.md` before using the dataset for research

This recommendation must be reviewed and approved (or overridden) before the first
official pull.  Record the decision in `DECISIONS.md`.

### 2.3 Impact on Assumption 8

Assumption 8 (direct native 4H extraction from `tradingview-mcp`) is **invalidated
by this discovery**.  The MCP server does not provide bulk historical 4H arrays.
Assumption 8 must be updated in `ASSUMPTIONS.md` once the actual acquisition method
is confirmed.

---

## Section 3 — Extraction Workflow (Updated for Actual Capabilities)

The following workflow describes how to use `coin_analysis` for **current-bar
snapshot** use cases (e.g. visual sanity checks, live monitoring) and a separate
path for **historical OHLCV acquisition**.

### 3.1 Current-bar snapshot via `coin_analysis`

Use case: confirm that TradingView and the data source agree on current price/indicators.

```
Step 1 — Call coin_analysis
  Input:  symbol = "BTCUSD", exchange = "COINBASE", timeframe = "1D"
  Output: dict with OHLC snapshot + indicators for the most recent bar

Step 2 — Compare against stored processed dataset
  Check that close, high, low for the current bar match within acceptable tolerance

Step 3 — Log any material discrepancy
  Write to data/metadata/extractions/<date>_sanity_check.json
```

### 3.2 Historical OHLCV acquisition workflow

The specific tool/library used here depends on the acquisition method approved in
`DECISIONS.md`.  The **interface contract** is unchanged regardless of source:

```
Step 1 — Pull raw OHLCV array
  Required fields: timestamp (UTC), open, high, low, close, volume
  Symbol:    BTC/USD via ccxt (= COINBASE:BTCUSD on TradingView)
  Timeframe: 1D (primary), 4H (confirmation), 1W (structural via resample)
  Start:     earliest available (target ≥ 10 years)
  End:       current date

Step 2 — Save raw file
  Path: data/raw/coinbase_rest/COINBASE_BTCUSD/<TF>/
        cbrest_COINBASE_BTCUSD_<TF>_UTC_<pull-date>.csv

Step 3 — Write extraction metadata JSON
  Path: data/metadata/extractions/
        cbrest_COINBASE_BTCUSD_<TF>_UTC_<pull-date>.json
  Required fields: see data_spec.md §18

Step 4 — Run validation (data/validation.py)
  If any check fails: write FAILED report; halt; do not produce processed dataset

Step 5 — Run ingestion pipeline (data/ingestion.py)
  Computes all derived fields; writes processed Parquet + manifest

Step 6 — Record dataset version in configs/default.yaml
  dataset.current_version = "proc_COINBASE_BTCUSD_1D_UTC_<date>_v1"
```

### 3.3 MCP `coin_analysis` call syntax for sanity checks

```python
# Via Claude Desktop or direct MCP call:
result = await mcp_client.call_tool(
    "coin_analysis",
    {
        "symbol": "BTCUSD",
        "exchange": "COINBASE",
        "timeframe": "1D"
    }
)
# Returns: dict with open, high, low, close, volume for most recent bar
```

---

## Section 4 — Symbol and Timeframe Conventions

### 4.1 Symbol format

The MCP server accepts symbol strings without exchange prefix when exchange is
specified separately:
- ✓ `symbol="BTCUSD", exchange="COINBASE"` → internally becomes `"COINBASE:BTCUSD"`
- ✓ `symbol="COINBASE:BTCUSD"` → passed through as-is

In file paths, the colon is replaced with underscore: `COINBASE_BTCUSD`.

### 4.2 Timeframe normalisation

| Project convention | MCP server format | Notes |
|---|---|---|
| `1D` | `1D` | Matches |
| `4H` | `4h` | Case difference — normalise to project convention at ingestion |
| `1W` | `1W` | Matches |
| `1h` | `1h` | Matches |

### 4.3 Exchange identifier

Use `COINBASE` (uppercase) for all MVP extractions.

---

## Section 5 — Required MCP Server Configuration

To use `tradingview-mcp` with Claude Desktop, add to the config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "tradingview-mcp": {
      "command": "uv",
      "args": [
        "tool", "run", "--from",
        "git+https://github.com/atilaahmettaner/tradingview-mcp.git",
        "tradingview-mcp"
      ]
    }
  }
}
```

Restart Claude Desktop after adding this configuration.

---

## Section 6 — Open Issues

| ID | Issue | Impact | Status |
|---|---|---|---|
| **M1** | `tradingview-mcp` has no bulk historical OHLCV tool | ~~Critical — blocks first official dataset~~ | **RESOLVED 2026-03-04** — Official method: Coinbase REST API via `ccxt`. See `DECISIONS.md` 2026-03-04 change log. |
| **M2** | Assumption 8 (direct 4H pull) is invalidated | ~~High — affects 4H acquisition policy~~ | **RESOLVED 2026-03-04** — `ASSUMPTIONS.md` Assumption 8 invalidated; Assumption 16 added. 4H via Coinbase REST `ccxt`. |
| **M3** | `coin_analysis` symbol format: "BTCUSD" vs "BTCUSDT" | Medium — symbol mismatch risk | **RESOLVED 2026-03-04** — `ccxt` Coinbase symbol is `BTC/USD`; confirmed equivalent to `COINBASE:BTCUSD`. For MCP snapshot use: `symbol="BTCUSD", exchange="COINBASE"`. |
| **M4** | TradingView rate limiting | Low (MCP now sanity-check only) | Monitor if `coin_analysis` calls are throttled during spot checks; use conservative delay intervals. |
| **M5** | First official dataset version string not yet committed to config | Low — blocks dataset production | Set `dataset.current_version` in `configs/default.yaml` after first pull. |

---

## Section 7 — Checklist Before First Official Dataset Pull

- [x] Acquisition method selected and recorded in `DECISIONS.md` (resolves M1)
- [x] Assumption 8 updated in `ASSUMPTIONS.md`; Assumption 16 added (resolves M2)
- [x] Symbol string confirmed for chosen acquisition source: `BTC/USD` via `ccxt` Coinbase (resolves M3)
- [ ] `configs/default.yaml` `dataset.current_version` set to final version string after pull
- [ ] `data/raw/coinbase_rest/COINBASE_BTCUSD/1D/` directory created on first pull
- [ ] `data/metadata/extractions/` directory exists
- [x] Ingestion pipeline tested with synthetic data (done — see `tests/test_ingestion.py`)
- [x] Validation checks confirmed working (done — see `tests/test_validation.py`)
- [ ] `ccxt` installed (`pip install ccxt`) in project environment
- [ ] First official daily raw pull executed: `cbrest_COINBASE_BTCUSD_1D_UTC_<date>.csv`
- [ ] ≥ 20 bars spot-checked against TradingView `COINBASE:BTCUSD` daily chart
- [ ] Any discrepancies > 0.1% logged in `DECISIONS.md`

---

## Section 8 — References

- `docs/data/data_spec.md` — §16–18 (storage, naming, metadata requirements)
- `DECISIONS.md` — data storage policy and 4H/weekly acquisition policy
- `ASSUMPTIONS.md` — Assumptions 8–9 (4H and weekly acquisition)
- `docs/phase0_builder_output.md` — Section 4 (MCP extraction workflow skeleton)
- `https://github.com/atilaahmettaner/tradingview-mcp` — MCP server source
