# Assumptions - Jenkins Quant Project

Use this file to log every approximation, temporary proxy, or unresolved implementation choice.

## Current assumptions
1. The source material is being translated into a testable quant framework, not accepted as proven alpha.
2. Structural pivot/origin selection is a research problem; multiple methods will be tested.
3. ~~TradingView MCP extraction can provide sufficiently reliable historical candles for MVP acquisition, subject to validation.~~ **INVALIDATED 2026-03-04** — `tradingview-mcp` provides only a current-bar snapshot, not bulk historical arrays. Official acquisition method is now Coinbase REST API via `ccxt` (see `DECISIONS.md` change log and Assumption 16).
4. Official experiments will use normalized saved datasets, not live bridge queries.
5. ~~Direct 4H extraction is preferred if complete and stable; otherwise a documented resampling fallback will be used.~~ **SUPERSEDED 2026-03-04** — 4H was pulled natively from Coinbase REST API via `ccxt`. **SUPERSEDED 2026-03-05** — The official intraday confirmation timeframe is now `6H` (see `DECISIONS.md` 2026-03-05 change log and Assumption 17).
6. Weekly bars will use a fixed UTC-based rule, with Monday 00:00 UTC as the default interpretation unless changed in `DECISIONS.md`.
7. Advanced geometric modules remain experimental until MVP modules are validated.

---

## Phase 0 provisional assumptions (added 2026-03-03)

### Assumption 8 — 4H acquisition method (**INVALIDATED 2026-03-04**)
**Date:** 2026-03-03
**Assumption:** ~~Direct native 4H candle extraction from the `tradingview-mcp` bridge is
available and sufficiently complete for `COINBASE:BTCUSD`. Use direct pull as the default
for Phase 1 ingestion.~~
**Invalidation reason:** `tradingview-mcp` does not provide bulk historical OHLCV arrays
of any timeframe. The `coin_analysis` tool returns only a single current-bar snapshot.
Direct 4H pull from the MCP bridge is not possible.
**Superseded by:** Assumption 16. 4H candles will be pulled natively from the Coinbase
REST API via `ccxt`, or resampled from 1H if native 4H depth is insufficient.
**Decision recorded in:** `DECISIONS.md` 2026-03-04 change log.
**Status:** INVALIDATED.

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

### Assumption 15 — Early COINBASE:BTCUSD daily history gaps
**Date:** 2026-03-04
**Assumption:** Early `COINBASE:BTCUSD` daily history (pre-approximately 2015) may contain
multi-day gaps. The operator should expect `max_allowed_missing_bars` to require documented
relaxation for long-history ingestion. Any such relaxation must be recorded in `DECISIONS.md`.
A relaxed-gap dataset is not equivalent to a fully gap-free dataset and must be labeled
accordingly (e.g. with a manifest flag or filename suffix indicating relaxed-gap status).
**Reason:** Early exchange history is incomplete; requiring strict gap checks would
reject otherwise usable long-history data without a clear record of the trade-off.
**What it approximates:** A fully continuous daily dataset from inception.
**How it will be tested:** During Phase 1 ingestion, the actual gap count and maximum
gap length for pre-2015 bars will be logged. Any relaxation of `max_allowed_missing_bars`
beyond the default will be recorded in DECISIONS.md before the dataset is accepted.
**Status:** Provisional. Must be revisited once real ingestion data is available.

### Assumption 16 — Official historical OHLCV acquisition via Coinbase REST API
**Date:** 2026-03-04
**Assumption:** The official method for acquiring BTC/USD historical OHLCV data for MVP
is the Coinbase REST API accessed through the `ccxt` Python library.
- `ccxt` exchange id: `coinbase`
- Symbol (ccxt format): `BTC/USD`
- Canonical TradingView reference: `COINBASE:BTCUSD`
- Primary timeframe: `1d` (daily)
- Confirmation timeframe: ~~`4h`~~ **SUPERSEDED 2026-03-05** → `6h` (see Assumption 17)
- Structural timeframe: `1w` (Python resampling from `1d` processed dataset)
- UTC timestamps: native — Coinbase API returns UTC millisecond timestamps
- No API key required for public historical OHLCV
- Daily history depth: approximately 2015 to present
- 6H history depth: approximately 2017 to present
**Reason:** `tradingview-mcp` cannot provide bulk historical OHLCV (Assumption 3
invalidated). Coinbase is the canonical exchange for the project symbol. The REST API
is the direct upstream source for TradingView's `COINBASE:BTCUSD` series. `ccxt` provides
a stable, well-maintained, paginating Python client with UTC normalisation.
**What it approximates:** The `COINBASE:BTCUSD` TradingView data series for all
historical periods.
**How it will be tested:**
1. Pull 1D dataset and spot-check ≥ 20 bars against TradingView `COINBASE:BTCUSD` daily
   chart for close, high, low agreement.
2. Log any material discrepancies (> 0.1%) in `DECISIONS.md` before accepting the dataset
   for research.
3. Confirm 6H bar alignment to UTC 6-hour boundaries.
**Status:** Active. Replaces Assumptions 3 and 8. Confirmation timeframe updated to 6H per Assumption 17.

---

### Assumption 17 — Official intraday confirmation timeframe is 6H
**Date:** 2026-03-05
**Assumption:** The official intraday confirmation timeframe for the MVP is native `6H`
from the Coinbase REST API via `ccxt` (ccxt timeframe string: `6h`).
This replaces the previous `4H` confirmation timeframe (Assumption 16 / `DECISIONS.md`
2026-03-04 policy).
- `ccxt` timeframe string: `6h`
- Dataset naming: `cbrest_COINBASE_BTCUSD_6H_UTC_<pull-date>.csv`
- Processed naming: `proc_COINBASE_BTCUSD_6H_UTC_<pull-date>_v1`
- Resample fallback: from 1H native pull if 6H depth is insufficient
- Do not mix native 6H and resampled 6H within the same official MVP experiment family
**Reason:** Per `DECISIONS.md` 2026-03-05 change log. Native `6H` is available from
Coinbase REST API and provides better structural alignment for Jenkins confirmation logic.
**What it approximates:** Intraday confirmation bars previously served by `4H`.
**How it will be tested:** Confirm 6H bar alignment to UTC 6-hour boundaries; spot-check
≥ 10 bars against a reference source when live API is accessible.
**Status:** Active. Supersedes `4H` confirmation policy from Assumption 16 / `DECISIONS.md` 2026-03-04.

---

### Assumption 18 — 6H missing-bar tolerance for resampled-from-1H datasets
**Date:** 2026-03-06
**Assumption:** When producing 6H datasets by resampling from 1H Coinbase REST raw data,
up to 5 missing 6H bars are tolerated without failing validation.  The default strict
policy (`fail_on_missing_bar: true`, `max_allowed_missing_bars: 0`) is overridden with
`fail_on_missing_bar: False`, `max_allowed_missing_bars: 5` in `data/ingest_from_raw.py`.
**Reason:** The 1H source data from Coinbase REST API contains isolated exchange-maintenance
gaps (e.g., one 12-hour gap at 2018-08-10).  When resampled to 6H, each such outage
produces at most 1–2 missing 6H bars.  The observed count for the
`proc_COINBASE_BTCUSD_6H_UTC_2026-03-06_v1` dataset is exactly 1 missing bar.
A cap of 5 provides a safety margin without silently accepting structurally broken data.
**What it approximates:** A fully continuous 6H bar series from Coinbase.
**How it will be tested:** The actual missing-bar count, policy, and gap timestamps are
recorded in every manifest (`missing_bar_count`, `missing_bar_policy`,
`missing_bar_details`).  Downstream modules that require gap-free data can check the
manifest and either skip affected bars or raise.
**Status:** Active.  See `DECISIONS.md` 2026-03-06 change log for the corresponding decision.

---

### Assumption 19 — Pivot detector uses strict greater-than comparison
**Date:** 2026-03-06
**Assumption:** For the N-bar pivot detector in `modules/origin_selection.py`, a pivot-high
requires `high[i] > high[j]` for all j in the look-back and look-forward window (strict
inequality).  Bars with the same high as the pivot bar are treated as non-pivot.
**Reason:** Strict comparison ensures determinism on flat-top / flat-bottom price
structures (multiple bars at the same extreme).  Relaxing to ≥ would produce multiple
adjacent pivots at the same level, inflating the origin count.
**What it approximates:** The standard N-bar fractal pivot definition.
**How it will be tested:** Synthetic flat-top series confirms only one pivot is produced.
**Status:** Active.

### Assumption 20 — Pivot quality score formula
**Date:** 2026-03-06
**Assumption:** Pivot quality score is computed as `prominence / (3 × median_atr_14)`,
clipped to [0, 1].  A prominence equal to 3× the median ATR receives quality = 1.0.
If ATR is unavailable, quality defaults to 0.5 as a neutral placeholder.
**Reason:** Normalising by ATR makes the quality scale comparable across different
volatility regimes and symbol ranges.  The 3× factor was chosen so that a
structurally significant pivot (3× daily ATR prominence) earns the maximum score.
**What it approximates:** A subjective "structural importance" rating a discretionary
analyst would assign to prominent swing pivots.
**How it will be tested:** Cross-checked against visually prominent BTC/USD pivots
during Phase 3 angle validation.
**Status:** Active.  May be revised if Phase 3 analysis shows the 3× factor
produces too many or too few high-quality origins.

### Assumption 21 — Zigzag uses high/low for reversal detection, close for storage
**Date:** 2026-03-06
**Assumption:** The zigzag detector in `modules/origin_selection.py` always uses the
`high` series to detect the running peak and the `low` series to detect the running
trough when determining reversals.  The `zigzag_price_field` parameter (default
``"close"``) governs only the `origin_price` stored in the output `Origin` objects.
**Reason:** Using high/low for reversal detection makes the algorithm independent of
body position and produces pivots that capture actual intrabar extremes, not just
close-to-close moves.  The stored price can be configured independently if downstream
callers prefer close-based anchors.
**What it approximates:** Standard zigzag indicator behaviour used in technical analysis.
**How it will be tested:** Verified that high-origin records have `origin_price` matching
the `close` of the pivot bar, not the `high`, when `zigzag_price_field="close"`.
**Status:** Active.

### Assumption 22 — Zigzag skips ATR warm-up rows in ATR mode
**Date:** 2026-03-06
**Assumption:** When the zigzag detector is run in ATR-threshold mode
(`threshold_atr` is not None), the first `atr_warmup_rows` bars are skipped as the
initial anchor, because ATR values in this range are unreliable.  Bars with NaN ATR
within the valid range are also skipped silently.
**Reason:** The ATR warm-up period (default 14 bars) produces unreliable ATR values
that would make the threshold inconsistently small or NaN, potentially triggering
false reversals.
**What it approximates:** Standard ATR initialisation treatment from Assumption 13.
**How it will be tested:** Confirmed by checking that no origin at row < 14 is produced
in ATR mode.
**Status:** Active.

### Assumption 23 — Zigzag uses reversal bar ATR for threshold
**Date:** 2026-03-06
**Assumption:** In ATR-based zigzag mode, the ATR value of the bar where the reversal
is being tested (the current bar `i`) is used as the threshold reference, not the ATR
at the most recent extreme.  If `atr_14[i]` is NaN, the bar is skipped silently.
**Reason:** Using the current bar's ATR adapts the threshold to local volatility at
the moment of reversal, not at the prior extreme.  This is a minor distinction but is
documented to prevent silent inconsistency.
**What it approximates:** A volatility-adaptive reversal threshold.
**How it will be tested:** Verified by a unit test in `tests/test_phase2_origin_selection.py`.
**Status:** Active.

### Assumption 24 — Impulse extreme defined as highest high / lowest low in window
**Date:** 2026-03-06
**Assumption:** For an upward impulse (from a low origin), the extreme is the bar with
the highest `high` value within the look-ahead window, subject to early reversal
stopping.  For a downward impulse (from a high origin), the extreme is the bar with
the lowest `low`.
**Reason:** Using `high` and `low` (not `close`) captures the true intrabar extent of
the move, consistent with structural analysis conventions in the source material.
**What it approximates:** The canonical extreme of a price impulse as defined by Jenkins.
**How it will be tested:** Cross-checked against visually identified impulses during
Phase 3 validation.
**Status:** Active.

### Assumption 25 — Multiple origins at the same bar produce independent impulses
**Date:** 2026-03-06
**Assumption:** If the same bar_index appears in the origins list more than once
(e.g. once as a pivot-high and once as a zigzag-high), each origin produces an
independent Impulse object.  Deduplication is the responsibility of downstream callers.
**Reason:** The impulse detector is a pure function of its inputs; it does not assume
any uniqueness constraint on the origin list.  Callers can filter duplicates before
or after calling `detect_impulses`.
**What it approximates:** Full independence of detectors.
**How it will be tested:** Verified by passing duplicate origins and confirming the
output list length matches expectations.
**Status:** Active.

### Assumption 26 — Origins with bar_index outside the DataFrame are silently skipped
**Date:** 2026-03-06
**Assumption:** If an `Origin` has a `bar_index` that does not appear in the processed
DataFrame's `bar_index` column, the origin is silently skipped and a WARNING is logged.
No exception is raised.
**Reason:** Origins may be produced from a different dataset slice or version than the
one passed to `detect_impulses`.  Silent skipping with a warning is more resilient than
raising an exception during a batch run.
**What it approximates:** Graceful cross-dataset alignment.
**How it will be tested:** Unit test `test_origin_not_in_df_is_skipped` confirms
behaviour.
**Status:** Active.

---

## Logging rule
When a new simplification is introduced, add:
- date
- assumption
- reason
- what it approximates
- how it will later be tested or replaced
