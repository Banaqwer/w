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

### Assumption 13 — Minimum daily history depth
**Date:** 2026-03-03
**Assumption:** The target minimum daily history for BTC/USD is 10 years
(consistent with `data_spec.md` §13 and `configs/default.yaml` `min_history_years_daily: 10`).
**Reason:** Jenkins-style methods depend on long structural history to identify
major swings and impulses. Ten years of daily BTC/USD data covers multiple full
market cycles. Shorter history risks anchoring impulse detection on locally
significant but structurally minor moves.
**What it approximates:** The ideal of "as much history as possible," bounded by
a practical minimum for the MVP validation to be structurally meaningful.
**How it will be tested:** At Phase 1 ingestion, compute `(last_bar - first_bar).days / 365.25`
from the extracted dataset and compare to the 10-year target.
**If actual MCP coverage is shorter than 10 years:**
- Do not fail ingestion; proceed with available data.
- Log a warning with the actual coverage depth.
- Note the coverage gap in the dataset manifest.
- Mark any research results produced from that dataset as having limited structural
  history depth. Do not treat them as equivalent to results from a 10-year dataset.
  Record the coverage shortfall in `DECISIONS.md` before proceeding.
**Status:** Provisional. Applied as a warning threshold, not a hard failure.

---

### Assumption 14 — Definition of "material missing bars"
**Date:** 2026-03-03
**Assumption:** For MVP, "material missing bars" is defined as **any missing bar
count greater than zero**, unless a specific documented exception is approved and
recorded in `DECISIONS.md`. The config setting `max_allowed_missing_bars: 0`
enforces this.
**Reason:** Jenkins-style time-count logic and squaring-the-range methods are
sensitive to bar counts and row continuity. A single missing bar can shift all
downstream time projections by one bar. The conservative default avoids silent
drift in time-sensitive results.
**What it approximates:** A zero-tolerance missing-data policy for the official
MVP dataset.
**How it will be tested:** The validation pipeline raises an exception and writes
a failure report when any missing bar is detected. Tests cover both the pass case
(complete sequence) and the fail case (deliberate gap).
**When to override:** If a source data gap is unavoidable (e.g. exchange downtime
with confirmed zero trading), a documented exception may be approved. The exception
must: name the specific timestamps, state the cause, record the action taken
(quarantine, label, or skip), and be logged in `DECISIONS.md`.
**Status:** Provisional. Strict default. Any relaxation requires DECISIONS.md entry.

---

### Assumption 15 — ATR warmup NaN rows
**Date:** 2026-03-03
**Assumption:** Rolling ATR computation produces expected NaN values for the first
n−1 rows of each `atr_n` field (e.g. `atr_14` has NaN for rows 0–12). These NaN
rows are **not validation errors** and do not cause ingestion to fail.
**Reason:** Rolling windows cannot be computed before sufficient observations
accumulate. This is standard behavior for any rolling statistic.
**What it approximates:** A complete ATR series; the warmup period is data loss
inherent to the rolling window method.
**How it will be tested:** Tests explicitly confirm that `atr_14` is NaN for rows
0–12 and non-null for rows 13 onward on a synthetic 100-row dataset.
**If warmup rows are a problem:** If ATR values are needed at the very start of
a dataset (e.g. for an impulse that occurs in the first 14 bars), this must be
handled by extending the raw extract to provide sufficient pre-history. Do not
use forward-filled or invented ATR values.
**Status:** Documented expected behavior. Not a blocker.

---

## Logging rule
When a new simplification is introduced, add:
- date
- assumption
- reason
- what it approximates
- how it will later be tested or replaced
