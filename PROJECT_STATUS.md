# Project Status - Jenkins Quant Project

## Current phase
- Phase 0 - alignment

## Current status
- final repo instruction docs prepared
- handoff docs prepared
- source PDFs prepared
- reference notes prepared
- AI team operating protocol prepared
- prompt packs for Phase 0 and Phase 1 prepared
- MCP-aware data policy finalized at the document level
- remaining task: upload final docs to repo and begin Builder Phase 0

## Confirmed project decisions
- Python is the official research and testing environment
- TradingView through the user's MCP bridge is the approved acquisition layer
- official experiments must run on saved, normalized, versioned datasets
- TradingView is not the official source of truth for backtest outputs
- BTC/USD is the MVP market
- official chart symbol is `COINBASE:BTCUSD`
- spot market is the MVP instrument choice
- UTC is the official timezone
- 00:00 UTC is the official daily close
- Daily / 4H / Weekly are the official MVP timeframes

## Open implementation items
- define the exact MCP extraction command/workflow to use consistently
- decide whether weekly is always resampled from daily or optionally pulled directly
- decide the first official dataset version name for MVP
- create the actual repo and upload the final doc bundle
- launch Claude Code Builder / Reviewer / Auditor sessions

## Immediate next actions
1. upload final doc bundle to repo
2. confirm any remaining open data implementation choices in `DECISIONS.md`
3. start Builder with the Phase 0 builder prompt
4. send Builder Phase 0 output to Reviewer
5. involve Auditor only if there is disagreement or a milestone gate decision is needed

## Success condition for Phase 0
Phase 0 is complete when:
- Builder produces an architecture confirmation memo
- Reviewer returns pass / revise / reject
- any critical dispute is resolved
- the repo structure and implementation order are approved
- the MCP extraction workflow is proposed clearly enough to begin Phase 1

## Notes
Do not start full implementation until Phase 0 is approved.
Do not allow the AI to skip directly to coding the whole system.
