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

---

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

---

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

---

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

---

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

---

## Phase 0 correction-pass assumptions (added 2026-03-04)

### Assumption 13 — Python environment and package manager
**Date:** 2026-03-04
**Assumption:** `uv` is the assumed package manager and environment tool for this project.
The `pyproject.toml` uses `setuptools.build_meta` as the build backend. Runtime dependencies
are installed via `pip install -e .` (or `uv pip install -e .`). Dev/test dependencies
(pytest) are installed via `pip install -e ".[dev]"` (or `uv pip install -e ".[dev]"`).
No other package manager (conda, poetry, pipenv) is assumed without a DECISIONS.md entry.
**Reason:** `uv` is already in use as the launch mechanism for the `tradingview-mcp` server
(`uv tool run --from ...`). Consistency with the existing toolchain is the default.
`setuptools.build_meta` is the standard, stable setuptools PEP 517 backend. The
`setuptools.backends.legacy:build` path is non-standard and deprecated.
**What it approximates:** A stable, reproducible Python build and dependency environment.
**How it will be tested:** Phase 1 begins by running `uv pip install -e ".[dev]"` and
confirming that `pytest` is importable and that the package is importable as `import core`.
**If uv is unavailable:** Fall back to `pip` with the same `pyproject.toml`. The project
must not depend on uv-specific features beyond the standard PEP 517 build interface.
**Status:** Provisional. Toolchain choice can be changed via DECISIONS.md.

---

### Assumption 14 — ATR warmup NaN handling policy
**Date:** 2026-03-04
**Assumption:** Rolling ATR(n) computation produces NaN for the first n−1 rows of each
`atr_n` column in every processed dataset (e.g. `atr_14` has NaN for rows 0–12).
These NaN rows are **valid and expected**. They do NOT cause ingestion to fail.
Validation logic must explicitly allow NaN in `atr_n` columns within the warmup window.
**Reason:** Rolling windows cannot be computed until n observations have accumulated.
This is standard statistical behavior and cannot be avoided without inventing data.
The alternative (pre-filling with the first valid ATR value or using `ewm`) would
produce synthetic data, which is prohibited in the official MVP dataset.
**What it approximates:** A complete ATR series from bar 0. The warmup period is
unavoidable data loss from the rolling window method.
**How it will be tested:**
- `test_validation.py` confirms that `atr_14` is NaN for rows 0–12 and the
  validation pipeline does NOT raise an error for this.
- `test_validation.py` confirms that `atr_14` is non-null for rows 13 onward.
- The dataset manifest records warmup counts: `"atr_warmup_rows": {"atr_14": 13}`.
**Impact on modules:** Modules that require a non-null ATR at the impulse origin bar
(e.g. the angle scaling contract in `get_angle_scale_basis`) must:
- skip origin candidates whose `bar_index` falls within the ATR warmup window, or
- extend the raw extract to provide sufficient pre-history before the first structural event.
Modules must never fill or impute ATR warmup NaN rows.
**Status:** Documented expected behavior. Not a blocker. Policy is enforced at the
validation and module level.

---

## Logging rule
When a new simplification is introduced, add:
- date
- assumption
- reason
- what it approximates
- how it will later be tested or replaced
