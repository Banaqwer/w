"""
tests/test_projections_schema.py

Tests for signals/projections.py.

Coverage
--------
- Projection dataclass:
  - field types and defaults
  - direction_hint validation
  - raw_score range validation
  - deterministic projection_id generation
  - price-only and time-only projections
  - to_dict: all keys present, JSON-serialisable
  - ensure_id
- ConfluenceZone dataclass:
  - all fields
  - to_dict: all keys present, JSON-serialisable
- make_zone_id:
  - deterministic
  - order-independent
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from signals.projections import (
    ConfluenceZone,
    Projection,
    make_zone_id,
)

_T0 = pd.Timestamp("2021-01-01", tz="UTC")
_T1 = pd.Timestamp("2021-06-01", tz="UTC")
_T2 = pd.Timestamp("2022-01-01", tz="UTC")


def _make_proj(**kwargs) -> Projection:
    defaults = dict(
        module_name="measured_moves",
        source_id="imp_1",
        projected_time=None,
        projected_price=50000.0,
        time_band=(None, None),
        price_band=(49500.0, 50500.0),
        direction_hint="resistance",
        raw_score=0.75,
        metadata={},
    )
    defaults.update(kwargs)
    return Projection(**defaults)


# ── Projection basic ──────────────────────────────────────────────────────────


class TestProjectionBasic:
    def test_default_fields(self):
        p = _make_proj()
        assert p.module_name == "measured_moves"
        assert p.source_id == "imp_1"
        assert p.projected_price == 50000.0
        assert p.direction_hint == "resistance"
        assert p.raw_score == 0.75

    def test_projection_id_auto_generated(self):
        p = _make_proj()
        assert len(p.projection_id) == 16
        assert isinstance(p.projection_id, str)

    def test_projection_id_deterministic(self):
        p1 = _make_proj()
        p2 = _make_proj()
        assert p1.projection_id == p2.projection_id

    def test_projection_id_differs_by_source(self):
        p1 = _make_proj(source_id="imp_1")
        p2 = _make_proj(source_id="imp_2")
        assert p1.projection_id != p2.projection_id

    def test_projection_id_differs_by_price(self):
        p1 = _make_proj(projected_price=50000.0)
        p2 = _make_proj(projected_price=60000.0)
        assert p1.projection_id != p2.projection_id

    def test_invalid_direction_hint_raises(self):
        with pytest.raises(ValueError, match="direction_hint"):
            _make_proj(direction_hint="bullish")

    def test_raw_score_too_high_raises(self):
        with pytest.raises(ValueError, match="raw_score"):
            _make_proj(raw_score=1.1)

    def test_raw_score_negative_raises(self):
        with pytest.raises(ValueError, match="raw_score"):
            _make_proj(raw_score=-0.01)

    def test_raw_score_boundary_valid(self):
        p = _make_proj(raw_score=0.0)
        assert p.raw_score == 0.0
        p2 = _make_proj(raw_score=1.0)
        assert p2.raw_score == 1.0

    def test_valid_direction_hints(self):
        for hint in ("support", "resistance", "turn", "ambiguous"):
            p = _make_proj(direction_hint=hint)
            assert p.direction_hint == hint


# ── Price-only / time-only ────────────────────────────────────────────────────


class TestProjectionVariants:
    def test_price_only(self):
        p = _make_proj(
            projected_time=None,
            time_band=(None, None),
        )
        assert p.projected_time is None
        assert p.time_band == (None, None)

    def test_time_only(self):
        p = _make_proj(
            projected_price=None,
            price_band=(None, None),
            projected_time=_T0,
            time_band=(_T0, _T1),
            direction_hint="turn",
        )
        assert p.projected_price is None
        assert p.price_band == (None, None)
        assert p.projected_time == _T0

    def test_combined_price_and_time(self):
        p = _make_proj(
            projected_time=_T1,
            time_band=(_T0, _T2),
        )
        assert p.projected_time == _T1
        assert p.projected_price is not None

    def test_metadata_stored(self):
        meta = {"ratio": 1.5, "mode": "raw"}
        p = _make_proj(metadata=meta)
        assert p.metadata["ratio"] == 1.5


# ── to_dict ───────────────────────────────────────────────────────────────────


class TestProjectionToDict:
    def test_all_keys_present(self):
        p = _make_proj()
        d = p.to_dict()
        expected = {
            "projection_id", "module_name", "source_id",
            "projected_time", "projected_price",
            "time_band", "price_band",
            "direction_hint", "raw_score", "metadata",
        }
        assert expected.issubset(set(d.keys()))

    def test_json_serialisable(self):
        p = _make_proj(projected_time=_T0, time_band=(_T0, _T1))
        d = p.to_dict()
        json.dumps(d)  # must not raise

    def test_none_price_is_none(self):
        p = _make_proj(projected_price=None, price_band=(None, None))
        d = p.to_dict()
        assert d["projected_price"] is None

    def test_none_time_is_none(self):
        p = _make_proj()
        d = p.to_dict()
        assert d["projected_time"] is None

    def test_time_band_serialised(self):
        p = _make_proj(time_band=(_T0, _T1))
        d = p.to_dict()
        assert d["time_band"][0] is not None
        assert d["time_band"][1] is not None

    def test_price_band_serialised(self):
        p = _make_proj(price_band=(49000.0, 51000.0))
        d = p.to_dict()
        assert d["price_band"] == [49000.0, 51000.0]


# ── ensure_id ─────────────────────────────────────────────────────────────────


class TestEnsureId:
    def test_ensure_id_returns_self(self):
        p = _make_proj()
        assert p.ensure_id() is p

    def test_ensure_id_populates_empty(self):
        p = _make_proj()
        original_id = p.projection_id
        p.projection_id = ""
        p.ensure_id()
        assert p.projection_id == original_id


# ── ConfluenceZone ────────────────────────────────────────────────────────────


class TestConfluenceZone:
    def _make_zone(self, **kwargs) -> ConfluenceZone:
        defaults = dict(
            zone_id="abc123",
            time_window=None,
            price_window=(49000.0, 51000.0),
            contributing_projection_ids=["proj_a", "proj_b"],
            confluence_score=0.42,
            module_counts={"measured_moves": 2},
            notes="type=price_only",
        )
        defaults.update(kwargs)
        return ConfluenceZone(**defaults)

    def test_fields(self):
        z = self._make_zone()
        assert z.zone_id == "abc123"
        assert z.confluence_score == 0.42

    def test_to_dict_all_keys(self):
        z = self._make_zone()
        d = z.to_dict()
        expected = {
            "zone_id", "time_window", "price_window",
            "contributing_projection_ids", "confluence_score",
            "module_counts", "notes",
        }
        assert expected.issubset(set(d.keys()))

    def test_json_serialisable(self):
        z = self._make_zone(time_window=(_T0, _T1))
        d = z.to_dict()
        json.dumps(d)  # must not raise

    def test_time_window_none(self):
        z = self._make_zone(time_window=None)
        d = z.to_dict()
        assert d["time_window"] is None

    def test_price_window_serialised(self):
        z = self._make_zone(price_window=(45000.0, 55000.0))
        d = z.to_dict()
        assert d["price_window"] == [45000.0, 55000.0]

    def test_projection_ids_sorted(self):
        z = self._make_zone(contributing_projection_ids=["zzz", "aaa", "mmm"])
        d = z.to_dict()
        assert d["contributing_projection_ids"] == ["aaa", "mmm", "zzz"]


# ── make_zone_id ──────────────────────────────────────────────────────────────


class TestMakeZoneId:
    def test_deterministic(self):
        ids = ["proj_a", "proj_b", "proj_c"]
        assert make_zone_id(ids) == make_zone_id(ids)

    def test_order_independent(self):
        ids1 = ["proj_a", "proj_b", "proj_c"]
        ids2 = ["proj_c", "proj_a", "proj_b"]
        assert make_zone_id(ids1) == make_zone_id(ids2)

    def test_different_for_different_inputs(self):
        ids1 = ["proj_a", "proj_b"]
        ids2 = ["proj_a", "proj_c"]
        assert make_zone_id(ids1) != make_zone_id(ids2)

    def test_single_id(self):
        z = make_zone_id(["only_one"])
        assert isinstance(z, str) and len(z) == 16
