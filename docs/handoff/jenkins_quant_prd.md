# Jenkins Quant Project PRD

## Objective
Build a research-grade quant framework that converts the methods in Michael S. Jenkins' *The Secret Science of the Stock Market* into modular, testable, reproducible components.

## Product goal
The system must determine, rigorously, which parts of the Jenkins framework can be formalized, tested, and retained as real signal-producing components.

## Core thesis
The framework treats the first structural impulse as the market's native unit, derives time-price transforms from that unit, merges projections into confluence zones, waits for market confirmation, and only then executes trades with risk controls.

## Required outcomes
- reproducible research pipeline
- modular signal stack
- forecast-zone generation
- confirmation-gated trade engine
- backtesting, ablation, and walk-forward validation
- clear decision trail for assumptions and simplifications

## In scope
- OHLCV-based research
- Daily / 4H / Weekly MVP stack
- BTC/USD MVP
- later validation on EUR/USD, SPY/ES, Gold
- Python-based research environment
- TradingView MCP as approved acquisition layer

## Out of scope
- discretionary chart drawing
- screenshot-only analysis
- assuming the book is correct without testing
- ad hoc TradingView backtests as official evidence

## MVP feature set
1. structural pivot and impulse engine
2. measured moves
3. adjusted angles
4. JTTL
5. square-root horizontal levels
6. time-count engine
7. log-level engine
8. confluence engine
9. confirmation layer
10. execution and risk layer
11. backtest and reporting

## Success metrics
- reproducible outputs
- independent module testing
- statistically meaningful evaluation
- walk-forward behavior that is stable enough to justify retention of modules

## Non-negotiables
- forecasting is separate from execution
- all datasets are versioned
- all assumptions are logged
- no silent simplifications
- no module is accepted because it "looks right" on a chart
