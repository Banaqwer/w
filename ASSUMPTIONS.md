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

### Assumption 19 — Phase 2 zigzag initialization direction
**Date:** 2026-03-06
**Assumption:** The zigzag detector (`detect_zigzag`) starts tracking in the "up"
direction from the first bar's high.  This means the very first bar's low is only
recorded as a swing-low origin if the initial high at bar 0 is subsequently reversed
downward by at least `reversal_pct` percent.
**Reason:** The classic zigzag algorithm requires an initial direction.  Starting "up"
is a documented simplification that produces correct results for all but the very first
potential low in a dataset.  For long BTC/USD datasets (3 000+ daily bars), the impact
of missing one early low is negligible.
**What it approximates:** A bidirectional initialization that simultaneously scans both
directions from bar 0.
**How it will later be tested:** Validate zigzag origin counts and alignment against a
reference implementation or visual chart comparison.
**Status:** Active.

---

### Assumption 20 — Phase 2 impulse extreme definition
**Date:** 2026-03-06
**Assumption:** For each origin, the impulse extreme is defined as the single bar with
the maximum high (upward impulse) or minimum low (downward impulse) within a forward
window of up to `max_bars=200` bars.  The window is not clipped to the next origin of
the same type.
**Reason:** A fixed `max_bars` window is simpler, more reproducible, and works regardless
of the chosen origin detector.  Clipping to the next same-type origin would couple impulse
detection to origin density, which varies across methods and parameters.
**What it approximates:** The "true" impulse ending at the structural reversal that
generated the next origin of the same type.
**How it will later be tested:** Compare with clip-to-next-origin variants in ablation.
**Status:** Active.

---

### Assumption 21 — Phase 3 log-mode angle scale reference
**Date:** 2026-03-07
**Assumption:** When computing log-space adjusted angles
(`price_mode="log"` in `compute_impulse_angles`), the per-impulse log-space
scale reference is:

    log_ppb_per_bar = log(1 + price_per_bar / origin_price)

where `price_per_bar` is the global scale basis (median ATR-14 from
`get_angle_scale_basis`) and `origin_price` is the impulse's origin price.

The log angle is then:

    angle_deg_log = degrees(atan(log(extreme / origin) / (delta_t * log_ppb_per_bar)))

At exactly `extreme / origin = (1 + price_per_bar / origin_price) ** delta_t`
the log angle equals 45°, preserving the 45°-at-scale-basis invariant in
log space.
**Reason:** Log-chart practitioners draw angles relative to the local price
level.  Using `log(1 + ppb / origin_price)` as the one-bar log "unit" anchors
the 45° line to the same ATR-derived scale as the raw mode, but expressed in
log-return space.  This makes raw and log angles directly comparable when
price levels are similar.
**What it approximates:** A hand-calibrated log-chart angle scale that a
discretionary analyst would use when drawing Gann-style lines on a log chart.
**How it will later be tested:** Compare raw-mode and log-mode angle
distributions on the BTC/USD dataset; assess whether log-mode better captures
self-similar angle families across different price epochs.
**Status:** Active.

---

### Assumption 22 — Phase 3 angles use bar_index deltas (gap-safe)
**Date:** 2026-03-07
**Assumption:** All adjusted-angle computations in `modules/adjusted_angles.py`
use `delta_t` (bar-index delta) from the stored Impulse data.  No raw
DataFrame or timestamp access is required.  For the 6H dataset
(`missing_bar_count=1`), this is gap-safe: `delta_t` counts only observed
bars, so missing bars do not distort the slope.
**Reason:** Impulse objects from Phase 2 already carry `delta_t` as a
bar-index delta.  Re-accessing the DataFrame would add a coupling dependency
and would not change the result (since Phase 2 gap handling already excluded
impulses that crossed a gap).
**What it approximates:** Angle computation on a fully continuous dataset.
**How it will later be tested:** Confirm that 6H angle distributions are
consistent with 1D distributions after normalising for scale basis.
**Status:** Active.

---

---

### Assumption 23 — JTTL horizon = 365 calendar days UTC for crypto
**Date:** 2026-03-07
**Assumption:** The default "one year" horizon for the JTTL module is 365
calendar days in UTC.  One 1D bar = one calendar day for BTC/USD (24/7
continuous market; no exchange closures or trading-day adjustments required).
The default additive sqrt-price increment is `k = 2.0` (configurable).
**Reason:** Crypto trades every calendar day.  Using 365 calendar days
captures "one year" accurately without the 252-trading-day adjustment needed
for equity markets.  `k = 2.0` is a commonly cited default in the Jenkins
source material; its optimal value is a research question.
**What it approximates:** The Jenkins JTTL projection as described in the
source PDFs.  Both `k` and horizon length are open parameters that future
ablation can test.
**How it will later be tested:** Compare JTTL target levels against observed
price reactions at the projected horizons across multiple BTC/USD epochs.
**Status:** Active.  See `DECISIONS.md` 2026-03-07 Phase 3B.1 section.

---

### Assumption 24 — Sqrt-level default increments are provisional
**Date:** 2026-03-07
**Assumption:** The default sqrt-level increments `[0.25, 0.5, 0.75, 1.0]`
(additive steps in sqrt-price space) are a provisional set based on common
Jenkins practice.  The optimal increment set is an open research question.
Down-levels where `sqrt(origin_price) - inc * step < 0` are silently
skipped (negative sqrt-price has no physical meaning).
**Reason:** The source material suggests equally spaced sqrt-price levels but
does not specify exact increment values for all markets.  Using a range of
increments allows the confluence engine (Phase 4) to score level density.
**What it approximates:** Optimal Jenkins sqrt-price level grid.
**How it will later be tested:** Ablation over increment sets in Phase 6;
compare confluence score distributions for different grids.
**Status:** Active.  Config-driven; can be changed without breaking anything.

---

### Assumption 25 — Measured-move default ratios are [0.5, 1.0, 1.5, 2.0]
**Date:** 2026-03-07
**Assumption:** The default measured-move ratio set is `[0.5, 1.0, 1.5, 2.0]`.
Ratios are applied as multiples of the impulse's signed `delta_p` (or log-space
equivalent) to generate both extension and retracement targets.
Both "raw" (linear price) and "log" (log-price space) formulas are supported.
Neither target set is a trade signal; confirmation is a Phase 4+ task.
**Reason:** These four ratios are the most commonly cited Fibonacci/extension
levels in classical measured-move analysis.  They are a starting point for the
confluence engine; optimal ratios are an open research question.
**What it approximates:** Classical Jenkins measured-move level projection.
**How it will later be tested:** Compare target levels against observed reactions
across BTC/USD epochs in Phase 6 validation.
**Status:** Active.  Config-driven; can be changed without breaking anything.

---

### Assumption 26 — Time counts use bar_index deltas (gap-safe)
**Date:** 2026-03-07
**Assumption:** All time-count arithmetic in `modules/time_counts.py` operates
on `bar_index` deltas stored in Impulse objects, not on calendar-day spans.
Because `bar_index` is a consecutive integer that counts only **present** bars,
the result is automatically correct even when the dataset has missing bars
(e.g., the 6H dataset with `missing_bar_count=1`).
This matches the gap policy established in DECISIONS.md 2026-03-06 (Phase 2)
and Assumption 18 (impulse delta_t is also a bar_index delta).
**Reason:** Calendar arithmetic would count the missing bar as elapsed time,
overstating the duration.  Bar-index arithmetic does not.
**What it approximates:** Exact market-session bar count.
**How it will later be tested:** Confirmed by the gap-safety unit tests in
`tests/test_time_counts.py`.
**Status:** Active.

---

## Logging rule
When a new simplification is introduced, add:
- date
- assumption
- reason
- what it approximates
- how it will later be tested or replaced
