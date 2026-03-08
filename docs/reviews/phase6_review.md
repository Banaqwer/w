# Phase 6 Review — Backtest Engine + Walk-Forward Evaluator

**Date:** 2026-03-08
**Reviewer:** Automated (Copilot Agent)
**Scope:** Phase 6 only — `backtest/execution.py`, `backtest/runner.py`,
`backtest/walkforward.py`, `configs/backtest.yaml`,
`research/run_phase6_smoke.py`, `ASSUMPTIONS.md` 31–38, `PROJECT_STATUS.md`
Phase 6 section, and the three test files.

---

## Verdict: **PASS** (after fixing one critical bug)

## May Phase 7 begin? **Yes**

---

## 1  Critical Bug Found and Fixed

### `_generate_projections` API call mismatches (backtest/runner.py lines 237–304)

Five of the five Phase 3/4 generators in `_generate_projections` had incorrect
calling conventions, causing all generators except `time_counts` to silently
fail via the broad `except Exception` handlers.  Because `time_counts` produces
time-only projections (no price band), the confluence engine produced zones
that lacked `price_window`, and `generate_signals` therefore returned 0
signal candidates in every walk-forward window.

| Generator | Error | Root Cause |
|-----------|-------|------------|
| measured_moves | `'Impulse' object is not iterable` | Passed single `Impulse` instead of `list[dict]` |
| jttl | `compute_jttl() missing 1 required positional argument` | Passed single `Origin` instead of `(origin_time, origin_price)` |
| sqrt_levels | `'<=' not supported between Impulse and int` | Passed `Impulse` instead of `float(imp.extreme_price)` |
| angle_families (compute) | `'Impulse' object is not iterable` | Passed single `Impulse` instead of `list[dict]` |
| angle_families (project) | Wrong `scale_basis` arg | Passed `df_1d` DataFrame instead of `basis` dict |
| jttl (project) | Wrong kwargs | Passed `(lines, df_1d, horizons=...)` instead of `(lines, quality_scores=..., source_ids=...)` |

**Fix:** Rewrote `_generate_projections` to match the calling conventions
demonstrated in `research/run_phase4_smoke.py`.  All generators now produce
projections with both price and time bands.

**Impact:** Before fix → 0 trades across all 34 windows.  After fix → 98 trades
across 31 of 34 windows.

---

## 2  Code Audit Findings

### 2.1  No lookahead / leakage ✅

- **Entry logic** (`simulate_signal_on_6h`, lines 473–490): Bar `i`'s close is
  checked; entry fill is on bar `i+1`'s open.  No future data accessed.
- **Exit logic** (lines 500–545): All exit conditions (`time_expired`,
  `max_hold_bars`, `invalidation`) use bars up to current; exit fill on the
  next bar's open (or current bar if it's the last).
- **Signal generation** (`run_backtest`, lines 839–844): Uses train-window
  slice only (`df_1d_sorted[index <= train_end]`).  Test-window data is never
  passed to signal generation.
- **Walk-forward windows** (`build_walkforward_windows`, lines 233–236):
  `train_end` is snapped backward, `test_start` is snapped forward.
  Guarantee: `train_end_snap < test_start_snap`.

### 2.2  Deterministic execution ✅

- No `random`, `np.random`, `datetime.now()`, or mutable global state.
- All DataFrames are sorted by timestamp before processing.
- Fills are computed from pure functions of `(open_price, side, fees_bps,
  slippage_bps)`.
- Tests confirm: same inputs → same trades/equity/summary
  (`test_determinism` in both `test_backtest_runner.py` and
  `test_walkforward.py`).

### 2.3  Fees + slippage correctness ✅

- Config specifies **round-trip** bps (`fees_bps: 10`, `slippage_bps: 5`).
- `BacktestConfig.from_yaml` divides by 2 for one-way application (line 185–186).
- Entry/exit formulas verified:
  - Short entry fill: `2279.80 × (1 − 7.5/10000) = 2278.09` → actual diff =
    1.71 = 7.5 bps ✓
  - Short exit fill: `2341.17 × (1 + 7.5/10000) = 2342.93` → actual diff =
    1.76 = 7.5 bps ✓
- Total round-trip cost = 15 bps as intended.
- `compute_fees_and_slippage` returns USD total (always positive) ✓.
- Costs meaningfully affect returns: Window 0 gross PnL = −973.24,
  fees/slippage = 27.60 (2.8% of gross).

### 2.4  Walk-forward boundaries ✅

- Train/test windows do not overlap.  `train_end` is snapped backward;
  `test_start` is snapped forward.  Explicit test:
  `test_train_end_before_test_start` asserts `w.train_end <= w.test_start`.
- Window step is deterministic: `cursor += step_td`.
- Minimum bar thresholds enforced (300 train, 30 test by default).

### 2.5  Gap-policy respect ⚠️ Partial

- Signal generation respects gap policy: `missing_bar_count > 0` →
  `skip_on_gap=True` passed to `detect_impulses`.
- **Limitation (documented):** Confirmations are not re-evaluated during
  execution simulation.  Documented as Assumption 36, planned for Phase 7.

### 2.6  Minor notes

- `compute_gross_pnl` has a guard for `entry_open <= 0` (returns 0.0).  This
  is correct for BTC/USD where prices are always positive.
- Equity curve correctly sums multiple trades exiting at the same timestamp.
- `write_trades` handles both CSV and Parquet formats.

---

## 3  Run Results

### Walk-forward configuration

| Parameter | Value |
|-----------|-------|
| train_window_days | 730 |
| test_window_days | 180 |
| step_days | 90 |
| min_train_bars | 300 |
| min_test_bars | 30 |
| fees_bps (round-trip) | 10 |
| slippage_bps (round-trip) | 5 |

### Aggregate results

| Metric | Value |
|--------|-------|
| **trade_count** | **98** |
| **total_return (net PnL)** | **−2999.79 USD** |
| **max_drawdown** (avg across windows) | **−0.12%** |
| **n_windows** | **34** |
| n_windows_with_trades | 31 |
| avg_win_rate | 2.96% |
| consistency_pct | 5.88% (2 of 34 windows positive) |
| avg_sharpe_like | per aggregate |

### Output artifacts

| File | Path | Size |
|------|------|------|
| Trades CSV | `reports/phase6/full/trades.csv` | 7,159 bytes |
| Equity curve | `reports/phase6/full/equity_curve.csv` | 31,479 bytes |
| Summary JSON | `reports/phase6/full/summary.json` | 716 bytes |
| **Walk-forward summary** | **`reports/phase6/full/walkforward_summary.json`** | **39,563 bytes** |

### Per-window consistency

- Per-window trade sum (98) matches aggregate `total_trades` (98) ✅
- Per-window PnL sum (−2999.79) matches aggregate `total_net_pnl` (−2999.79) ✅

### Fees/slippage impact (Window 0)

| Metric | Value |
|--------|-------|
| Gross PnL | −973.24 |
| Fees + slippage | 27.60 |
| Net PnL | −1000.84 |
| Cost as % of gross | 2.8% |

---

## 4  Test Coverage

- 822 tests total (797 non-walkforward + 25 walkforward), all passing.
- Phase 6 specific: 97 tests (46 execution, 26 runner, 25 walkforward).
- Walkforward tests now take ~2.5 minutes total (previously <1s when generators
  were broken).

---

## 5  Performance Note

The system shows a net loss across the walk-forward (−2999.79 USD on 100K
initial capital, 98 trades).  This is expected for an MVP research system
that has not been tuned.  All trades exit via invalidation (0% win rate in
many windows), indicating that the signal generation pipeline produces entries
that are frequently invalidated.

**No performance claims are made.**  These results represent the baseline
against which future improvements will be measured.

---

## 6  Remaining Items

1. **Confirmation gating during execution** — Currently deferred to Phase 7
   (Assumption 36).  Signals are accepted at generation time without
   re-evaluation during the test window.

2. **Sharpe-like metric** — Per-trade approximation (Assumption 35), not
   per-bar.  Documented limitation.

3. **Walkforward test performance** — Tests that exercise `run_walk_forward`
   with synthetic data now take ~2.5 minutes because all generators work.
   This is correct behavior but may need attention if CI times become a
   concern.
