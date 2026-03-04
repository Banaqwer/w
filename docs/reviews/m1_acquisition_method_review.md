# M1 Acquisition-Method Review

**Reviewer:** Automated review agent
**Date:** 2026-03-04
**Scope:** M1 recommendation only — Coinbase REST API via `ccxt` as official historical OHLCV acquisition method
**Phase reviewed:** Phase 1, M1 resolution

---

## 1. Verdict

### **REVISE → PASS (after fixes applied in this commit)**

The M1 acquisition-method recommendation itself is **sound, well-justified, and architecturally consistent**. However, the doc stack contained **14 stale references** to the superseded TradingView MCP bulk-extraction method, including **3 code-level bugs** that would have broken the first official dataset pull. All issues have been corrected in this commit.

---

## 2. Recommendation summary

| Property | Value |
|---|---|
| Method | Coinbase REST API via `ccxt` |
| Exchange | `coinbase` (Coinbase Advanced Trade) |
| Symbol (ccxt) | `BTC/USD` |
| TradingView reference | `COINBASE:BTCUSD` |
| Auth required | No (public OHLCV endpoint) |
| Primary TF | `1d` |
| Confirmation TF | `4h` (native pull) |
| Structural TF | `1w` (Python resample from `1d`) |
| History depth | ~2015–present (daily), ~2017–present (4H) |

**Rationale strengths:**
- Coinbase is the canonical exchange for `COINBASE:BTCUSD`
- REST API is the direct upstream source of the TradingView data series
- `ccxt` provides paginated, UTC-normalised Python interface
- No API key needed for public historical OHLCV
- History depth satisfies `data_spec.md §13` (≥ 10 years daily)
- MCP bridge role correctly narrowed to `coin_analysis` sanity checks

---

## 3. Conflicts found and resolved

### 3.1 Code bugs (Critical — would break first dataset pull)

| # | File | Issue | Fix |
|---|---|---|---|
| 1 | `data/loader.py:102` | `load_raw()` default `base_path` was `"data/raw/tradingview_mcp"` | Changed to `"data/raw/coinbase_rest"` |
| 2 | `data/loader.py:131` | `load_raw()` filename prefix was `tvmcp_` | Changed to `cbrest_` |
| 3 | `data/loader.py:170` | `load_extraction_metadata()` filename prefix was `tvmcp_` | Changed to `cbrest_` |

### 3.2 Functional config

| # | File | Issue | Fix |
|---|---|---|---|
| 4 | `.gitignore:33-39` | Gitignore patterns referenced `data/raw/tradingview_mcp/` | Updated to `data/raw/coinbase_rest/` |

### 3.3 Documentation conflicts

| # | File / Section | Issue | Fix |
|---|---|---|---|
| 5 | `CLAUDE.md` §MCP bridge usage | Listed "pull official historical candles" as MCP use case — contradicts M1 | Rewritten to reflect sanity-check-only role |
| 6 | `PROJECT_STATUS.md` line 45 | "TradingView … is the approved acquisition layer" — stale | Split into two lines: MCP = sanity checks only; Coinbase REST = official |
| 7 | `docs/data/data_spec.md` §2 | Listed "historical candle extraction" as MCP use case | Replaced with "current-bar snapshot sanity checks" |
| 8 | `docs/data/data_spec.md` §8 | 4H policy referenced "TradingView MCP bridge" | Updated to "Coinbase REST API via `ccxt`" |
| 9 | `docs/data/data_spec.md` §18 title | Section titled "MCP extraction metadata" — misleading | Changed to "Extraction metadata requirements" |
| 10 | `docs/data/data_spec.md` §18 body | Referenced "MCP command used" | Changed to "extraction method (e.g. `coinbase_rest_ccxt`)" |
| 11 | `docs/data/data_spec.md` §22 | Open items still listed MCP workflow and 4H as unresolved | Marked first three items RESOLVED with cross-references |
| 12 | `DECISIONS.md` §4H policy | Original inline section still said "MCP bridge" | Updated to match the 2026-03-04 change log |
| 13 | `docs/data/mcp_extraction_runbook.md` §3.2 | Steps 1–3 showed old paths (`tradingview_mcp/`) and old prefix (`tvmcp_`) | Updated to `coinbase_rest/` and `cbrest_` |
| 14 | `tests/test_ingestion.py:63,66` | Fixture used old path `raw/tradingview_mcp` and old method `tradingview-mcp` | Updated to `raw/coinbase_rest` and `coinbase_rest_ccxt` |

### 3.4 Not updated (historical record — intentional)

| File | Reason |
|---|---|
| `docs/phase0_builder_output.md` | Phase 0 historical record. The `DECISIONS.md` change log already documents the supersession. Rewriting the Phase 0 output would break audit trail. |

---

## 4. Consistency check against required files

| Document | Consistent after fixes? | Notes |
|---|---|---|
| `docs/data/data_spec.md` | ✅ Yes | §2, §3, §8, §16, §17, §18, §21, §22 all aligned |
| `DECISIONS.md` | ✅ Yes | Change log + inline 4H policy now consistent |
| `ASSUMPTIONS.md` | ✅ Yes | Assumptions 3, 5, 8 correctly invalidated/superseded; Assumption 16 active |
| `PROJECT_STATUS.md` | ✅ Yes | Confirmed decisions list and M1/M2/M3 status accurate |
| `CLAUDE.md` | ✅ Yes | MCP bridge section rewritten to sanity-check-only role |
| `configs/default.yaml` | ✅ Yes | Already correct (updated before this review) |
| `data/ingestion.py` | ✅ Yes | Already used `cbrest_` prefix and `coinbase_rest` paths |
| `data/loader.py` | ✅ Yes | Fixed in this commit |
| `.gitignore` | ✅ Yes | Fixed in this commit |
| `tests/test_ingestion.py` | ✅ Yes | Fixed in this commit |

---

## 5. Can the project proceed to the first official dataset pull?

**Yes** — once the fixes in this commit are merged:

1. All stale references to `tradingview_mcp` / `tvmcp_` have been corrected
2. `data/loader.py` now matches the storage convention in `data/ingestion.py`
3. `.gitignore` covers the actual raw data path
4. The doc stack is internally consistent on the acquisition method
5. All 59 existing tests pass
6. The remaining pre-pull checklist items (from `mcp_extraction_runbook.md` §7) are operational — install `ccxt`, execute pull, spot-check, set dataset version

**Immediate next step:** Execute item 4 on `PROJECT_STATUS.md` — install `ccxt` and run the first official daily data pull from Coinbase REST API.

---

## 6. Risk notes

- `docs/phase0_builder_output.md` still contains old `tvmcp_` / `tradingview_mcp` references. This is acceptable as a historical record but could confuse future readers. Consider adding a note at the top of that file pointing to the M1 resolution in `DECISIONS.md`.
- The `data/ingestion.py` metadata JSON still writes `mcp_server` and `mcp_tool_name` fields. These are harmless for Coinbase REST pulls (they'll be empty strings) but could be renamed in a future cleanup pass to `sanity_check_server` / `sanity_check_tool` for clarity.
