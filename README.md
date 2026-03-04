# Jenkins Quant Project Repo

This repository contains the planning, handoff, and reference material for building a research-grade quant framework inspired by Michael S. Jenkins' *The Secret Science of the Stock Market*.

## What this repo is for
- define the project clearly
- give Claude Code and human reviewers a consistent instruction set
- freeze data and environment conventions
- organize the build into auditable phases
- keep the system modular, testable, and reproducible

## High-level workflow
1. Phase 0 - alignment
2. Phase 1 - repo and data layer
3. Phase 2 - structural pivot and impulse engine
4. Phase 3 - MVP projection stack
5. Phase 4 - confluence engine
6. Phase 5 - confirmation and execution
7. Phase 6 - validation
8. Phase 7 - advanced module expansion

## Core repo documents
- `CLAUDE.md` - master repo instructions
- `PROJECT_STATUS.md` - current phase and next actions
- `ASSUMPTIONS.md` - approximations and unresolved items
- `DECISIONS.md` - frozen project choices

## Main docs folders
- `docs/handoff/` - project handoff docs
- `docs/data/` - official data specification
- `docs/ai/` - AI operating protocol
- `docs/prompts/` - phase prompt packs
- `references/pdfs/` - source PDFs
- `references/notes/` - distilled notes from the source material

## MVP defaults
- market: BTC/USD
- symbol: `COINBASE:BTCUSD`
- research environment: Python
- acquisition layer: TradingView MCP bridge
- main timeframe: Daily
- confirmation timeframe: 4H
- structural timeframe: Weekly
- timezone: UTC
- daily close: 00:00 UTC

## Immediate start
If you are Claude Code or a human operator:
1. read `CLAUDE.md`
2. check `PROJECT_STATUS.md`
3. read `docs/data/data_spec.md`
4. begin with the current phase only
5. do not freewheel beyond that phase
