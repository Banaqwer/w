# Project Status - Jenkins Quant Project

## Current phase
- Phase 1 — Repository and data layer (in progress)

## Current status

### Phase 0 — COMPLETE (approved 2026-03-04)
- Architecture confirmation memo produced and passed review
- Implementation order confirmed
- Ambiguity list resolved
- Repo structure and phase sequence approved
- MCP extraction workflow proposed in phase0_builder_output.md
- All canonical docs consistent and internally aligned

### Phase 1 — IN PROGRESS (started 2026-03-04)

#### Completed deliverables
- `docs/data/mcp_extraction_runbook.md` — MCP tool discovery + extraction workflow
- `pyproject.toml` — Python project definition; pytest-ready
- `configs/default.yaml` — all data + module defaults; config-driven experiment control
- `core/__init__.py`, `core/coordinate_system.py` — coordinate system with all derived fields
- `data/__init__.py`, `data/validation.py` — OHLC + continuity checks (data_spec.md §10–12)
- `data/ingestion.py` — raw → processed ingestion pipeline (7 steps per phase0 workflow)
- `data/loader.py` — load processed datasets, raw files, manifests, extraction metadata
- `modules/__init__.py`, `signals/__init__.py`, `backtest/__init__.py`, `research/__init__.py` — package stubs
- `tests/test_validation.py`, `tests/test_coordinate_system.py`, `tests/test_ingestion.py` — 59 tests, all passing
- Data directory structure: `data/raw/coinbase_rest/`, `data/processed/`, `data/metadata/extractions/`

#### Open Phase 1 items
- **M1 — RESOLVED (2026-03-04):** `tradingview-mcp` has no bulk historical OHLCV tool.
  Official acquisition method selected: **Coinbase REST API via `ccxt`**.
  Decision recorded in `DECISIONS.md` 2026-03-04 change log.
- **M2 — RESOLVED (2026-03-04):** Assumption 8 (direct 4H pull from MCP) has been
  invalidated and updated in `ASSUMPTIONS.md`. Assumption 16 added.
  4H will be pulled natively from Coinbase REST API via `ccxt`.
- **M3 — RESOLVED (2026-03-04):** Coinbase REST API symbol is `BTC/USD` (ccxt format)
  which maps to `COINBASE:BTCUSD`. Symbol confirmed consistent with canonical reference.
- **M5:** Set `dataset.current_version` in `configs/default.yaml` once first pull date is known.
- First official raw dataset pull not yet executed — acquisition method now confirmed; ready to pull.

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

## Immediate next actions
1. ~~Review mcp_extraction_runbook.md §2 and select the historical data acquisition method~~ — DONE
2. ~~Record the decision in `DECISIONS.md`~~ — DONE
3. ~~Update `ASSUMPTIONS.md` Assumption 8 to reflect the actual acquisition method~~ — DONE
4. Install `ccxt` (`pip install ccxt`) and execute the first official daily data pull from Coinbase REST API
5. Run the ingestion pipeline with `extraction_method="coinbase_rest_ccxt"` and `raw_base="data/raw/coinbase_rest"`
6. Spot-check ≥ 20 bars against TradingView `COINBASE:BTCUSD` daily chart
7. Log any discrepancies in `DECISIONS.md`; confirm dataset passes validation
8. Confirm dataset version and update `configs/default.yaml` `dataset.current_version`
9. Phase 1 complete when: first processed dataset exists, passes validation, manifest is written

## Success condition for Phase 1
Phase 1 is complete when:
- All scaffolding files exist and tests pass
- MCP runbook documents actual tool names and limitations
- First processed dataset for `COINBASE:BTCUSD` daily is produced, validated, and version-stamped
- Dataset manifest exists and all derived fields are confirmed non-null (post-warmup)

## Notes
Do not start Phase 2 until the first official processed dataset is confirmed valid.
Phase 2 scope: structural pivot and impulse engine.
