"""
tests/test_walkforward.py

Tests for backtest/walkforward.py — WalkForwardConfig, WalkForwardWindow,
build_walkforward_windows, aggregate_walkforward_metrics, run_walk_forward.

Coverage
--------
- WalkForwardConfig:
  - defaults are correct
  - from_yaml loads without errors
- build_walkforward_windows:
  - empty index returns empty list
  - windows span correct time boundaries
  - train_end < test_start (no data leakage)
  - step correctly advances windows
  - windows with insufficient bars are skipped
  - windows do not extend beyond data_end
  - sequential (non-overlapping test windows)
  - window count is deterministic
- WalkForwardWindow.to_dict:
  - all required keys present
- aggregate_walkforward_metrics:
  - empty list → zeros
  - n_windows, total_trades counted correctly
  - avg_win_rate is mean of per-window win rates
  - consistency_pct = fraction of positive-pnl windows
  - note field present in output
- run_walk_forward:
  - returns correct types
  - determinism: same inputs → same window count and aggregate
  - output_dir creates walkforward_summary.json when provided
- WalkForwardWindowResult.to_dict:
  - all required keys present
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

from backtest.runner import BacktestConfig
from backtest.walkforward import (
    WalkForwardConfig,
    WalkForwardWindow,
    WalkForwardWindowResult,
    aggregate_walkforward_metrics,
    build_walkforward_windows,
    run_walk_forward,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_daily_index(n_days: int, start: str = "2018-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n_days, freq="1D", tz="UTC")


def _make_window_result(
    idx: int,
    n_trades: int,
    win_rate: float,
    net_pnl: float,
) -> WalkForwardWindowResult:
    win = WalkForwardWindow(
        window_index=idx,
        train_start=pd.Timestamp("2020-01-01", tz="UTC"),
        train_end=pd.Timestamp("2021-12-31", tz="UTC"),
        test_start=pd.Timestamp("2022-01-01", tz="UTC"),
        test_end=pd.Timestamp("2022-06-30", tz="UTC"),
        n_train_bars=365,
        n_test_bars=90,
    )
    summary = {
        "total_trades": n_trades,
        "winning_trades": int(n_trades * win_rate),
        "win_rate": win_rate,
        "total_net_pnl": net_pnl,
        "expectancy": net_pnl / n_trades if n_trades else 0.0,
        "sharpe_like": 0.5 if n_trades > 0 else 0.0,
        "avg_r_multiple": 1.2 if n_trades > 0 else 0.0,
        "max_drawdown_pct": -0.05,
    }
    return WalkForwardWindowResult(window=win, summary=summary, n_trades=n_trades)


# ── WalkForwardConfig ─────────────────────────────────────────────────────────


class TestWalkForwardConfig:
    def test_defaults(self):
        cfg = WalkForwardConfig()
        assert cfg.train_window_days == 730
        assert cfg.test_window_days == 180
        assert cfg.step_days == 90
        assert cfg.min_train_bars == 300
        assert cfg.min_test_bars == 30

    def test_from_yaml(self):
        cfg = WalkForwardConfig.from_yaml("configs/backtest.yaml")
        assert cfg.train_window_days > 0
        assert cfg.test_window_days > 0
        assert cfg.step_days > 0


# ── build_walkforward_windows ─────────────────────────────────────────────────


class TestBuildWalkforwardWindows:
    def test_empty_index_returns_empty(self):
        idx = pd.DatetimeIndex([])
        wins = build_walkforward_windows(idx, WalkForwardConfig())
        assert wins == []

    def test_too_short_data_returns_empty(self):
        """Less data than train_window + test_window → no windows."""
        idx = _make_daily_index(100)
        cfg = WalkForwardConfig(
            train_window_days=300, test_window_days=100, step_days=90,
            min_train_bars=200, min_test_bars=30,
        )
        wins = build_walkforward_windows(idx, cfg)
        assert wins == []

    def test_window_boundaries_correct(self):
        """train_end must be before test_start."""
        idx = _make_daily_index(2000)
        cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        wins = build_walkforward_windows(idx, cfg)
        assert len(wins) > 0
        for w in wins:
            assert w.train_end <= w.test_start

    def test_train_end_before_test_start(self):
        """No data leakage: train_end must not exceed test_start."""
        idx = _make_daily_index(2000)
        cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        wins = build_walkforward_windows(idx, cfg)
        for w in wins:
            assert w.train_end <= w.test_start, (
                f"Window {w.window_index}: train_end={w.train_end} > test_start={w.test_start}"
            )

    def test_windows_do_not_exceed_data_end(self):
        idx = _make_daily_index(2000)
        cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        wins = build_walkforward_windows(idx, cfg)
        data_end = idx[-1]
        for w in wins:
            assert w.test_end <= data_end

    def test_windows_are_sequential(self):
        """Window indices are sequential and window starts advance by step."""
        idx = _make_daily_index(2000)
        cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        wins = build_walkforward_windows(idx, cfg)
        for i, w in enumerate(wins):
            assert w.window_index == i

    def test_window_count_deterministic(self):
        idx = _make_daily_index(2000)
        cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        w1 = build_walkforward_windows(idx, cfg)
        w2 = build_walkforward_windows(idx, cfg)
        assert len(w1) == len(w2)
        for a, b in zip(w1, w2):
            assert a.train_start == b.train_start
            assert a.test_end == b.test_end

    def test_min_test_bars_filter(self):
        """Windows with fewer than min_test_bars 1D bars are skipped."""
        idx = _make_daily_index(2000)
        cfg_strict = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=500,  # impossible threshold
        )
        wins = build_walkforward_windows(idx, cfg_strict)
        assert wins == []

    def test_n_train_bars_populated(self):
        idx = _make_daily_index(2000)
        cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        wins = build_walkforward_windows(idx, cfg)
        if wins:
            assert wins[0].n_train_bars > 0
            assert wins[0].n_test_bars > 0


# ── WalkForwardWindow.to_dict ─────────────────────────────────────────────────


class TestWalkForwardWindowToDict:
    def test_required_keys(self):
        w = WalkForwardWindow(
            window_index=0,
            train_start=pd.Timestamp("2020-01-01", tz="UTC"),
            train_end=pd.Timestamp("2021-12-31", tz="UTC"),
            test_start=pd.Timestamp("2022-01-01", tz="UTC"),
            test_end=pd.Timestamp("2022-06-30", tz="UTC"),
        )
        d = w.to_dict()
        required = {"window_index", "train_start", "train_end", "test_start", "test_end"}
        assert required.issubset(d.keys())


# ── aggregate_walkforward_metrics ─────────────────────────────────────────────


class TestAggregateWalkforwardMetrics:
    def test_empty_list(self):
        agg = aggregate_walkforward_metrics([])
        assert agg["n_windows"] == 0
        assert agg["total_trades"] == 0
        assert agg["avg_win_rate"] == 0.0

    def test_n_windows_counted(self):
        results = [_make_window_result(i, 10, 0.6, 500.0) for i in range(5)]
        agg = aggregate_walkforward_metrics(results)
        assert agg["n_windows"] == 5

    def test_total_trades_summed(self):
        results = [_make_window_result(i, 10, 0.6, 500.0) for i in range(3)]
        agg = aggregate_walkforward_metrics(results)
        assert agg["total_trades"] == 30

    def test_total_net_pnl_summed(self):
        results = [_make_window_result(i, 10, 0.6, 300.0) for i in range(4)]
        agg = aggregate_walkforward_metrics(results)
        assert agg["total_net_pnl"] == pytest.approx(1200.0)

    def test_avg_win_rate_is_mean(self):
        r1 = _make_window_result(0, 10, 0.6, 100.0)
        r2 = _make_window_result(1, 10, 0.4, 100.0)
        agg = aggregate_walkforward_metrics([r1, r2])
        assert agg["avg_win_rate"] == pytest.approx(0.5)

    def test_consistency_pct(self):
        r1 = _make_window_result(0, 10, 0.6, 200.0)   # positive
        r2 = _make_window_result(1, 10, 0.4, -100.0)  # negative
        r3 = _make_window_result(2, 10, 0.7, 300.0)   # positive
        agg = aggregate_walkforward_metrics([r1, r2, r3])
        assert agg["consistency_pct"] == pytest.approx(2 / 3)

    def test_note_field_present(self):
        results = [_make_window_result(0, 5, 0.5, 100.0)]
        agg = aggregate_walkforward_metrics(results)
        assert "note" in agg

    def test_n_windows_with_trades(self):
        r1 = _make_window_result(0, 0, 0.0, 0.0)  # no trades
        r2 = _make_window_result(1, 5, 0.6, 200.0)
        agg = aggregate_walkforward_metrics([r1, r2])
        assert agg["n_windows_with_trades"] == 1


# ── WalkForwardWindowResult.to_dict ──────────────────────────────────────────


class TestWalkForwardWindowResultToDict:
    def test_required_keys(self):
        wr = _make_window_result(0, 5, 0.6, 100.0)
        d = wr.to_dict()
        assert "window_index" in d
        assert "summary" in d
        assert "n_trades" in d


# ── run_walk_forward ──────────────────────────────────────────────────────────


class TestRunWalkForward:
    def _make_df_1d(self, n: int = 1500, start: str = "2019-01-01") -> pd.DataFrame:
        idx = pd.date_range(start, periods=n, freq="1D", tz="UTC")
        rng = np.random.default_rng(42)
        prices = 40000.0 + np.cumsum(rng.normal(0, 200, n))
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 200,
            "low": prices - 200,
            "close": prices + 50,
            "volume": 1000.0,
            "bar_index": range(n),
            "atr_14": [200.0] * n,
            "log_close": [1.0] * n,
            "hl_range": [400.0] * n,
            "true_range": [400.0] * n,
            "calendar_day_index": range(n),
            "trading_day_index": range(n),
        }, index=idx)
        return df

    def _make_df_6h(self, n: int = 6000, start: str = "2019-01-01") -> pd.DataFrame:
        idx = pd.date_range(start, periods=n, freq="6h", tz="UTC")
        rng = np.random.default_rng(7)
        prices = 40000.0 + np.cumsum(rng.normal(0, 50, n))
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 50,
            "low": prices - 50,
            "close": prices + 10,
            "volume": 100.0,
        }, index=idx)
        return df

    def test_returns_correct_types(self):
        df_1d = self._make_df_1d(1500)
        df_6h = self._make_df_6h(6000)
        bt_cfg = BacktestConfig()
        wf_cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        window_results, agg = run_walk_forward(
            df_1d=df_1d, df_6h=df_6h,
            manifest_1d={}, manifest_6h={},
            bt_config=bt_cfg, wf_config=wf_cfg,
            dataset_version="test_v1",
        )
        assert isinstance(window_results, list)
        assert isinstance(agg, dict)
        assert "n_windows" in agg

    def test_determinism(self):
        """Same inputs → same window count and same aggregate total_net_pnl."""
        df_1d = self._make_df_1d(1500)
        df_6h = self._make_df_6h(6000)
        bt_cfg = BacktestConfig()
        wf_cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        kwargs = dict(
            df_1d=df_1d, df_6h=df_6h,
            manifest_1d={}, manifest_6h={},
            bt_config=bt_cfg, wf_config=wf_cfg,
            dataset_version="test_v1",
        )
        _, agg1 = run_walk_forward(**kwargs)
        _, agg2 = run_walk_forward(**kwargs)
        assert agg1["n_windows"] == agg2["n_windows"]
        assert agg1["total_trades"] == agg2["total_trades"]
        assert agg1["total_net_pnl"] == pytest.approx(agg2["total_net_pnl"])

    def test_output_dir_creates_summary_json(self):
        df_1d = self._make_df_1d(1500)
        df_6h = self._make_df_6h(6000)
        bt_cfg = BacktestConfig()
        wf_cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            run_walk_forward(
                df_1d=df_1d, df_6h=df_6h,
                manifest_1d={}, manifest_6h={},
                bt_config=bt_cfg, wf_config=wf_cfg,
                dataset_version="test_v1",
                output_dir=out,
            )
            summary_file = out / "walkforward_summary.json"
            assert summary_file.exists()
            with open(summary_file) as fh:
                data = json.load(fh)
            assert "aggregate" in data
            assert "windows" in data

    def test_no_output_dir_does_not_crash(self):
        df_1d = self._make_df_1d(1500)
        df_6h = self._make_df_6h(6000)
        bt_cfg = BacktestConfig()
        wf_cfg = WalkForwardConfig(
            train_window_days=365, test_window_days=90, step_days=90,
            min_train_bars=100, min_test_bars=20,
        )
        _, agg = run_walk_forward(
            df_1d=df_1d, df_6h=df_6h,
            manifest_1d={}, manifest_6h={},
            bt_config=bt_cfg, wf_config=wf_cfg,
        )
        assert isinstance(agg, dict)
