# AI Team Operating Protocol - Claude Code Build System

## 1. Model assignments

### Builder Agent
- Model: Claude Sonnet 4.x / latest Sonnet available in Claude Code
- Role: primary implementation agent
- Environment: separate dedicated session

Responsibilities:
- build repository structure
- implement data pipeline
- implement pivot and impulse engine
- implement MVP projection modules
- implement confluence engine
- implement confirmation logic
- implement execution and risk layer
- write tests, configs, logs, and documentation

Rules:
- do not silently simplify source logic
- do not skip testing or logging
- do not redesign scope without documenting it
- work milestone by milestone, not all at once

### Reviewer Agent
- Model: Claude Sonnet 4.x / latest Sonnet available in Claude Code
- Role: independent reviewer
- Environment: separate session with no inherited assumptions from Builder

Responsibilities:
- review each completed module after Builder
- challenge logic, assumptions, formulas, interfaces, and tests
- detect drift into generic TA logic
- flag overfitting, leakage, weak abstractions, or unsupported simplifications
- return pass / revise / reject for each milestone

Rules:
- do not trust Builder output by default
- produce written defect notes
- require exact mapping between implementation and project documents

### Auditor Agent
- Model: Claude Opus 4.x / latest Opus available in Claude Code
- Role: architectural auditor and adversarial critic
- Environment: separate session, only used at milestone gates

Responsibilities:
- review architecture and research validity
- detect weak methodology and false confidence
- resolve disputes between Builder and Reviewer
- approve or reject milestone completion
- audit ablation design, walk-forward design, and evaluation quality

Rules:
- do not act as day-to-day implementer
- intervene only at major checkpoints
- write short milestone decision memos

## 2. Project operating principle
This project is a research-grade quant framework. It is not a discretionary charting workflow and not a generic TA bot.

The system must follow this sequence:
1. detect the first structural impulse
2. derive time-price transforms from that impulse
3. build forecast zones through multi-module confluence
4. require market confirmation
5. execute trades with risk controls
6. validate every module independently and jointly

## 3. Environment rules
- Python is the official build, testing, and research environment.
- TradingView through the user's MCP bridge is the approved acquisition and visual-validation layer.
- All official outputs must come from validated datasets in Python.

## 4. Market and data rules
- Primary MVP market: BTC/USD
- Official symbol: `COINBASE:BTCUSD`
- Primary timeframe: Daily
- Confirmation timeframe: 6H
- Structural timeframe: Weekly
- Official timezone: UTC
- Official daily close: 00:00 UTC
- Keep both calendar-day and trading-day logic alive

## 5. Build phases
### Phase 0
- read all handoff docs
- summarize architecture and implementation order
- confirm shared understanding
- propose MCP extraction workflow

### Phase 1
- repository skeleton
- config system
- data loaders
- coordinate system
- data validation checks

### Phase 2
- multiple pivot/origin methods
- impulse extraction
- structural importance scoring

### Phase 3
- measured moves
- adjusted angles
- JTTL
- square-root levels
- time-count engine
- log-level engine

### Phase 4
- confluence engine
- forecast-zone builder

### Phase 5
- confirmation
- execution
- risk logic

### Phase 6
- backtests
- ablation
- walk-forward
- reporting

### Phase 7
- advanced modules

## 6. Non-negotiable rules
- never freewheel the whole project in one pass
- every simplification must be documented
- every module must be independently testable
- forecasting is not execution
- do not hard-code one origin method too early
- all outputs must be reproducible
- logs are mandatory

## 7. Handoff format
Builder handoff must include:
- what was built
- files changed
- formulas/logic used
- tests added
- known uncertainties

Reviewer response must include:
- pass / revise / reject
- key defects
- required changes
- untested assumptions
- fidelity concerns

Auditor decision must include:
- approved / conditionally approved / rejected
- architectural concerns
- research concerns
- milestone readiness
