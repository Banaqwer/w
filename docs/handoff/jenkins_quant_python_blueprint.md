# Jenkins Quant Project - Python Blueprint

## Proposed top-level structure
- `core/`
- `data/`
- `modules/`
- `signals/`
- `backtest/`
- `research/`
- `reports/`
- `tests/`

## Core objects

### `Impulse`
Fields:
- origin_time
- origin_price
- extreme_time
- extreme_price
- delta_t
- delta_p
- slope_raw
- slope_log
- quality_score
- detector_name

### `Projection`
Fields:
- module_name
- impulse_id
- projected_time
- projected_price
- time_band
- price_band
- direction_hint
- raw_score

### `ForecastZone`
Fields:
- zone_start
- zone_end
- price_low
- price_high
- support_score
- resistance_score
- turn_score
- combined_score
- modules_hit

### `TradeSignal`
Fields:
- side
- entry_time
- entry_price
- stop_price
- target_price
- confluence_score
- confirmation_type

## Core package sketch
### `core/pivots.py`
- pivot detection utilities
- multiple origin-selection methods

### `core/impulses.py`
- structural impulse extraction
- impulse quality scoring

### `modules/measured_move.py`
- vector clone generation
- endpoint projection

### `modules/adjusted_angles.py`
- impulse-aligned angle families
- fractional divisions

### `modules/jttl.py`
- JTTL generation
- root-based line construction
- line intersection utilities

### `modules/sqrt_levels.py`
- `(sqrt(P0) + k)^2` horizontal levels

### `modules/time_counts.py`
- range-to-time and row-count projections

### `modules/log_levels.py`
- semi-log transforms
- log-fraction support/resistance

### `signals/confluence.py`
- per-bar scoring
- zone merge logic

### `signals/confirmation.py`
- confirmation gates
- reversal / continuation confirmation logic

### `backtest/engine.py`
- simulation runner

### `research/ablation.py`
- module ablation runner

### `research/walkforward.py`
- rolling validation

## Design rules
- every module must be independently runnable
- no module may require chart-pixel geometry
- all module outputs must be serializable
- all experiments must reference dataset versions
- all inputs and outputs must be traceable in logs
