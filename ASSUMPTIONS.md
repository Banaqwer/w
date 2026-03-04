# Assumptions - Jenkins Quant Project

Use this file to log every approximation, temporary proxy, or unresolved implementation choice.

## Current assumptions
1. The source material is being translated into a testable quant framework, not accepted as proven alpha.
2. Structural pivot/origin selection is a research problem; multiple methods will be tested.
3. TradingView MCP extraction can provide sufficiently reliable historical candles for MVP acquisition, subject to validation.
4. Official experiments will use normalized saved datasets, not live bridge queries.
5. Direct 4H extraction is preferred if complete and stable; otherwise a documented resampling fallback will be used.
6. Weekly bars will use a fixed UTC-based rule, with Monday 00:00 UTC as the default interpretation unless changed in `DECISIONS.md`.
7. Advanced geometric modules remain experimental until MVP modules are validated.

---

## Phase 0 provisional assumptions (added 2026-03-03)

### Assumption 8 — 4H acquisition method
**Date:** 2026-03-03
**Assumption:** Direct native 4H candle extraction from the `tradingview-mcp` bridge is
available and sufficiently complete for `COINBASE:BTCUSD`. Use direct pull as the default
for Phase 1 ingestion.
**Reason:** DECISIONS.md specifies "prefer direct extraction if reliable." Before empirical
testing, direct pull is the optimistic default.
**What it approximates:** Full native 4H history from TradingView.
**How it will be tested:** In Phase 1, pull 4H data and check bar count, coverage depth,
and continuity. If gaps or shallow history are found, switch to documented Python resampling
from 1H or lower and record the change in DECISIONS.md.
**Status:** Provisional. Will be confirmed or overridden early in Phase 1.

### Assumption 9 — Weekly data source
**Date:** 2026-03-03
**Assumption:** Weekly bars will be produced by Python resampling from the official daily
processed dataset, not by a separate direct weekly pull from the MCP bridge.
**Reason:** Daily is the primary research timeframe and will be validated first. Resampling
from daily is deterministic and reproducible. Direct weekly pull can be added later if needed.
**What it approximates:** Native weekly candles from TradingView.
**How it will be tested:** Spot-checked against TradingView weekly chart for at least 10
reference bars.
**Status:** Provisional. Can be changed in DECISIONS.md if direct weekly pull proves superior.

### Assumption 10 — ATR default window
**Date:** 2026-03-03
**Assumption:** Default ATR window is 14 bars. The derived field stored in all processed
daily datasets is `atr_14`. Additional windows are config-driven.
**Reason:** ATR(14) is the conventional default and a widely used structural range reference.
No project document specifies a different window.
**What it approximates:** A generic volatility measure. The project may later define custom
windows tied to impulse length.
**How it will be tested:** Compared against TradingView ATR(14) on the daily chart for a
sanity check during Phase 1 validation.
**Status:** Provisional. Config-driven; can be changed without breaking anything.

### Assumption 11 — `trading_day_index` for 24/7 crypto
**Date:** 2026-03-03
**Assumption:** For BTC/USD (a 24/7 continuous market), `trading_day_index` is computed
as the zero-based sequential count of observed bars from the epoch anchor — identical to
`bar_index` for daily data with no gaps. If gaps exist, `trading_day_index` increments only
for present bars (count of observations, not count of days).
**Reason:** Crypto has no exchange-closed days. The index tracks observed bars, preserving
the "count of trading bars seen" semantic.
**What it approximates:** Traditional trading-day count used in equity markets.
**How it will be tested:** Compared with `calendar_day_index` on a known date range to
confirm correct divergence when gaps exist.
**Status:** Provisional. May be revised once gap behavior is analyzed on real data.

### Assumption 12 — `bar_index` and `calendar_day_index` anchor epoch
**Date:** 2026-03-03
**Assumption:** Both `bar_index` and `calendar_day_index` are zero-based, anchored to the
first bar present in the raw dataset (earliest available timestamp). The anchor timestamp
is stored in the dataset manifest.
**Reason:** Anchoring to a fixed external epoch (e.g. Unix epoch) produces large integers
and breaks if datasets with different start dates are compared directly. Dataset-relative
anchoring keeps values small and reproducible from any consistent dataset version.
**What it approximates:** A stable coordinate system; not a global calendar index.
**How it will be tested:** Confirmed by checking `bar_index == 0` at row 0, increments by
1 per bar, and `calendar_day_index` matches elapsed UTC calendar days from row 0.
**Status:** Provisional. Epoch rule must be stored in the dataset manifest to allow
cross-dataset comparisons via re-alignment.

### Assumption 13 — `atr_warmup_rows` exclusion rule
**Date:** 2026-03-04
**Assumption:** The first `atr_warmup_rows` rows of any processed dataset are treated as
ATR warm-up only. For the default ATR window of 14, the first 14 rows produce unreliable
ATR values (rolling window not yet filled). These rows are flagged in the manifest but are
not dropped from the stored dataset; downstream modules that depend on ATR must skip
the warm-up rows.
**Reason:** Dropping rows would alter `bar_index` / `calendar_day_index` anchor semantics.
Keeping them and flagging preserves coordinate-system integrity.
**What it approximates:** Standard ATR initialization behaviour in most TA libraries.
**How it will be tested:** Confirmed by checking that ATR values at row < 14 are NaN
in the processed dataset, and that the manifest records `atr_warmup_rows: 14`.
**Status:** Provisional. If window changes via config, `atr_warmup_rows` updates to match.

---

### Assumption 14 — `get_angle_scale_basis` uses median ATR
**Date:** 2026-03-04
**Assumption:** `get_angle_scale_basis` in `core/coordinate_system.py` computes the
price-per-bar scale factor for adjusted-angle modules by taking the median of `atr_14`
across the dataset (excluding warm-up rows). This scalar normalizes angular measurements
so that angles are comparable across different volatility regimes.
**Reason:** Median ATR is a robust central-tendency measure not skewed by outlier
volatility spikes. A full-dataset median gives a stable constant without requiring
rolling recalculation inside each projection module.
**What it approximates:** A hand-calibrated price-per-bar scale that a discretionary
analyst would select when drawing angles on a chart.
**How it will be tested:** Compared against a manually estimated scale for a known
BTC/USD chart segment during Phase 3 adjusted-angles validation.
**Status:** Provisional. May be revised if per-impulse scale proves superior.

---

## Logging rule
When a new simplification is introduced, add:
- date
- assumption
- reason
- what it approximates
- how it will later be tested or replaced
