# Phase 0 Builder Output — Revised
## Jenkins Quant Project · Builder Agent · 2026-03-03

---

## Section 1 — Revised Architecture Confirmation

### Project identity
A research-grade, modular quant framework that formalizes Michael S. Jenkins'
*The Secret Science of the Stock Market* into independently testable, reproducible
Python components. This is not a charting assistant, a generic TA bot, or a
discretionary workflow.

### Core pipeline (locked sequence)
```
Raw OHLCV data (via TradingView MCP bridge)
  ↓
Ingestion + validation + normalization → versioned processed datasets
  ↓
Structural pivot/impulse detection (multiple origin-selection methods)
  ↓
Time-price transform modules
  (measured move · adjusted angles · JTTL · sqrt levels · time-count · log levels)
  ↓
Confluence scoring (per-bar + zone merge)
  ↓
Forecast zone construction
  ↓
Market confirmation gate
  ↓
Execution + risk logic (stop / target / trail)
  ↓
Backtest / ablation / walk-forward validation
```

### Environment hierarchy (from CLAUDE.md §Official environment)
| Layer | Approved role |
|---|---|
| Python | Official research, feature generation, backtesting, reporting |
| TradingView MCP bridge | Approved raw data acquisition + visual sanity check |
| TradingView / Pine Script | Optional translation only; not source of truth |

### MVP market and data conventions (all locked in DECISIONS.md)
| Parameter | Value |
|---|---|
| Market | BTC/USD |
| Symbol | `COINBASE:BTCUSD` |
| Instrument | Spot |
| Timezone | UTC |
| Daily close | 00:00 UTC bar boundary |
| Primary TF | Daily |
| Confirmation TF | 4H |
| Structural TF | Weekly |
| Weekly boundary | Monday 00:00 UTC → next Monday 00:00 UTC |
| Missing bar policy | Detect, log, fail validation if material |
| OHLC fill-forward | Prohibited in official MVP dataset |

### Core object interfaces (from CLAUDE.md + blueprint)
**`Impulse`**
```python
origin_time, origin_price, extreme_time, extreme_price,
delta_t, delta_p, slope_raw, slope_log,
quality_score, detector_name
```

**`Projection`**
```python
module_name, impulse_id,
projected_time, projected_price,
time_band, price_band,
direction_hint, raw_score
```

**`ForecastZone`**
```python
zone_start, zone_end,
price_low, price_high,
support_score, resistance_score, turn_score, combined_score,
modules_hit
```

**`TradeSignal`**
```python
side, entry_time, entry_price, stop_price, target_price,
confluence_score, confirmation_type
```

### Data storage conventions (from DECISIONS.md + data_spec.md §16–17)
File-path sanitization rule: the colon in `COINBASE:BTCUSD` is replaced with
an underscore in all storage paths, consistent with the naming examples already
present in data_spec.md §17. `COINBASE:BTCUSD` → `COINBASE_BTCUSD` in paths.

```
data/raw/tradingview_mcp/COINBASE_BTCUSD/<timeframe>/
  tvmcp_COINBASE_BTCUSD_1D_UTC_<pull-date>.csv (or .parquet)
  tvmcp_COINBASE_BTCUSD_4H_UTC_<pull-date>.csv
  tvmcp_COINBASE_BTCUSD_1W_UTC_<pull-date>.csv

data/processed/<dataset_version>/
  proc_COINBASE_BTCUSD_1D_UTC_<source-date>_v1.parquet
  proc_COINBASE_BTCUSD_4H_UTC_<source-date>_v1.parquet
  proc_COINBASE_BTCUSD_1W_UTC_<source-date>_v1.parquet

data/metadata/extractions/
  tvmcp_COINBASE_BTCUSD_1D_UTC_<pull-date>.json
  (one JSON sidecar per raw extraction; see Section 4 for required fields)
```

### Module map (from blueprint, with explicit additions noted in Section 5)
```
core/
  pivots.py               — multiple pivot/origin detection methods
  impulses.py             — impulse extraction + quality scoring
  coordinate_system.py    — [ADDITION — see Section 5 and Section 8]

data/
  ingestion.py            — MCP extraction → raw → metadata → processed pipeline
  validation.py           — OHLC integrity + timestamp continuity checks
  loader.py               — load raw/processed datasets by version

configs/
  default.yaml            — [ADDITION — see Section 5 and Section 7]

modules/
  measured_move.py
  adjusted_angles.py
  jttl.py
  sqrt_levels.py
  time_counts.py
  log_levels.py

signals/
  confluence.py
  confirmation.py

backtest/
  engine.py

research/
  ablation.py
  walkforward.py

reports/
tests/
```

### AI team roles (from ai_team_operating_protocol.md)
| Agent | Model | Scope |
|---|---|---|
| Builder | Sonnet 4.x | Phase-by-phase implementation |
| Reviewer | Sonnet 4.x | Returns pass / revise / reject per phase |
| Auditor | Opus 4.x | Milestone gate decisions only |

---

## Section 2 — Corrected Implementation Order

### Phase sequence
```
Phase 0  (now)   — Alignment. This document.
Phase 1          — Repo skeleton · config · data loaders · coordinate system · validation
Phase 2          — Structural pivot + impulse engine (multiple origin methods)
Phase 3          — MVP projection stack
                   (measured move · adjusted angles · JTTL · sqrt levels · time-count · log)
Phase 4          — Confluence engine + forecast-zone builder
Phase 5          — Confirmation logic + execution + risk layer
Phase 6          — Backtest engine + ablation + walk-forward + first research report
Phase 7          — Advanced modules (arcs · boxes · Pythagorean · music ratios)
```

### Phase 1 file creation order (proposed)
Order is driven by dependency: config must exist before data code runs;
validation must exist before ingestion calls it; coordinate system must
exist before ingestion stores derived fields.

```
1. pyproject.toml + package __init__ files    — project plumbing
2. configs/default.yaml                        — all data + module defaults
3. data/validation.py                          — OHLC + continuity checks
4. core/coordinate_system.py                   — index derivation + derived fields
5. data/ingestion.py                           — MCP → raw → validate → derive → processed
6. data/loader.py                              — load by version/symbol/TF
7. tests/test_validation.py                    — maps to data_spec.md §10–12
8. tests/test_ingestion.py                     — end-to-end ingestion with synthetic data
```

### Derived fields stored into processed datasets (data_spec.md §5)
The ingestion pipeline **derives and stores** all of the following into every
processed dataset before it is approved for research use:

| Field | Source / formula |
|---|---|
| `bar_index` | Sequential integer from epoch anchor (see Section 8) |
| `calendar_day_index` | Integer count of UTC calendar days from epoch |
| `trading_day_index` | Integer count of non-gap bars from epoch (crypto: same as bar_index unless gaps exist) |
| `log_close` | `log(close)` using natural log |
| `hl_range` | `high - low` |
| `true_range` | `max(high-low, abs(high-prev_close), abs(low-prev_close))` |
| `atr_n` | Rolling mean of true_range over configured window(s) |

All derived fields must be reproducible from raw OHLCV input.
No derived field is invented; all are computed deterministically.

---

## Section 3 — Corrected Ambiguities and Real Blockers

### Resolved — not open
| Item | Resolution |
|---|---|
| Symbol/path sanitization (formerly A4) | **Closed.** data_spec.md §17 naming examples already use underscore (`COINBASE_BTCUSD`). Apply that rule consistently. |
| Whether bar_index / calendar_day_index / trading_day_index are separate (formerly A7) | **Closed.** They are clearly separate concepts. See Section 8 for the remaining open question: anchoring and computation rules for 24/7 crypto. |
| Repo root layout (formerly A9) | **Closed.** Current layout is canonical. Root-level control files and docs/ stay as-is. Phase 1 code directories added alongside existing structure. |
| MCP server identity (formerly A1 partial) | **Closed.** Server name: `tradingview-mcp`. Launch: `uv tool run --from git+https://github.com/atilaahmettaner/tradingview-mcp.git tradingview-mcp`. |

### Remaining open items — must resolve before Phase 1 begins

**B1 — Exact MCP tool/function names and parameter schema**
The server identity is known but the specific tool call names (e.g. the function
to invoke for candle extraction), the required parameters, and the exact return
payload format are not yet documented. The workflow skeleton in Section 4 designs
around this gap using an interface contract. A discovery step is required at the
start of Phase 1 to fill in the concrete tool call details.

**B2 — 4H acquisition method: direct pull or resample**
Currently a provisional assumption (see Section 6). Must be confirmed by testing
whether the MCP bridge returns reliable native 4H candles for `COINBASE:BTCUSD`
with sufficient history. This test should happen early in Phase 1.

**B3 — First official dataset version identifier**
The version string (e.g. `proc_COINBASE_BTCUSD_1D_UTC_2026-03-03_v1`) must be
agreed before the first official processed dataset is written. A provisional
default is proposed in Section 7 and Section 6.

### Lower-priority items — can defer to the relevant phase

| Item | Phase |
|---|---|
| JTTL exact root-transform formula | Phase 3 |
| Adjusted-angle family exact fractional divisions | Phase 3 |
| Confluence scoring weights | Phase 4 |
| Confirmation gate trigger conditions | Phase 5 |
| Baseline comparison strategy implementations | Phase 6 |
| Origin quality scoring metric | Phase 2 |

---

## Section 4 — MCP Extraction Workflow Skeleton

### Interface contract
The exact MCP tool/function names are not yet known. This section defines the
**workflow steps and interface contract** that the ingestion layer must implement
regardless of the final tool call names.

The registered server is `tradingview-mcp`.
Launch: `uv tool run --from git+https://github.com/atilaahmettaner/tradingview-mcp.git tradingview-mcp`

### Step 1 — Discovery (Phase 1 first task)
Before writing ingestion code, call the MCP server's tool-listing endpoint to
enumerate available tool names, parameter schemas, and return formats.
Document the results in `docs/data/mcp_extraction_runbook.md`.
This runbook is a **Phase 1 deliverable**.

### Step 2 — Extraction call (interface contract)
The extraction call must accept:
```
symbol:    COINBASE:BTCUSD
timeframe: 1D | 4H | 1W
start:     ISO-8601 UTC date string
end:       ISO-8601 UTC date string (or "now")
timezone:  UTC
```

The extraction call must return OHLCV bars in one of:
- JSON array of objects with keys: timestamp, open, high, low, close, volume
- CSV with header row containing those column names
- Any other structured format that maps unambiguously to those fields

If the return format differs, the ingestion layer is responsible for
normalization before writing raw files.

### Step 3 — Raw file save
Immediately after extraction, write the raw output to:
```
data/raw/tradingview_mcp/COINBASE_BTCUSD/<timeframe>/
  tvmcp_COINBASE_BTCUSD_<TF>_UTC_<pull-date>.<ext>
```
- `<TF>` examples: `1D`, `4H`, `1W`
- `<pull-date>`: ISO date of extraction, e.g. `2026-03-03`
- `<ext>`: `.csv` or `.parquet` depending on source format

Do not modify the raw file after writing. It is the unmodified source record.

### Step 4 — Extraction metadata save
Immediately after raw save, write a JSON metadata sidecar to:
```
data/metadata/extractions/
  tvmcp_COINBASE_BTCUSD_<TF>_UTC_<pull-date>.json
```

Required metadata fields (from data_spec.md §18):
```json
{
  "extraction_timestamp": "ISO-8601 UTC datetime of pull",
  "tradingview_symbol": "COINBASE:BTCUSD",
  "timeframe": "1D",
  "timezone_assumption": "UTC",
  "bar_count": 3650,
  "first_bar_timestamp": "ISO-8601",
  "last_bar_timestamp": "ISO-8601",
  "extraction_method": "tradingview-mcp uv tool run",
  "mcp_server": "tradingview-mcp",
  "mcp_tool_name": "<to fill after discovery>",
  "raw_file_path": "data/raw/tradingview_mcp/...",
  "checksum_sha256": "<sha256 of raw file>",
  "user_note": ""
}
```

### Step 5 — Immediate post-extraction validation
Before producing processed datasets, run `data/validation.py` against the raw file.

Required checks (from data_spec.md §10–12):
- timestamp uniqueness
- timestamp continuity (expected bar count vs actual)
- out-of-order row detection
- OHLC integrity: `low <= open <= high`, `low <= close <= high`, `high >= low`
- volume presence (flag if missing, do not fail)
- no future timestamps relative to extraction date

If any check fails, write a validation failure report to:
```
data/metadata/extractions/tvmcp_COINBASE_BTCUSD_<TF>_UTC_<pull-date>_FAILED.json
```
and raise an exception. Do not continue to Step 6.

### Step 6 — Processed dataset production
If validation passes:
1. normalize timestamps to UTC `datetime64[ns]`
2. compute all derived fields (see Section 2, derived fields table)
3. write processed dataset to:
   ```
   data/processed/proc_COINBASE_BTCUSD_<TF>_UTC_<source-date>_v<N>/
     proc_COINBASE_BTCUSD_<TF>_UTC_<source-date>_v<N>.parquet
   ```
4. write a dataset version manifest alongside:
   ```json
   {
     "dataset_version": "proc_COINBASE_BTCUSD_1D_UTC_2026-03-03_v1",
     "source_raw_file": "tvmcp_COINBASE_BTCUSD_1D_UTC_2026-03-03.csv",
     "source_metadata": "tvmcp_COINBASE_BTCUSD_1D_UTC_2026-03-03.json",
     "validation_passed": true,
     "row_count_raw": 3650,
     "row_count_processed": 3650,
     "derived_fields": ["bar_index", "calendar_day_index", "trading_day_index",
                         "log_close", "hl_range", "true_range", "atr_14"],
     "coordinate_system_version": "v1",
     "produced_at": "ISO-8601 UTC"
   }
   ```

### Step 7 — Research handoff
A dataset is approved for research use only when:
- raw file exists
- metadata JSON exists
- validation passed
- processed dataset and manifest exist
- all derived fields are present and non-null (except documented gaps)

Official experiments reference the processed dataset version string, not the raw file.

---

## Section 5 — Repo Structure Check, Including Explicit Additions

### Current state of `/home/user/w/` (the git repo root)
```
/home/user/w/
├── .git/
├── jenkins_repo_docs_final/        ← project root (control files + docs)
│   ├── CLAUDE.md                   ← master instructions (source-of-truth priority 1)
│   ├── README.md
│   ├── PROJECT_STATUS.md
│   ├── DECISIONS.md
│   ├── ASSUMPTIONS.md
│   ├── docs/
│   │   ├── ai/ai_team_operating_protocol.md
│   │   ├── data/data_spec.md
│   │   ├── handoff/                (prd · blueprint · task_breakdown)
│   │   └── prompts/                (phase0+1 builder/reviewer/auditor)
│   └── references/
│       ├── notes/                  (chapter notes · origin notes · jttl notes)
│       └── pdfs/                   (source book)
├── secretScienceofStockMarket 66 (1).pdf   ← duplicate PDFs (not in docs tree)
├── secretScienceofStockMarket 66.pdf
└── secretScienceofStockMarket_text (1) - hh.pdf
```

**Assessment:** Documentation layer is complete and internally consistent.
Code layer is absent — correct for Phase 0. No structural changes to docs
are needed before Phase 1.

### Phase 1 additions (code directories created at project root)
All Phase 1 code directories are created inside `jenkins_repo_docs_final/`
alongside the existing `docs/` and `references/` folders, consistent with A9.

```
jenkins_repo_docs_final/
├── [existing docs as above]
│
├── configs/               ← ADDITION (see justification below)
│   └── default.yaml
│
├── core/                  ← from blueprint
│   ├── __init__.py
│   ├── pivots.py          (Phase 2)
│   ├── impulses.py        (Phase 2)
│   └── coordinate_system.py   ← ADDITION (see justification below)
│
├── data/                  ← from blueprint
│   ├── __init__.py
│   ├── ingestion.py
│   ├── validation.py
│   └── loader.py
│
├── modules/               ← from blueprint (populated Phase 3)
│   └── __init__.py
│
├── signals/               ← from blueprint (populated Phase 4–5)
│   └── __init__.py
│
├── backtest/              ← from blueprint (populated Phase 6)
│   └── __init__.py
│
├── research/              ← from blueprint (populated Phase 6)
│   └── __init__.py
│
├── reports/               ← from blueprint
├── tests/                 ← from blueprint
│   ├── __init__.py
│   ├── test_validation.py
│   └── test_ingestion.py
│
└── pyproject.toml         ← ADDITION (see Section 9)
```

### Explicit additions and justifications

**`configs/`** — Not in the original blueprint module list, but required from
CLAUDE.md §Required MVP module stack and the data_spec.md's requirement for
versioned, reproducible experiments. Every module and data pipeline needs a
common config to set symbol, timeframe, paths, module toggles, and ATR windows.
Without a config layer, reproducing any experiment requires reading scattered
hardcoded values. This aligns directly with CLAUDE.md Rule 6 (reproducibility).

**`core/coordinate_system.py`** — Not listed as a separate file in the blueprint,
but CLAUDE.md §Phase 1 deliverables explicitly includes "coordinate system" as a
Phase 1 deliverable, and data_spec.md §5 requires `bar_index`, `calendar_day_index`,
and `trading_day_index` in every processed dataset. The derivation logic for these
indices (anchor epoch, 24/7 crypto gap handling, bar counting) belongs in one
canonical, tested location rather than duplicated inside each module. Placing it
in `core/` makes it available to pivot detection, impulse extraction, and every
projection module.

**`pyproject.toml`** — See Section 9.

---

## Section 6 — ASSUMPTIONS.md Provisional Entries to Add

The following entries must be appended to `ASSUMPTIONS.md` before Phase 1
begins. Each is provisional, logged explicitly, and will be re-evaluated when
empirical data is available.

---

### Assumption 8 — 4H acquisition method (provisional)
**Date:** 2026-03-03
**Assumption:** Assume direct native 4H candle extraction from the `tradingview-mcp`
bridge is available and sufficiently complete for `COINBASE:BTCUSD`. Use direct
pull for Phase 1 ingestion.
**Reason:** DECISIONS.md states to prefer direct extraction if reliable. Before
testing, direct pull is the optimistic default.
**What it approximates:** Full native 4H history from TradingView.
**How it will be tested:** In Phase 1, pull 4H data and check bar count, coverage
depth, and continuity against expectations. If gaps or shallow history are found,
switch to documented Python resampling from 1H or lower and record the change in
DECISIONS.md.
**Status:** Provisional. Will be confirmed or overridden early in Phase 1.

---

### Assumption 9 — Weekly data source (provisional)
**Date:** 2026-03-03
**Assumption:** Weekly bars will be produced by Python resampling from the official
daily processed dataset, not by a separate direct weekly pull.
**Reason:** Daily is the primary research timeframe and will be validated first.
Resampling weekly from daily is deterministic, reproducible, and avoids a second
extraction dependency. Direct weekly pull can be added later if needed.
**What it approximates:** Native weekly candles from TradingView.
**How it will be tested:** Visual and numeric spot-check against TradingView weekly
chart for at least 10 reference bars.
**Status:** Provisional. Can be changed in DECISIONS.md if direct weekly pull
proves superior.

---

### Assumption 10 — ATR default window
**Date:** 2026-03-03
**Assumption:** Default ATR window is 14 bars. The derived field stored in all
processed daily datasets is `atr_14`. Additional windows can be added via config.
**Reason:** ATR(14) is the conventional default and widely used as a structural
range reference. No project document specifies a different window.
**What it approximates:** A generic volatility measure; the project may later
define custom windows tied to impulse length.
**How it will be tested:** Compared against TradingView ATR(14) on daily chart
for sanity check during Phase 1 validation.
**Status:** Provisional. Config-driven; can be changed without breaking anything.

---

### Assumption 11 — `trading_day_index` for 24/7 crypto (provisional)
**Date:** 2026-03-03
**Assumption:** For BTC/USD (a 24/7 continuous market), `trading_day_index` is
computed as the zero-based sequential bar count from the epoch anchor, identical
to `bar_index` for daily bars with no gaps. If gaps exist (missing bars), the
`trading_day_index` increments only for bars that are present, preserving the
"count of trading bars observed" semantic. It does NOT skip integers for missing bars.
**Reason:** Crypto has no exchange-closed days, so there is no traditional
"non-trading day" concept. The index tracks observed bars.
**What it approximates:** Traditional trading-day count used in equities.
**How it will be tested:** Compared with calendar_day_index on a known date range
to confirm they diverge correctly when/if gaps exist.
**Status:** Provisional. May be revised once gap behavior is analyzed on real data.

---

### Assumption 12 — `bar_index` and `calendar_day_index` anchor epoch (provisional)
**Date:** 2026-03-03
**Assumption:** Both `bar_index` and `calendar_day_index` are zero-based, anchored
to the **first bar present in the raw dataset** (the earliest available timestamp).
**Reason:** Anchoring to a fixed external epoch (e.g. Unix epoch 1970-01-01)
would produce large, fragile integers. Anchoring to dataset start keeps values
small and reproducible from any consistent dataset version.
**What it approximates:** A stable, dataset-relative coordinate system.
**How it will be tested:** Confirmed by checking that `bar_index == 0` at the
first row and increments by 1 per bar, and that `calendar_day_index` matches the
elapsed UTC calendar days from row 0.
**Status:** Provisional. Epoch rule is dataset-relative; must be stored in the
dataset manifest to allow cross-dataset comparisons.

---

## Section 7 — Proposed `configs/default.yaml` Schema

```yaml
# configs/default.yaml
# All experiments must reference a config. Do not hardcode these values.

# ── Market and symbol ──────────────────────────────────────────────────────
market:
  name: "BTC/USD"
  source: "COINBASE"                    # exchange/venue
  symbol_tv: "COINBASE:BTCUSD"          # TradingView symbol (for MCP calls)
  symbol_path: "COINBASE_BTCUSD"        # sanitized for file paths (colon → underscore)
  instrument_type: "spot"

# ── Timeframes ────────────────────────────────────────────────────────────
timeframes:
  primary: "1D"                         # Daily — main research TF
  confirmation: "4H"                    # 4H — confirmation and execution TF
  structural: "1W"                      # Weekly — higher-structure validation

# ── Time conventions ──────────────────────────────────────────────────────
timezone: "UTC"
daily_close_convention: "00:00 UTC"     # bar boundary; one UTC calendar day
weekly_boundary: "Monday 00:00 UTC"     # weekly bar start

# ── Storage paths ────────────────────────────────────────────────────────
paths:
  raw: "data/raw/tradingview_mcp"
  processed: "data/processed"
  metadata: "data/metadata/extractions"
  reports: "reports"
  logs: "logs"

# ── Dataset version ──────────────────────────────────────────────────────
dataset:
  current_version: "proc_COINBASE_BTCUSD_1D_UTC_2026-03-03_v1"
  # Update this when a new processed dataset is approved

# ── Data acquisition ────────────────────────────────────────────────────
acquisition:
  mcp_server: "tradingview-mcp"
  method_4h: "direct"                   # "direct" or "resample_from_1H"
  method_weekly: "resample_from_1D"     # "direct" or "resample_from_1D"

# ── Derived fields ───────────────────────────────────────────────────────
derived_fields:
  atr_windows: [14]                     # ATR window(s); atr_14 computed by default
  atr_warmup_rows: 14                   # rows dropped from head before ATR is considered valid
  log_close: true
  true_range: true
  hl_range: true
  bar_index: true
  calendar_day_index: true
  trading_day_index: true

# ── Coordinate system ────────────────────────────────────────────────────
coordinate_system:
  bar_index_epoch: "first_bar"          # anchor to first bar in dataset
  calendar_day_epoch: "first_bar"

# ── Validation settings ──────────────────────────────────────────────────
validation:
  require_volume: false                 # flag if missing but do not fail
  fail_on_ohlc_violation: true
  fail_on_duplicate_timestamp: true
  fail_on_missing_bar: true            # fail if continuity break is material
  max_allowed_missing_bars: 0          # 0 = strict; raise this only with documented justification
  fail_on_future_timestamp: true

# ── Module toggles ───────────────────────────────────────────────────────
modules:
  measured_move: true
  adjusted_angles: true
  jttl: true
  sqrt_levels: true
  time_counts: true
  log_levels: true
  arcs: false                           # advanced; off until MVP validated
  boxes: false
  pythagorean_ratios: false
  music_ratios: false
  direct_weekly_pull: false             # RESERVED — not used under current MVP Assumption 9

# ── Research defaults ────────────────────────────────────────────────────
research:
  min_history_years_daily: 10
  random_seed: 42
```

---

## Section 8 — Proposed `core/coordinate_system.py` Design

### Purpose
Provides a single, canonical location for all index and derived-field computations
that are required in every processed dataset. Centralizing this prevents
inconsistent implementations across modules.

### What it computes
| Field | Type | Unit | Formula |
|---|---|---|---|
| `bar_index` | int | bars | `0, 1, 2, …` from first bar in dataset |
| `calendar_day_index` | int | UTC calendar days | `(timestamp - timestamp[0]).days` |
| `trading_day_index` | int | observed bars | cumulative count of non-null bars from row 0 (for 24/7 crypto: equals `bar_index` unless gaps exist) |
| `log_close` | float | log price units | `ln(close)` |
| `hl_range` | float | price units | `high - low` |
| `true_range` | float | price units | `max(H-L, |H-C_prev|, |L-C_prev|)` |
| `atr_n` | float | price units | `rolling_mean(true_range, window=n)` for each configured n |

### Anchor / epoch logic
- Both `bar_index` and `calendar_day_index` are anchored to the first bar in
  the dataset (index 0).
- The epoch row timestamp is stored in the dataset manifest so cross-dataset
  comparisons can re-align if needed.
- Epoch is dataset-relative, not a global fixed date, to avoid large integer
  offsets and to remain correct across different history depths.

### Behavior on missing bars / gaps
- `bar_index` increments by 1 for every row present (it counts rows, not calendar days).
- `calendar_day_index` counts elapsed UTC calendar days from the first bar's timestamp;
  if a bar is missing, the sequence will have a gap in this value.
- `trading_day_index` counts observed bars (no gaps in the sequence); for 24/7
  BTC/USD daily data without missing bars this equals `bar_index`.
- The validation layer catches missing bars before this function runs. If a gap
  exists and validation did not fail, log a warning but continue.

### 24/7 crypto specifics
- No concept of "exchange-closed day" exists for BTC/USD.
- `trading_day_index` carries the semantic of "observation count," not
  "count of days the exchange was open."
- If later applied to equities, `trading_day_index` semantics must be revisited
  and a market-calendar dependency added. Document that change in DECISIONS.md.

### Fields stored into processed datasets
All 7+ fields above are written as columns into every processed `.parquet` file.
No downstream module may recompute these from raw data; all modules read from
the processed dataset.

### Interface sketch
```python
# core/coordinate_system.py

def add_indices(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add bar_index, calendar_day_index, trading_day_index to df.
    df must have a UTC-normalized datetime index or 'timestamp' column.
    Modifies df in-place and returns it.
    """
    ...

def add_derived_fields(df: pd.DataFrame, atr_windows: list[int]) -> pd.DataFrame:
    """
    Add log_close, hl_range, true_range, atr_n for each window.
    Requires 'open', 'high', 'low', 'close' columns.
    """
    ...

def build_coordinate_system(df: pd.DataFrame, atr_windows: list[int]) -> pd.DataFrame:
    """
    Convenience wrapper: runs add_indices then add_derived_fields.
    Returns the fully annotated DataFrame.
    """
    ...

def get_angle_scale_basis(df: pd.DataFrame) -> dict:
    """
    Return the price-per-bar scale factor required by adjusted_angles.py.
    Computes median ATR over the dataset as the canonical scale basis.
    Used by adjusted_angles module to normalize angular measurements.
    """
    ...
```

---

## Section 9 — Minimum Python Package / Plumbing Requirements

### `pyproject.toml`
A `pyproject.toml` at the project root (`jenkins_repo_docs_final/`) defines the
package, its dependencies, and the test runner configuration. This is required so
that `pytest` can discover tests and so that imports work consistently across modules.

**Minimum proposed `pyproject.toml`:**
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "jenkins-quant"
version = "0.1.0"
description = "Research-grade quant framework from Jenkins methods"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.26",
    "pyarrow>=14.0",     # parquet support
    "pyyaml>=6.0",       # config loading
    "pytest>=8.0",       # test runner
]

[tool.setuptools.packages.find]
where = ["."]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
```

Additional dependencies (added when the relevant phase begins):
- `scipy` — Phase 3 geometry (angle computation)
- `matplotlib` — Phase 6 reporting charts
- `statsmodels` or `quantstats` — Phase 6 metrics

```toml
[project.optional-dependencies]
research = ["scipy>=1.11", "matplotlib>=3.8", "statsmodels>=0.14"]
```

### Package initialization
Each code directory that is a Python package requires an `__init__.py`.
Stub files for Phase 1:
```
core/__init__.py
data/__init__.py
modules/__init__.py
signals/__init__.py
backtest/__init__.py
research/__init__.py
tests/__init__.py
```

### Test framework assumption
**pytest** is the assumed test runner. No other framework is assumed.
Tests are collected from `tests/` and named `test_*.py`.

### `test_validation.py` scope
Covers all checks from data_spec.md §10–12:
- OHLC integrity violations (low > high, close outside high/low)
- duplicate timestamp detection
- out-of-order row detection
- missing bar detection (continuity gaps)
- future timestamp detection
- volume-missing flag (no failure, just flag)
Uses synthetic DataFrames; no real data required.

### `test_ingestion.py` scope
Covers the pipeline from raw input to processed output:
- raw file write and read round-trip
- metadata JSON schema completeness
- validation integration (pass case + fail case)
- coordinate system field presence and correctness
- processed dataset manifest completeness
- dataset version string format conformance
Uses a synthetic 100-row OHLCV DataFrame injected as a mock raw extraction.
Does not require a live MCP connection.

---

## Section 10 — Candidate Inventory for Phase 2 Origin Methods

Phase 2 must implement and compare multiple origin-selection methods.
Origin selection is a research problem; no single method is hard-coded.
(Per CLAUDE.md Rule 1 + origin_selection_notes.md)

### Candidate methods (initial inventory)

| # | Method | Description | Key parameter(s) |
|---|---|---|---|
| O1 | ZigZag structural pivot | Classic percentage-threshold ZigZag; labels local extrema as H/L pivots | `threshold_pct`: minimum price move to count as a pivot |
| O2 | Williams fractal | 5-bar fractal pattern: bar[n] is pivot high if `high[n] > high[n±1] > high[n±2]` | `bars_each_side`: default 2 |
| O3 | ATR-threshold pivot | Bar qualifies as pivot if the move to/from it exceeds `k × ATR` | `k`: ATR multiplier |
| O4 | Range-expansion pivot | Bar qualifies if its range (`high - low`) exceeds `k × rolling_range_median` | `k` and `lookback_window` |
| O5 | Major swing pivot | Multi-timeframe: daily pivot must also be a pivot on the weekly chart | Requires weekly data; no additional parameters at this stage |
| O6 | Volume-weighted pivot | Pivot candidates weighted or filtered by relative volume; high-volume pivots score higher | `volume_threshold` as percentile |

### Validation concept (from origin_selection_notes.md)
A strong origin candidate should generate downstream geometry (projections,
trend lines, level clusters) that aligns with future turning points more
consistently than weaker candidates. Phase 2 must define a measurable scoring
metric for this alignment before any origin method is declared superior.

### Provisional ranking for Phase 2 start order
1. O1 (ZigZag) — baseline; widely understood; easiest to validate
2. O2 (Williams fractal) — mentioned in Jenkins-style literature; deterministic
3. O3 (ATR-threshold) — aligns with the project's volatility-awareness
4. O4, O5, O6 — lower priority; add after O1–O3 are tested

---

## Section 11 — Recommended Next Step

### Phase 0 deliverables status
- [x] Section 1: Architecture confirmation memo
- [x] Section 2: Implementation order
- [x] Section 3: Ambiguities and real blockers only
- [x] Section 4: MCP extraction workflow skeleton
- [x] Section 5: Repo structure check with explicit additions
- [x] Section 6: ASSUMPTIONS.md provisional entries
- [x] Section 7: `configs/default.yaml` schema
- [x] Section 8: `core/coordinate_system.py` design
- [x] Section 9: Python package/plumbing requirements
- [x] Section 10: Phase 2 origin-method candidate inventory

### Remaining open items before Phase 1 starts
1. **B1** — MCP tool/function names must be discovered and documented in
   `docs/data/mcp_extraction_runbook.md` at the start of Phase 1.
2. **B2** — 4H acquisition method must be empirically confirmed in Phase 1;
   provisional assumption is "direct pull" (Assumption 8 above).
3. **B3** — First official dataset version must be agreed; provisional default
   is `proc_COINBASE_BTCUSD_1D_UTC_2026-03-03_v1`.

### Hand-off to Reviewer
This output is ready for Reviewer Phase 0 assessment.
The Reviewer should evaluate using the Phase 0 Reviewer prompt at
`docs/prompts/phase0_reviewer.md`.

Auditor involvement is required only if Reviewer returns `reject` or if there
is a disputed architectural decision.

---
*Builder Phase 0 · Revised · Branch: `claude/read-phase-0-docs-W8kVW` · 2026-03-03*
