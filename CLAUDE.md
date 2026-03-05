# Jenkins Quant Project - Master Repo Instructions

## Project identity
This repository is a research-grade, modular quant framework built from the Jenkins project documents and source PDF material.

This is not:
- a discretionary charting assistant
- a generic TA bot
- a one-shot strategy script
- a screenshot-based workflow
- a TradingView-only project

This is a forecasting and validation system.

## Core architecture
The project must preserve this sequence:

1. detect the first structural impulse
2. derive time-price transforms from that impulse
3. generate forecast zones
4. score multi-module confluence
5. wait for market confirmation
6. execute with risk controls
7. validate with ablation and walk-forward testing

Do not collapse this into:
- RSI + moving average logic
- generic support/resistance
- hand-drawn chart interpretation
- anecdotal examples
- a simplified breakout bot unless explicitly requested for comparison

## Source-of-truth hierarchy
When making decisions, use this priority order:

1. `CLAUDE.md`
2. `docs/handoff/jenkins_quant_prd.md`
3. `docs/handoff/jenkins_quant_python_blueprint.md`
4. `docs/handoff/jenkins_quant_task_breakdown.md`
5. `docs/data/data_spec.md`
6. `ASSUMPTIONS.md`
7. `DECISIONS.md`
8. source PDFs and reference notes

If there is ambiguity:
- do not invent silent assumptions
- document the ambiguity
- propose options
- record the chosen approximation in `ASSUMPTIONS.md` or `DECISIONS.md`

## Official environment
### Primary research environment
- Python is the official environment for:
  - data ingestion
  - feature/module generation
  - projection engines
  - confluence scoring
  - confirmation logic
  - backtesting
  - ablation
  - reporting

### TradingView usage
TradingView may be used only for:
- chart inspection
- visual validation
- geometry sanity checks
- comparison to source examples
- optional later Pine Script translation if needed

TradingView is not the source of truth for:
- backtests
- signal validity
- performance claims
- experiment outputs

### MCP bridge usage
The user's TradingView <-> Claude MCP bridge is retained for current-bar snapshot sanity checks only.
It may be used to:
- inspect chart states via `coin_analysis` current-bar snapshots
- verify symbol and timeframe availability
- visual validation and geometry sanity checks
- comparison to source examples

It must NOT be used to:
- pull bulk historical OHLCV datasets (not supported by `tradingview-mcp`)
- produce official research datasets

Official historical OHLCV acquisition uses the **Coinbase REST API via `ccxt`**
(see `DECISIONS.md` 2026-03-04 change log and `docs/data/data_spec.md` §3).

However:
- official experiments must run on saved, versioned, normalized datasets
- official backtests may not rely on ad hoc live MCP queries
- every extraction must be logged and versioned

All official outputs must come from Python using validated datasets.

## Primary market and timeframe scope
### MVP market
- BTC/USD

### Official MVP chart symbol
- `COINBASE:BTCUSD`

### Main research timeframe
- Daily

### Confirmation / execution timeframe
- 6H

### Higher-structure validation timeframe
- Weekly

### Secondary validation markets after MVP
- EUR/USD
- SPY or ES
- Gold

Do not switch the MVP market or main timeframe without recording the reason in `DECISIONS.md`.

## Core design rules
### Rule 1 - Impulse first
The first structural impulse is the master state variable.

All projection modules must derive from the accepted structural impulse unless a module explicitly states otherwise.

### Rule 2 - Forecasting is not execution
A projected zone is not a trade by itself.

Every trade must pass through:
- forecast generation
- confluence scoring
- confirmation gating
- risk logic

### Rule 3 - Every module must be independently testable
No hidden dependencies.

Each module must be capable of being:
- turned on/off
- tested alone
- tested in combinations
- ablated from the final system

### Rule 4 - No silent simplifications
If a concept from the source material is approximated, record:
- what was simplified
- why
- what it approximates
- how it will later be tested or replaced

### Rule 5 - No chart-pixel geometry
All geometry must be mathematically defined in reproducible coordinates.

Do not build logic that depends on:
- screen pixels
- chart zoom
- display aspect ratio
- manual drawing position

### Rule 6 - Reproducibility is mandatory
All experiments must be reproducible from:
- code
- configs
- logged assumptions
- stored outputs

### Rule 7 - Keep both time systems alive
Maintain:
- calendar-day logic
- trading-day / bar-index logic

Do not remove either during MVP unless explicitly justified.

## Required MVP module stack
Implement these first:

1. structural pivot and impulse engine
2. measured move module
3. adjusted angle module
4. JTTL module
5. square-root horizontal level module
6. time-count / squaring-the-range module
7. log-level / semi-log module
8. confluence engine
9. confirmation engine
10. execution and risk layer
11. backtest engine
12. ablation and walk-forward framework

Do not begin advanced modules until MVP is running and testable.

## Advanced modules
Only after MVP validation, add:
- arcs / circles
- boxes / squares
- Pythagorean ratio engine
- music-ratio engine
- expanded wheel/root-cycle transforms

These modules must remain experimental until they prove incremental value.

## Build phase order
### Phase 0 - alignment
Deliver:
- architecture confirmation memo
- implementation order
- ambiguity list
- repo structure proposal
- MCP extraction workflow proposal

### Phase 1 - repository and data layer
Deliver:
- repository skeleton
- config system
- data loaders
- coordinate system
- data validation checks
- MCP extraction scripts or documented ingestion workflow

### Phase 2 - structural pivot and impulse engine
Deliver:
- multiple pivot/origin methods
- impulse extraction
- structural importance scoring
- impulse metadata objects

### Phase 3 - MVP projection stack
Deliver:
- measured moves
- adjusted angles
- JTTL
- square-root levels
- time counts
- log levels
- tests
- docs

### Phase 4 - confluence engine
Deliver:
- support/resistance/turn-date scoring
- forecast-zone builder
- scoring docs

### Phase 5 - confirmation and execution
Deliver:
- confirmation logic
- trade signal logic
- stops / targets / trailing
- risk layer

### Phase 6 - validation
Deliver:
- backtest runner
- ablation runner
- walk-forward runner
- first research report

### Phase 7 - advanced expansion
Deliver:
- advanced modules
- incremental value analysis
- keep/drop recommendations

## Required objects and interfaces
At minimum the codebase must support these concepts:

### `Impulse`
Fields should include:
- origin_time
- origin_price
- extreme_time
- extreme_price
- delta_t
- delta_p
- slope_raw
- slope_log
- quality_score
- detector_name

### `Projection`
Fields should include:
- module_name
- impulse_id
- projected_time
- projected_price
- time_band
- price_band
- direction_hint
- raw_score

### `ForecastZone`
Fields should include:
- zone_start
- zone_end
- price_low
- price_high
- support_score
- resistance_score
- turn_score
- combined_score
- modules_hit

### `TradeSignal`
Fields should include:
- side
- entry_time
- entry_price
- stop_price
- target_price
- confluence_score
- confirmation_type

## Research standards
### Required validation
Test:
- each module alone
- key module pairs
- full system without confirmation
- full system with confirmation
- multiple assets
- multiple regimes
- walk-forward splits

### Minimum metrics
Report:
- expectancy
- hit rate
- average R multiple
- Sharpe / Sortino
- max drawdown
- turnover
- calibration of confluence score vs realized reaction probability

### Baselines
Compare against:
- random entry with same risk rules
- basic breakout baseline
- basic swing-reversal baseline
- simple moving-average baseline

## Logging requirements
Every meaningful run must log:
- selected impulse
- module outputs
- forecast zones
- confluence scores
- confirmation signals
- entries/exits
- stop/target logic
- metrics
- assumptions used
- failure notes

No milestone is complete without logs.

## Documentation requirements
Every completed module must include:
- module purpose
- formula summary
- inputs
- outputs
- assumptions
- tests
- known limitations

If a file or module is incomplete, say so explicitly.

## What not to do
Do not:
- claim edge before testing
- cherry-pick good-looking examples
- use manual chart interpretation in production logic
- mix multiple data conventions during MVP
- skip ablation
- hide uncertain assumptions
- move on from a broken phase just to make progress appear faster

## Definition of done
A milestone is complete only if:
- code runs
- tests pass
- logs exist
- documentation exists
- assumptions are recorded
- outputs are reproducible

A module is not done because it looks visually correct on one chart.

## Default working behavior
When asked to work:
1. identify the current phase
2. state the exact deliverable
3. work only on that deliverable
4. list assumptions
5. list files changed
6. summarize tests
7. note open issues
8. suggest the next narrow step

Do not freewheel beyond the requested phase.

## Immediate instruction
Start from the current phase indicated in `PROJECT_STATUS.md`.

If that file is missing, begin with:
- architecture confirmation
- repo structure
- data specification check
- ambiguity list
- MCP extraction workflow plan

Then stop and wait for review.
