#!/usr/bin/env python3
"""Fault-Injection Engine & Synthetic Test Fixture Generation for Solar Telemetry.

Task: S2-Both-01
Implements:
- Fault-Injection Engine introducing realistic field solar anomalies into base datasets:
    * Soiling: Progressive multi-day degradation of power generation simulating dust/soiling accumulation.
    * Ramp / Trip: Abrupt inverter tripping during peak generation creating severe negative step-gradients and zero power.
    * Clipping: Flat horizontal ceiling threshold capping peak generation during maximum solar noon.
    * Flatline: Frozen sensor telemetry repeating identical non-zero values across consecutive intervals.
- Synchronized Output Generation:
    * Surya-A-demo.csv (or configured output path): Corrupted dataset with identical schema and row order.
    * ground_truth_anomalies.json: Explicit JSON answer key mapping exact timestamps, row indexes,
      device keys, affected columns, and anomaly types for downstream validation and AI model benchmarking.
- Robust Typer CLI with rich terminal reports, parameter configuration, and deterministic seeding.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import json
import os
from pathlib import Path
import random
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import polars as pl
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

# Ensure project root in sys.path
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

app = typer.Typer(
    name="inject-faults",
    help="PlantIQ Fault-Injection Engine & Synthetic Test Fixture Generator",
    add_completion=False,
)
console = Console()

DEFAULT_INPUT_FILE = Path(_project_root) / "Datasets" / "Plant_1_Generation_Data.csv"
DEFAULT_OUTPUT_CSV = Path(_project_root) / "Datasets" / "Surya-A-demo.csv"
DEFAULT_GROUND_TRUTH_JSON = Path(_project_root) / "Datasets" / "ground_truth_anomalies.json"

# Known Timestamp Formats for Candidate Matching
TIMESTAMP_FORMATS: List[str] = [
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
]


def _to_float(val: Any, default: float = 0.0) -> float:
    """Safely convert any numeric value or scalar to float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class AnomalyType(str, Enum):
    """Supported solar telemetry anomaly categories."""

    SOILING = "soiling"
    TRIP = "trip"
    CLIPPING = "clipping"
    FLATLINE = "flatline"


@dataclass
class FaultConfig:
    """Runtime parameters and controls for fault-injection pipeline."""

    seed: int = 42
    severity: float = 1.0  # Scales anomaly magnitudes/degradation rates
    include_soiling: bool = True
    include_trip: bool = True
    include_clipping: bool = True
    include_flatline: bool = True

    # Soiling parameters
    soiling_days: int = 7
    soiling_max_degradation: float = 0.35  # 35% degradation at peak
    soiling_start_date: Optional[Union[str, date, datetime]] = None

    # Trip parameters
    trip_duration_steps: int = 16  # 4 hours at 15-min cadence
    trip_residual_power: float = 0.0
    trip_start_time: Optional[Union[str, datetime]] = None

    # Clipping parameters
    clipping_ratio: float = 0.65  # Cap at 65% of max observed AC power
    clipping_threshold_ac: Optional[float] = None
    clipping_threshold_dc: Optional[float] = None
    clipping_days: int = 5
    clipping_start_date: Optional[Union[str, date, datetime]] = None

    # Flatline parameters
    flatline_duration_steps: int = 8  # 2 hours at 15-min cadence
    flatline_value: Optional[float] = None
    flatline_start_time: Optional[Union[str, datetime]] = None

    # Device Target Overrides (if None, auto-assigned from available devices)
    target_inverter_soiling: Optional[str] = None
    target_inverter_trip: Optional[str] = None
    target_inverter_clipping: Optional[str] = None
    target_inverter_flatline: Optional[str] = None

    # Yield consistency
    adjust_yield: bool = True


@dataclass
class InjectedEvent:
    """High-level macro description of an injected solar anomaly episode."""

    event_id: str
    anomaly_type: str
    device_id: Optional[str]
    columns: List[str]
    start_timestamp: str
    end_timestamp: str
    affected_row_count: int
    parameters: Dict[str, Any]
    row_indexes: List[int]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize event to dictionary."""
        return asdict(self)


@dataclass
class RowModification:
    """Detailed ground-truth modification entry for a single data row."""

    row_index: int
    timestamp: str
    device_id: Optional[str]
    anomaly_types: List[str]
    event_ids: List[str]
    modifications: Dict[str, Dict[str, float]]  # col -> {"original": x, "corrupted": y}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize row modification to dictionary."""
        return asdict(self)


@dataclass
class GroundTruthManifest:
    """Complete ground-truth container and metadata manifest."""

    metadata: Dict[str, Any]
    events: List[InjectedEvent]
    row_ground_truth: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to JSON-serializable dictionary."""
        return {
            "metadata": self.metadata,
            "events": [e.to_dict() for e in self.events],
            "row_ground_truth": self.row_ground_truth,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize manifest to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, output_path: Union[str, Path]) -> None:
        """Save ground truth manifest to disk."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())


# ---------------------------------------------------------------------------
# Utility Functions: Column & Timestamp Detection
# ---------------------------------------------------------------------------


def detect_dataset_columns(
    df: pl.DataFrame,
) -> Tuple[str, Optional[str], List[str], Optional[str]]:
    """Intelligently detect timestamp, device, power, and yield columns."""
    cols = df.columns

    # 1. Timestamp column detection
    ts_candidates = [
        "DATE_TIME",
        "date_time",
        "Date-Time",
        "timestamp",
        "Timestamp",
        "datetime",
        "DATETIME",
        "date",
        "DATE",
        "time",
    ]
    ts_col: Optional[str] = None
    for cand in ts_candidates:
        if cand in cols:
            ts_col = cand
            break

    if ts_col is None:
        # Fallback: check temporal dtypes
        for col_name in cols:
            if df[col_name].dtype.is_temporal():
                ts_col = col_name
                break

    if ts_col is None:
        raise ValueError(
            f"Could not automatically detect timestamp column in dataset. Columns: {cols}"
        )

    # 2. Device column detection
    device_candidates = [
        "SOURCE_KEY",
        "source_key",
        "Inverter_ID",
        "inverter_id",
        "device_id",
        "DEVICE_ID",
        "asset_id",
        "ASSET_ID",
        "inverter",
    ]
    device_col: Optional[str] = None
    for cand in device_candidates:
        if cand in cols:
            device_col = cand
            break

    # 3. Power columns detection
    power_cols: List[str] = []
    preferred_power_order = [
        "AC_POWER",
        "DC_POWER",
        "ac_power",
        "dc_power",
        "AC_Power",
        "DC_Power",
        "active_power",
        "power_ac",
        "power_dc",
    ]
    for cand in preferred_power_order:
        if cand in cols and cand not in power_cols:
            power_cols.append(cand)

    # If none found by exact name, regex search for numeric power columns
    if not power_cols:
        for c in cols:
            if re.search(r"(power|kw|watt|ac_p|dc_p)", c, re.IGNORECASE) and df[c].dtype.is_numeric():
                if c not in power_cols:
                    power_cols.append(c)

    if not power_cols:
        # If still none found, select any numeric telemetry column that is not plant_id
        for c in cols:
            if (
                df[c].dtype.is_numeric()
                and c != ts_col
                and c != device_col
                and "id" not in c.lower()
            ):
                power_cols.append(c)

    # 4. Daily yield column detection
    yield_candidates = ["DAILY_YIELD", "daily_yield", "Daily_Yield", "yield_daily", "energy_daily"]
    yield_col: Optional[str] = None
    for cand in yield_candidates:
        if cand in cols:
            yield_col = cand
            break

    return ts_col, device_col, power_cols, yield_col


def parse_timestamps(series: pl.Series) -> pl.Series:
    """Parse string or temporal series to pl.Datetime safely without modifying original."""
    if series.dtype.is_temporal():
        return series.cast(pl.Datetime)

    if series.dtype == pl.String:
        sample = series.drop_nulls()
        if len(sample) == 0:
            return pl.Series("parsed_dt", [], dtype=pl.Datetime)

        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = series.str.strptime(pl.Datetime, fmt, strict=False)
                valid_count = len(parsed.drop_nulls())
                if valid_count / max(1, len(sample)) >= 0.8:
                    return parsed
            except Exception:
                continue

        # Generic polars parser
        try:
            parsed = series.str.to_datetime(strict=False)
            valid_count = len(parsed.drop_nulls())
            if valid_count / max(1, len(sample)) >= 0.8:
                return parsed
        except Exception:
            pass

    raise ValueError(f"Unable to parse timestamp series '{series.name}' into Datetime.")


# ---------------------------------------------------------------------------
# Individual Fault Injection Functions
# ---------------------------------------------------------------------------


def inject_soiling(
    df: pl.DataFrame,
    target_device: Optional[str] = None,
    power_cols: Optional[List[str]] = None,
    yield_col: Optional[str] = None,
    start_date: Optional[Union[str, date, datetime]] = None,
    duration_days: int = 7,
    max_degradation: float = 0.35,
    event_id: str = "soil-001",
    timestamp_col: Optional[str] = None,
    device_col: Optional[str] = None,
    adjust_yield: bool = True,
) -> Tuple[pl.DataFrame, InjectedEvent, List[RowModification]]:
    """Inject progressive multi-day soiling degradation into target device generation."""
    ts_c, dev_c, default_power, default_yield = detect_dataset_columns(df)
    timestamp_col = timestamp_col or ts_c
    device_col = device_col if device_col is not None else dev_c
    power_cols = power_cols or default_power
    yield_col = yield_col or default_yield

    # Annotate with row index and parsed datetime
    row_count = len(df)
    parsed_dt = parse_timestamps(df[timestamp_col])
    temp_df = df.with_columns(
        pl.int_range(0, row_count).alias("__row_idx__"),
        parsed_dt.alias("__parsed_dt__"),
    )

    # Filter target device
    if device_col and target_device:
        device_mask = temp_df[device_col] == target_device
    else:
        device_mask = pl.Series([True] * row_count)

    sub_df = temp_df.filter(device_mask)
    if len(sub_df) == 0:
        raise ValueError(f"No records found for target device '{target_device}'")

    # Determine start and end date
    valid_dates = sub_df["__parsed_dt__"].dt.date().unique().sort().drop_nulls().to_list()
    if not valid_dates:
        raise ValueError("No valid chronological dates available for soiling injection")

    if start_date is not None:
        if isinstance(start_date, str):
            for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"]:
                try:
                    s_date: date = datetime.strptime(start_date, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                s_date = datetime.fromisoformat(start_date).date()
        elif isinstance(start_date, datetime):
            s_date = start_date.date()
        else:
            s_date = start_date
    else:
        # Default start: around day 5 (or first quarter of chronological span)
        start_idx = min(5, max(0, len(valid_dates) - duration_days - 1))
        s_date = valid_dates[start_idx]

    e_date = s_date + timedelta(days=duration_days)

    # Window condition
    in_window_mask = (
        device_mask
        & (temp_df["__parsed_dt__"].dt.date() >= s_date)
        & (temp_df["__parsed_dt__"].dt.date() <= e_date)
    )

    window_indices = temp_df.filter(in_window_mask)["__row_idx__"].to_list()
    if not window_indices:
        raise ValueError(
            f"No data rows found within soiling window [{s_date} to {e_date}] for device '{target_device}'"
        )

    t_start_dt = temp_df.filter(pl.col("__row_idx__") == window_indices[0])["__parsed_dt__"][0]
    t_end_dt = temp_df.filter(pl.col("__row_idx__") == window_indices[-1])["__parsed_dt__"][0]
    total_window_seconds = max(1.0, (t_end_dt - t_start_dt).total_seconds())

    # Prepare mutable copies of target columns
    col_arrays: Dict[str, List[float]] = {}
    for col_name in power_cols:
        col_arrays[col_name] = [float(v) if v is not None else 0.0 for v in df[col_name].to_list()]

    yield_array: Optional[List[float]] = None
    if adjust_yield and yield_col and yield_col in df.columns:
        yield_array = [float(v) if v is not None else 0.0 for v in df[yield_col].to_list()]

    dt_series = temp_df["__parsed_dt__"]
    row_modifications: List[RowModification] = []
    affected_rows: List[int] = []

    # Apply progressive degradation
    current_day: Optional[date] = None
    day_cumulative_delta_kwh: float = 0.0

    for idx in window_indices:
        row_dt = dt_series[idx]
        if row_dt is None:
            continue

        # Check if day rolled over for yield accumulation
        r_date = row_dt.date()
        if r_date != current_day:
            current_day = r_date
            day_cumulative_delta_kwh = 0.0

        elapsed_s = max(0.0, (row_dt - t_start_dt).total_seconds())
        progress_ratio = min(1.0, elapsed_s / total_window_seconds)
        degradation_factor = progress_ratio * max_degradation
        multiplier = max(0.0, 1.0 - degradation_factor)

        row_mods: Dict[str, Dict[str, float]] = {}
        delta_p_ac = 0.0

        for col_name in power_cols:
            orig_val = col_arrays[col_name][idx]
            if orig_val > 0.0:
                new_val = round(orig_val * multiplier, 4)
                col_arrays[col_name][idx] = new_val
                row_mods[col_name] = {"original": orig_val, "corrupted": new_val}
                if "ac" in col_name.lower():
                    delta_p_ac = orig_val - new_val

        # Adjust DAILY_YIELD if present (assuming 15-min = 0.25h interval)
        if yield_array is not None and yield_col is not None and delta_p_ac > 0.0:
            delta_kwh = delta_p_ac * 0.25
            day_cumulative_delta_kwh += delta_kwh
            orig_yield = yield_array[idx]
            new_yield = max(0.0, round(orig_yield - day_cumulative_delta_kwh, 4))
            yield_array[idx] = new_yield
            row_mods[yield_col] = {"original": orig_yield, "corrupted": new_yield}

        if row_mods:
            affected_rows.append(idx)
            dev_val = str(df[device_col][idx]) if device_col else target_device
            row_modifications.append(
                RowModification(
                    row_index=idx,
                    timestamp=str(df[timestamp_col][idx]),
                    device_id=dev_val,
                    anomaly_types=[AnomalyType.SOILING.value],
                    event_ids=[event_id],
                    modifications=row_mods,
                )
            )

    # Reconstruct modified DataFrame
    updated_cols: List[pl.Series] = []
    for c in df.columns:
        if c in col_arrays:
            updated_cols.append(pl.Series(c, col_arrays[c]))
        elif yield_array is not None and c == yield_col:
            updated_cols.append(pl.Series(c, yield_array))
        else:
            updated_cols.append(df[c])

    updated_df = pl.DataFrame(updated_cols)

    first_ts = str(df[timestamp_col][window_indices[0]])
    last_ts = str(df[timestamp_col][window_indices[-1]])

    event = InjectedEvent(
        event_id=event_id,
        anomaly_type=AnomalyType.SOILING.value,
        device_id=target_device,
        columns=power_cols + ([yield_col] if yield_array is not None and yield_col else []),
        start_timestamp=first_ts,
        end_timestamp=last_ts,
        affected_row_count=len(affected_rows),
        parameters={
            "start_date": str(s_date),
            "end_date": str(e_date),
            "duration_days": duration_days,
            "max_degradation_pct": round(max_degradation * 100.0, 2),
            "profile": "linear_progressive",
        },
        row_indexes=affected_rows,
    )

    return updated_df, event, row_modifications


def inject_trip(
    df: pl.DataFrame,
    target_device: Optional[str] = None,
    power_cols: Optional[List[str]] = None,
    yield_col: Optional[str] = None,
    trip_time: Optional[Union[str, datetime]] = None,
    duration_steps: int = 16,
    residual_power: float = 0.0,
    event_id: str = "trip-001",
    timestamp_col: Optional[str] = None,
    device_col: Optional[str] = None,
    adjust_yield: bool = True,
) -> Tuple[pl.DataFrame, InjectedEvent, List[RowModification]]:
    """Inject abrupt inverter trip / ramp-down fault cutting power to zero during peak sunlight."""
    ts_c, dev_c, default_power, default_yield = detect_dataset_columns(df)
    timestamp_col = timestamp_col or ts_c
    device_col = device_col if device_col is not None else dev_c
    power_cols = power_cols or default_power
    yield_col = yield_col or default_yield

    row_count = len(df)
    parsed_dt = parse_timestamps(df[timestamp_col])
    temp_df = df.with_columns(
        pl.int_range(0, row_count).alias("__row_idx__"),
        parsed_dt.alias("__parsed_dt__"),
    )

    if device_col and target_device:
        device_mask = temp_df[device_col] == target_device
    else:
        device_mask = pl.Series([True] * row_count)

    sub_df = temp_df.filter(device_mask)
    if len(sub_df) == 0:
        raise ValueError(f"No records found for target device '{target_device}'")

    # If trip_time not provided, find peak generation row in the middle of dataset
    target_start_idx: Optional[int] = None
    if trip_time is not None:
        if isinstance(trip_time, str):
            # Try to match string directly or parsed
            match = sub_df.filter(pl.col(timestamp_col) == trip_time)
            if len(match) > 0:
                target_start_idx = match["__row_idx__"][0]
            else:
                p_dt = parse_timestamps(pl.Series([trip_time]))[0]
                match_dt = sub_df.filter(pl.col("__parsed_dt__") >= p_dt)
                if len(match_dt) > 0:
                    target_start_idx = match_dt["__row_idx__"][0]
        elif isinstance(trip_time, datetime):
            match_dt = sub_df.filter(pl.col("__parsed_dt__") >= trip_time)
            if len(match_dt) > 0:
                target_start_idx = match_dt["__row_idx__"][0]

    if target_start_idx is None:
        # Auto-select: find daylight peak (e.g. power > 60% of max, around midday 11:30 - 13:00)
        p_col = power_cols[0]
        max_p = _to_float(sub_df[p_col].max(), 100.0)
        candidate_rows = sub_df.filter(
            (pl.col(p_col) > 0.6 * max_p)
            & (pl.col("__parsed_dt__").dt.hour() >= 11)
            & (pl.col("__parsed_dt__").dt.hour() <= 13)
        )
        if len(candidate_rows) > 0:
            # Pick a day around day 7 or middle
            mid_row = candidate_rows[len(candidate_rows) // 2]
            target_start_idx = mid_row["__row_idx__"][0]
        else:
            # Fallback: row with absolute max power
            target_start_idx = sub_df.filter(pl.col(p_col) == max_p)["__row_idx__"][0]

    # Find subsequent rows for the same device
    device_rows = sub_df["__row_idx__"].to_list()
    pos = device_rows.index(target_start_idx)
    trip_indices = device_rows[pos : pos + duration_steps]

    col_arrays: Dict[str, List[float]] = {}
    for col_name in power_cols:
        col_arrays[col_name] = [float(v) if v is not None else 0.0 for v in df[col_name].to_list()]

    yield_array: Optional[List[float]] = None
    if adjust_yield and yield_col and yield_col in df.columns:
        yield_array = [float(v) if v is not None else 0.0 for v in df[yield_col].to_list()]

    row_modifications: List[RowModification] = []
    affected_rows: List[int] = []

    # Record pre-trip power for verification
    pre_trip_power = {col: col_arrays[col][target_start_idx] for col in power_cols}

    for idx in trip_indices:
        row_mods: Dict[str, Dict[str, float]] = {}
        for col_name in power_cols:
            orig_val = col_arrays[col_name][idx]
            new_val = residual_power
            col_arrays[col_name][idx] = new_val
            row_mods[col_name] = {"original": orig_val, "corrupted": new_val}

        # If adjust yield, freeze daily yield to pre-trip value
        if yield_array is not None and yield_col is not None:
            orig_yield = yield_array[idx]
            # Yield remains frozen at pre-trip value during trip downtime
            pre_trip_yield = yield_array[trip_indices[0]]
            new_yield = pre_trip_yield
            yield_array[idx] = new_yield
            row_mods[yield_col] = {"original": orig_yield, "corrupted": new_yield}

        affected_rows.append(idx)
        dev_val = str(df[device_col][idx]) if device_col else target_device
        row_modifications.append(
            RowModification(
                row_index=idx,
                timestamp=str(df[timestamp_col][idx]),
                device_id=dev_val,
                anomaly_types=[AnomalyType.TRIP.value],
                event_ids=[event_id],
                modifications=row_mods,
            )
        )

    updated_cols: List[pl.Series] = []
    for c in df.columns:
        if c in col_arrays:
            updated_cols.append(pl.Series(c, col_arrays[c]))
        elif yield_array is not None and c == yield_col:
            updated_cols.append(pl.Series(c, yield_array))
        else:
            updated_cols.append(df[c])

    updated_df = pl.DataFrame(updated_cols)

    first_ts = str(df[timestamp_col][trip_indices[0]])
    last_ts = str(df[timestamp_col][trip_indices[-1]])

    event = InjectedEvent(
        event_id=event_id,
        anomaly_type=AnomalyType.TRIP.value,
        device_id=target_device,
        columns=power_cols + ([yield_col] if yield_array is not None and yield_col else []),
        start_timestamp=first_ts,
        end_timestamp=last_ts,
        affected_row_count=len(affected_rows),
        parameters={
            "duration_steps": duration_steps,
            "residual_power": residual_power,
            "pre_trip_power": pre_trip_power,
            "trip_mode": "instantaneous_cut",
        },
        row_indexes=affected_rows,
    )

    return updated_df, event, row_modifications


def inject_clipping(
    df: pl.DataFrame,
    target_device: Optional[str] = None,
    power_cols: Optional[List[str]] = None,
    clip_threshold_ac: Optional[float] = None,
    clip_threshold_dc: Optional[float] = None,
    clip_ratio: float = 0.65,
    start_date: Optional[Union[str, date, datetime]] = None,
    duration_days: int = 5,
    event_id: str = "clip-001",
    timestamp_col: Optional[str] = None,
    device_col: Optional[str] = None,
) -> Tuple[pl.DataFrame, InjectedEvent, List[RowModification]]:
    """Inject peak generation clipping creating a flat horizontal ceiling threshold."""
    ts_c, dev_c, default_power, _ = detect_dataset_columns(df)
    timestamp_col = timestamp_col or ts_c
    device_col = device_col if device_col is not None else dev_c
    power_cols = power_cols or default_power

    row_count = len(df)
    parsed_dt = parse_timestamps(df[timestamp_col])
    temp_df = df.with_columns(
        pl.int_range(0, row_count).alias("__row_idx__"),
        parsed_dt.alias("__parsed_dt__"),
    )

    if device_col and target_device:
        device_mask = temp_df[device_col] == target_device
    else:
        device_mask = pl.Series([True] * row_count)

    sub_df = temp_df.filter(device_mask)
    if len(sub_df) == 0:
        raise ValueError(f"No records found for target device '{target_device}'")

    valid_dates = sub_df["__parsed_dt__"].dt.date().unique().sort().drop_nulls().to_list()
    if not valid_dates:
        raise ValueError("No valid chronological dates available for clipping injection")

    if start_date is not None:
        if isinstance(start_date, str):
            for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"]:
                try:
                    s_date: date = datetime.strptime(start_date, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                s_date = datetime.fromisoformat(start_date).date()
        elif isinstance(start_date, datetime):
            s_date = start_date.date()
        else:
            s_date = start_date
    else:
        # Default start: middle of dataset
        start_idx = min(10, max(0, len(valid_dates) - duration_days - 1))
        s_date = valid_dates[start_idx]

    e_date = s_date + timedelta(days=duration_days)

    # Window condition
    in_window_mask = (
        device_mask
        & (temp_df["__parsed_dt__"].dt.date() >= s_date)
        & (temp_df["__parsed_dt__"].dt.date() <= e_date)
    )

    window_indices = temp_df.filter(in_window_mask)["__row_idx__"].to_list()
    if not window_indices:
        raise ValueError(
            f"No data rows found within clipping window [{s_date} to {e_date}] for device '{target_device}'"
        )

    # Compute thresholds per power column
    thresholds: Dict[str, float] = {}
    for col_name in power_cols:
        col_max = _to_float(sub_df[col_name].max(), 1000.0)
        if "dc" in col_name.lower() and clip_threshold_dc is not None:
            thresholds[col_name] = clip_threshold_dc
        elif "ac" in col_name.lower() and clip_threshold_ac is not None:
            thresholds[col_name] = clip_threshold_ac
        elif clip_threshold_ac is not None and len(power_cols) == 1:
            thresholds[col_name] = clip_threshold_ac
        else:
            thresholds[col_name] = round(col_max * clip_ratio, 2)

    col_arrays: Dict[str, List[float]] = {}
    for col_name in power_cols:
        col_arrays[col_name] = [float(v) if v is not None else 0.0 for v in df[col_name].to_list()]

    row_modifications: List[RowModification] = []
    affected_rows: List[int] = []

    for idx in window_indices:
        row_mods: Dict[str, Dict[str, float]] = {}
        for col_name in power_cols:
            orig_val = col_arrays[col_name][idx]
            thresh = thresholds[col_name]
            if orig_val > thresh:
                new_val = thresh
                col_arrays[col_name][idx] = new_val
                row_mods[col_name] = {"original": orig_val, "corrupted": new_val}

        if row_mods:
            affected_rows.append(idx)
            dev_val = str(df[device_col][idx]) if device_col else target_device
            row_modifications.append(
                RowModification(
                    row_index=idx,
                    timestamp=str(df[timestamp_col][idx]),
                    device_id=dev_val,
                    anomaly_types=[AnomalyType.CLIPPING.value],
                    event_ids=[event_id],
                    modifications=row_mods,
                )
            )

    updated_cols: List[pl.Series] = []
    for c in df.columns:
        if c in col_arrays:
            updated_cols.append(pl.Series(c, col_arrays[c]))
        else:
            updated_cols.append(df[c])

    updated_df = pl.DataFrame(updated_cols)

    first_ts = (
        str(df[timestamp_col][affected_rows[0]])
        if affected_rows
        else str(df[timestamp_col][window_indices[0]])
    )
    last_ts = (
        str(df[timestamp_col][affected_rows[-1]])
        if affected_rows
        else str(df[timestamp_col][window_indices[-1]])
    )

    event = InjectedEvent(
        event_id=event_id,
        anomaly_type=AnomalyType.CLIPPING.value,
        device_id=target_device,
        columns=power_cols,
        start_timestamp=first_ts,
        end_timestamp=last_ts,
        affected_row_count=len(affected_rows),
        parameters={
            "clip_thresholds": thresholds,
            "clip_ratio": clip_ratio,
            "start_date": str(s_date),
            "end_date": str(e_date),
            "duration_days": duration_days,
            "profile": "horizontal_ceiling",
        },
        row_indexes=affected_rows,
    )

    return updated_df, event, row_modifications


def inject_flatline(
    df: pl.DataFrame,
    target_device: Optional[str] = None,
    columns: Optional[List[str]] = None,
    start_time: Optional[Union[str, datetime]] = None,
    duration_steps: int = 8,
    fixed_value: Optional[float] = None,
    event_id: str = "flat-001",
    timestamp_col: Optional[str] = None,
    device_col: Optional[str] = None,
) -> Tuple[pl.DataFrame, InjectedEvent, List[RowModification]]:
    """Inject frozen telemetry flatline repeating identical non-zero values across consecutive intervals."""
    ts_c, dev_c, default_power, _ = detect_dataset_columns(df)
    timestamp_col = timestamp_col or ts_c
    device_col = device_col if device_col is not None else dev_c
    columns = columns or default_power

    row_count = len(df)
    parsed_dt = parse_timestamps(df[timestamp_col])
    temp_df = df.with_columns(
        pl.int_range(0, row_count).alias("__row_idx__"),
        parsed_dt.alias("__parsed_dt__"),
    )

    if device_col and target_device:
        device_mask = temp_df[device_col] == target_device
    else:
        device_mask = pl.Series([True] * row_count)

    sub_df = temp_df.filter(device_mask)
    if len(sub_df) == 0:
        raise ValueError(f"No records found for target device '{target_device}'")

    target_start_idx: Optional[int] = None
    if start_time is not None:
        if isinstance(start_time, str):
            match = sub_df.filter(pl.col(timestamp_col) == start_time)
            if len(match) > 0:
                target_start_idx = match["__row_idx__"][0]
            else:
                p_dt = parse_timestamps(pl.Series([start_time]))[0]
                match_dt = sub_df.filter(pl.col("__parsed_dt__") >= p_dt)
                if len(match_dt) > 0:
                    target_start_idx = match_dt["__row_idx__"][0]
        elif isinstance(start_time, datetime):
            match_dt = sub_df.filter(pl.col("__parsed_dt__") >= start_time)
            if len(match_dt) > 0:
                target_start_idx = match_dt["__row_idx__"][0]

    if target_start_idx is None:
        # Select active daytime interval where power > 100 kW around 10:00 AM on a sunny day
        primary_col = columns[0]
        max_v = _to_float(sub_df[primary_col].max(), 500.0)
        candidate_rows = sub_df.filter(
            (pl.col(primary_col) > 0.4 * max_v)
            & (pl.col("__parsed_dt__").dt.hour() >= 10)
            & (pl.col("__parsed_dt__").dt.hour() <= 12)
        )
        if len(candidate_rows) > 0:
            target_start_idx = candidate_rows[len(candidate_rows) // 3]["__row_idx__"][0]
        else:
            # Fallback: any non-zero row
            target_start_idx = sub_df.filter(pl.col(primary_col) > 10.0)["__row_idx__"][0]

    device_rows = sub_df["__row_idx__"].to_list()
    pos = device_rows.index(target_start_idx)
    flatline_indices = device_rows[pos : pos + duration_steps]

    col_arrays: Dict[str, List[float]] = {}
    for col_name in columns:
        col_arrays[col_name] = [float(v) if v is not None else 0.0 for v in df[col_name].to_list()]

    # Freeze values to the reading at the initial interval (guaranteed non-zero)
    frozen_values: Dict[str, float] = {}
    for col_name in columns:
        if fixed_value is not None:
            frozen_values[col_name] = fixed_value
        else:
            val_at_start = col_arrays[col_name][target_start_idx]
            frozen_values[col_name] = round(val_at_start, 4)

    row_modifications: List[RowModification] = []
    affected_rows: List[int] = []

    for idx in flatline_indices:
        row_mods: Dict[str, Dict[str, float]] = {}
        for col_name in columns:
            orig_val = col_arrays[col_name][idx]
            new_val = frozen_values[col_name]
            col_arrays[col_name][idx] = new_val
            row_mods[col_name] = {"original": orig_val, "corrupted": new_val}

        affected_rows.append(idx)
        dev_val = str(df[device_col][idx]) if device_col else target_device
        row_modifications.append(
            RowModification(
                row_index=idx,
                timestamp=str(df[timestamp_col][idx]),
                device_id=dev_val,
                anomaly_types=[AnomalyType.FLATLINE.value],
                event_ids=[event_id],
                modifications=row_mods,
            )
        )

    updated_cols: List[pl.Series] = []
    for c in df.columns:
        if c in col_arrays:
            updated_cols.append(pl.Series(c, col_arrays[c]))
        else:
            updated_cols.append(df[c])

    updated_df = pl.DataFrame(updated_cols)

    first_ts = str(df[timestamp_col][flatline_indices[0]])
    last_ts = str(df[timestamp_col][flatline_indices[-1]])

    event = InjectedEvent(
        event_id=event_id,
        anomaly_type=AnomalyType.FLATLINE.value,
        device_id=target_device,
        columns=columns,
        start_timestamp=first_ts,
        end_timestamp=last_ts,
        affected_row_count=len(affected_rows),
        parameters={
            "frozen_values": frozen_values,
            "duration_steps": duration_steps,
            "profile": "stuck_telemetry_buffer",
        },
        row_indexes=affected_rows,
    )

    return updated_df, event, row_modifications


# ---------------------------------------------------------------------------
# Fault Injection Engine Orchestrator
# ---------------------------------------------------------------------------


class FaultInjectionEngine:
    """Orchestrator introducing realistic field anomalies and generating ground truth."""

    def __init__(self, config: Optional[FaultConfig] = None) -> None:
        """Initialize engine with configuration."""
        self.config = config or FaultConfig()
        random.seed(self.config.seed)

    def run(
        self,
        input_df: pl.DataFrame,
        source_path: str = "Datasets/Plant_1_Generation_Data.csv",
        corrupted_path: str = "Datasets/Surya-A-demo.csv",
    ) -> Tuple[pl.DataFrame, GroundTruthManifest]:
        """Execute end-to-end fault injection and compile ground truth manifest."""
        current_df = input_df.clone()
        ts_col, dev_col, power_cols, yield_col = detect_dataset_columns(current_df)

        # Inverter / Device Allocation
        unique_devices: List[str] = []
        if dev_col and dev_col in current_df.columns:
            unique_devices = sorted(current_df[dev_col].unique().drop_nulls().to_list())

        # Assign targets
        dev_soiling = self.config.target_inverter_soiling
        dev_trip = self.config.target_inverter_trip
        dev_clipping = self.config.target_inverter_clipping
        dev_flatline = self.config.target_inverter_flatline

        if unique_devices:
            # If targets not explicitly configured, distribute across distinct inverters
            if dev_soiling is None and len(unique_devices) >= 1:
                dev_soiling = unique_devices[0]
            if dev_trip is None and len(unique_devices) >= 2:
                dev_trip = unique_devices[1]
            elif dev_trip is None:
                dev_trip = unique_devices[0]
            if dev_clipping is None and len(unique_devices) >= 3:
                dev_clipping = unique_devices[2]
            elif dev_clipping is None:
                dev_clipping = unique_devices[0]
            if dev_flatline is None and len(unique_devices) >= 4:
                dev_flatline = unique_devices[3]
            elif dev_flatline is None:
                dev_flatline = unique_devices[0]

        events: List[InjectedEvent] = []
        all_modifications: List[RowModification] = []

        # 1. Inject Soiling
        if self.config.include_soiling:
            current_df, event, mods = inject_soiling(
                df=current_df,
                target_device=dev_soiling,
                power_cols=power_cols,
                yield_col=yield_col,
                start_date=self.config.soiling_start_date,
                duration_days=self.config.soiling_days,
                max_degradation=self.config.soiling_max_degradation * self.config.severity,
                event_id="soil-001",
                timestamp_col=ts_col,
                device_col=dev_col,
                adjust_yield=self.config.adjust_yield,
            )
            events.append(event)
            all_modifications.extend(mods)

        # 2. Inject Ramp / Trip
        if self.config.include_trip:
            current_df, event, mods = inject_trip(
                df=current_df,
                target_device=dev_trip,
                power_cols=power_cols,
                yield_col=yield_col,
                trip_time=self.config.trip_start_time,
                duration_steps=self.config.trip_duration_steps,
                residual_power=self.config.trip_residual_power,
                event_id="trip-001",
                timestamp_col=ts_col,
                device_col=dev_col,
                adjust_yield=self.config.adjust_yield,
            )
            events.append(event)
            all_modifications.extend(mods)

        # 3. Inject Clipping
        if self.config.include_clipping:
            current_df, event, mods = inject_clipping(
                df=current_df,
                target_device=dev_clipping,
                power_cols=power_cols,
                clip_threshold_ac=self.config.clipping_threshold_ac,
                clip_threshold_dc=self.config.clipping_threshold_dc,
                clip_ratio=self.config.clipping_ratio,
                start_date=self.config.clipping_start_date,
                duration_days=self.config.clipping_days,
                event_id="clip-001",
                timestamp_col=ts_col,
                device_col=dev_col,
            )
            events.append(event)
            all_modifications.extend(mods)

        # 4. Inject Flatline
        if self.config.include_flatline:
            current_df, event, mods = inject_flatline(
                df=current_df,
                target_device=dev_flatline,
                columns=power_cols,
                start_time=self.config.flatline_start_time,
                duration_steps=self.config.flatline_duration_steps,
                fixed_value=self.config.flatline_value,
                event_id="flat-001",
                timestamp_col=ts_col,
                device_col=dev_col,
            )
            events.append(event)
            all_modifications.extend(mods)

        # Aggregate row ground-truth into dictionary keyed by row index string
        row_ground_truth: Dict[str, Dict[str, Any]] = {}
        anomalies_by_type: Dict[str, int] = {
            AnomalyType.SOILING.value: 0,
            AnomalyType.TRIP.value: 0,
            AnomalyType.CLIPPING.value: 0,
            AnomalyType.FLATLINE.value: 0,
        }
        affected_devices_set: Set[str] = set()

        for mod in all_modifications:
            r_str = str(mod.row_index)
            if r_str not in row_ground_truth:
                row_ground_truth[r_str] = {
                    "row_index": mod.row_index,
                    "timestamp": mod.timestamp,
                    "device_id": mod.device_id,
                    "anomaly_types": list(mod.anomaly_types),
                    "event_ids": list(mod.event_ids),
                    "modifications": dict(mod.modifications),
                }
            else:
                existing = row_ground_truth[r_str]
                for at in mod.anomaly_types:
                    if at not in existing["anomaly_types"]:
                        existing["anomaly_types"].append(at)
                for eid in mod.event_ids:
                    if eid not in existing["event_ids"]:
                        existing["event_ids"].append(eid)
                existing["modifications"].update(mod.modifications)

            # Ensure "original" always reflects true clean input_df baseline
            # and "corrupted" reflects the final state in current_df
            for col_name in row_ground_truth[r_str]["modifications"]:
                row_ground_truth[r_str]["modifications"][col_name]["original"] = _to_float(
                    input_df[col_name][mod.row_index]
                )
                row_ground_truth[r_str]["modifications"][col_name]["corrupted"] = _to_float(
                    current_df[col_name][mod.row_index]
                )

            if mod.device_id:
                affected_devices_set.add(mod.device_id)

        for event in events:
            anomalies_by_type[event.anomaly_type] = (
                anomalies_by_type.get(event.anomaly_type, 0) + event.affected_row_count
            )

        total_rows = len(current_df)
        total_affected = len(row_ground_truth)

        metadata: Dict[str, Any] = {
            "generator": "PlantIQ Fault-Injection Engine",
            "task": "S2-Both-01",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed": self.config.seed,
            "severity": self.config.severity,
            "source_dataset": str(source_path),
            "corrupted_dataset": str(corrupted_path),
            "total_rows": total_rows,
            "total_anomalous_rows": total_affected,
            "anomalous_rows_percentage": round(
                (total_affected / max(1, total_rows)) * 100.0, 3
            ),
            "anomalies_by_type": anomalies_by_type,
            "affected_devices": sorted(list(affected_devices_set)),
        }

        manifest = GroundTruthManifest(
            metadata=metadata,
            events=events,
            row_ground_truth=row_ground_truth,
        )

        return current_df, manifest


# ---------------------------------------------------------------------------
# CLI Command Implementation
# ---------------------------------------------------------------------------


@app.command()
def main(
    input_file: Path = typer.Option(
        DEFAULT_INPUT_FILE,
        "--input-file",
        "-i",
        help="Path to clean base solar telemetry CSV or Parquet file.",
    ),
    output_file: Path = typer.Option(
        DEFAULT_OUTPUT_CSV,
        "--output-file",
        "-o",
        help="Path to save corrupted solar telemetry CSV (Surya-A-demo.csv).",
    ),
    ground_truth_file: Path = typer.Option(
        DEFAULT_GROUND_TRUTH_JSON,
        "--ground-truth-file",
        "-g",
        help="Path to save ground-truth JSON answer key.",
    ),
    seed: int = typer.Option(
        42,
        "--seed",
        "-s",
        help="Deterministic random seed.",
    ),
    severity: float = typer.Option(
        1.0,
        "--severity",
        help="Overall anomaly severity multiplier (0.1 to 2.0).",
    ),
    soiling: bool = typer.Option(
        True,
        "--soiling/--no-soiling",
        help="Inject progressive multi-day soiling degradation.",
    ),
    trip: bool = typer.Option(
        True,
        "--trip/--no-trip",
        help="Inject abrupt inverter trip / ramp-down power cut.",
    ),
    clipping: bool = typer.Option(
        True,
        "--clipping/--no-clipping",
        help="Inject peak solar generation horizontal ceiling clipping.",
    ),
    flatline: bool = typer.Option(
        True,
        "--flatline/--no-flatline",
        help="Inject frozen sensor telemetry flatline.",
    ),
    soiling_days: int = typer.Option(
        7,
        "--soiling-days",
        help="Duration in days for progressive soiling accumulation.",
    ),
    trip_steps: int = typer.Option(
        16,
        "--trip-steps",
        help="Number of 15-minute intervals for inverter trip downtime.",
    ),
    clipping_ratio: float = typer.Option(
        0.65,
        "--clipping-ratio",
        help="Clipping ceiling ratio relative to observed peak generation.",
    ),
    flatline_steps: int = typer.Option(
        8,
        "--flatline-steps",
        help="Number of consecutive intervals for frozen telemetry flatline.",
    ),
    target_inverters: Optional[str] = typer.Option(
        None,
        "--target-inverters",
        help="Comma-separated target inverter keys (e.g. 'INV-1,INV-2,INV-3,INV-4').",
    ),
    adjust_yield: bool = typer.Option(
        True,
        "--adjust-yield/--no-adjust-yield",
        help="Adjust cumulative daily yield consistently with modified power output.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress rich terminal output tables.",
    ),
) -> None:
    """Execute Fault-Injection Engine on base solar dataset and generate test fixtures."""
    if not input_file.exists():
        console.print(f"[bold red]Error:[/bold red] Input file '{input_file}' does not exist.")
        raise typer.Exit(code=1)

    t0 = datetime.now()

    # Parse target inverters if specified
    targets: Optional[List[str]] = None
    if target_inverters:
        targets = [t.strip() for t in target_inverters.split(",") if t.strip()]

    config = FaultConfig(
        seed=seed,
        severity=severity,
        include_soiling=soiling,
        include_trip=trip,
        include_clipping=clipping,
        include_flatline=flatline,
        soiling_days=soiling_days,
        trip_duration_steps=trip_steps,
        clipping_ratio=clipping_ratio,
        flatline_duration_steps=flatline_steps,
        target_inverter_soiling=targets[0] if targets and len(targets) > 0 else None,
        target_inverter_trip=targets[1] if targets and len(targets) > 1 else None,
        target_inverter_clipping=targets[2] if targets and len(targets) > 2 else None,
        target_inverter_flatline=targets[3] if targets and len(targets) > 3 else None,
        adjust_yield=adjust_yield,
    )

    if not quiet:
        console.print(
            Panel.fit(
                f"[bold cyan]PlantIQ Fault-Injection Engine[/bold cyan]\n"
                f"[dim]Task: S2-Both-01 | Monorepo Synthetic Fixture Generation[/dim]\n\n"
                f"• Input:  [bold yellow]{input_file}[/bold yellow]\n"
                f"• Output: [bold green]{output_file}[/bold green]\n"
                f"• Ground Truth: [bold magenta]{ground_truth_file}[/bold magenta]\n"
                f"• Seed: {seed} | Severity: {severity}x",
                title="[bold]Fault Injection Pipeline[/bold]",
                border_style="cyan",
            )
        )

    # Load clean base dataset using Polars
    try:
        if str(input_file).endswith(".parquet"):
            clean_df = pl.read_parquet(input_file)
        else:
            clean_df = pl.read_csv(input_file, infer_schema_length=10000)
    except Exception as e:
        console.print(f"[bold red]Failed to read input dataset:[/bold red] {e}")
        raise typer.Exit(code=1)

    # Execute injection engine
    engine = FaultInjectionEngine(config=config)
    corrupted_df, manifest = engine.run(
        input_df=clean_df,
        source_path=str(input_file),
        corrupted_path=str(output_file),
    )

    # Ensure parent output directories exist
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ground_truth_file.parent.mkdir(parents=True, exist_ok=True)

    # Write corrupted CSV artifact
    try:
        corrupted_df.write_csv(output_file)
    except Exception as e:
        console.print(f"[bold red]Failed to write corrupted CSV:[/bold red] {e}")
        raise typer.Exit(code=1)

    # Write ground-truth JSON artifact
    try:
        manifest.save(ground_truth_file)
    except Exception as e:
        console.print(f"[bold red]Failed to write ground truth JSON:[/bold red] {e}")
        raise typer.Exit(code=1)

    duration = (datetime.now() - t0).total_seconds()

    if not quiet:
        # Display Injected Events Table
        event_table = Table(
            title="Injected Anomaly Events (Ground Truth Summary)",
            show_header=True,
            header_style="bold magenta",
        )
        event_table.add_column("Event ID", style="bold")
        event_table.add_column("Anomaly Type", style="cyan")
        event_table.add_column("Target Device", style="yellow")
        event_table.add_column("Affected Rows", justify="right")
        event_table.add_column("Time Window", style="dim")
        event_table.add_column("Key Injected Parameter")

        for event in manifest.events:
            param_str = ", ".join(f"{k}={v}" for k, v in list(event.parameters.items())[:2])
            event_table.add_row(
                event.event_id,
                event.anomaly_type.upper(),
                str(event.device_id),
                str(event.affected_row_count),
                f"{event.start_timestamp} -> {event.end_timestamp}",
                param_str,
            )

        console.print(event_table)

        # Summary Panel
        meta = manifest.metadata
        summary_panel = Panel(
            f"[bold green]✔ Fault Injection Complete in {duration:.2f}s[/bold green]\n\n"
            f"• Total Rows:             [bold]{meta['total_rows']:,}[/bold]\n"
            f"• Corrupted Data Rows:    [bold red]{meta['total_anomalous_rows']:,}[/bold red] ({meta['anomalous_rows_percentage']}% of dataset)\n"
            f"• Anomaly Breakdown:      Soiling={meta['anomalies_by_type']['soiling']}, "
            f"Trip={meta['anomalies_by_type']['trip']}, "
            f"Clipping={meta['anomalies_by_type']['clipping']}, "
            f"Flatline={meta['anomalies_by_type']['flatline']}\n"
            f"• Affected Devices:       {', '.join(meta['affected_devices'])}\n"
            f"• Output Dataset:         [bold green]{output_file}[/bold green] ({output_file.stat().st_size / (1024*1024):.2f} MB)\n"
            f"• Ground Truth Key:       [bold magenta]{ground_truth_file}[/bold magenta] ({ground_truth_file.stat().st_size / 1024:.1f} KB)",
            title="[bold green]Artifacts Successfully Generated[/bold green]",
            border_style="green",
        )
        console.print(summary_panel)


if __name__ == "__main__":
    app()
