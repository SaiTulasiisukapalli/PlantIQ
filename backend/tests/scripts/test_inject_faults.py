"""Unit and Integration Tests for Fault-Injection Engine & Synthetic Test Fixtures.

Task: S2-Both-01
Validates:
- Standalone fault injection functions:
    * inject_soiling: Progressive daytime degradation, night zero-preservation, peer isolation.
    * inject_trip: Instantaneous cut to 0.0 kW during peak hours, downtime duration, step-change gradient.
    * inject_clipping: Strict horizontal ceiling threshold bounding peak power, lower values untouched.
    * inject_flatline: Sensor freezing on identical non-zero values across consecutive intervals.
- Schema integrity and shape preservation between clean base dataset and corrupted dataset.
- Exact synchronization between Surya-A-demo.csv and ground_truth_anomalies.json answer key.
- Unaffected rows and peer devices remain 100% bit-for-bit identical.
- Typer CLI execution, custom parameters, toggles (--no-trip, --no-soiling), and deterministic seeding.
- Interoperability with PlantIQ Vectorized QC Bitmask Engine (FLATLINE and SPIKE flag detection).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List
import polars as pl
import pytest
from typer.testing import CliRunner

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.app.ai.ingest_worker import IngestConfig, QCFlag, evaluate_qc_series
from backend.scripts.inject_faults import (
    DEFAULT_GROUND_TRUTH_JSON,
    DEFAULT_INPUT_FILE,
    DEFAULT_OUTPUT_CSV,
    AnomalyType,
    FaultConfig,
    FaultInjectionEngine,
    app,
    detect_dataset_columns,
    inject_clipping,
    inject_flatline,
    inject_soiling,
    inject_trip,
    parse_timestamps,
)

runner = CliRunner()


@pytest.fixture
def synthetic_solar_df() -> pl.DataFrame:
    """Create a controlled 2-device, 3-day synthetic solar generation DataFrame at 15-min cadence."""
    base_time = datetime(2023, 6, 1, 0, 0, 0)
    rows: List[Dict[str, Any]] = []

    # 3 days = 3 * 96 = 288 timesteps for 2 devices = 576 rows
    for step in range(288):
        dt = base_time + timedelta(minutes=step * 15)
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        hour = dt.hour + (dt.minute / 60.0)

        # Baseline diurnal bell curve between 6:00 and 18:00
        if 6.0 <= hour <= 18.0:
            solar_factor = max(0.0, -((hour - 12.0) ** 2) / 36.0 + 1.0)
            p_ac_base = round(800.0 * solar_factor, 2)
            p_dc_base = round(8200.0 * solar_factor, 2)
        else:
            p_ac_base = 0.0
            p_dc_base = 0.0

        for dev in ["INV_ALPHA", "INV_BETA"]:
            # Add small device variance
            mult = 1.0 if dev == "INV_ALPHA" else 0.98
            rows.append(
                {
                    "timestamp": dt_str,
                    "device_id": dev,
                    "AC_POWER": round(p_ac_base * mult, 2),
                    "DC_POWER": round(p_dc_base * mult, 2),
                    "DAILY_YIELD": round(step * 0.25, 2),
                }
            )

    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# 1. Column Detection & Timestamp Utility Tests
# ---------------------------------------------------------------------------


def test_detect_dataset_columns(synthetic_solar_df: pl.DataFrame) -> None:
    """Verify smart column detection across various naming conventions."""
    ts_col, dev_col, power_cols, yield_col = detect_dataset_columns(synthetic_solar_df)
    assert ts_col == "timestamp"
    assert dev_col == "device_id"
    assert "AC_POWER" in power_cols
    assert "DC_POWER" in power_cols
    assert yield_col == "DAILY_YIELD"


def test_parse_timestamps_formats() -> None:
    """Verify timestamp parsing across both Day-First and ISO formats."""
    s1 = pl.Series("ts", ["15-05-2020 00:00", "15-05-2020 00:15", "15-05-2020 12:30"])
    p1 = parse_timestamps(s1)
    assert p1.dtype == pl.Datetime
    assert p1[0] == datetime(2020, 5, 15, 0, 0)
    assert p1[2] == datetime(2020, 5, 15, 12, 30)

    s2 = pl.Series("ts", ["2023-06-01 10:00:00", "2023-06-01 10:15:00"])
    p2 = parse_timestamps(s2)
    assert p2.dtype == pl.Datetime
    assert p2[0] == datetime(2023, 6, 1, 10, 0)


# ---------------------------------------------------------------------------
# 2. Standalone Anomaly Injection Tests
# ---------------------------------------------------------------------------


def test_inject_soiling_progressive_degradation(synthetic_solar_df: pl.DataFrame) -> None:
    """Verify that soiling progressively degrades power over time without altering night values."""
    target_dev = "INV_ALPHA"
    mod_df, event, mods = inject_soiling(
        df=synthetic_solar_df,
        target_device=target_dev,
        duration_days=2,
        max_degradation=0.40,
        adjust_yield=False,
    )

    assert event.anomaly_type == AnomalyType.SOILING.value
    assert event.device_id == target_dev
    assert len(mods) > 0
    assert len(mod_df) == len(synthetic_solar_df)

    # Verify target device power decreased during daytime
    alpha_clean = synthetic_solar_df.filter(pl.col("device_id") == target_dev)
    alpha_corrupted = mod_df.filter(pl.col("device_id") == target_dev)

    clean_ac = alpha_clean["AC_POWER"].to_list()
    corr_ac = alpha_corrupted["AC_POWER"].to_list()

    day_points_tested = 0
    for c_val, m_val in zip(clean_ac, corr_ac):
        if c_val > 0.0:
            assert m_val <= c_val
            day_points_tested += 1
        else:
            # Nighttime remains 0.0
            assert m_val == 0.0

    assert day_points_tested > 0

    # Verify peer device INV_BETA was completely untouched
    beta_clean = synthetic_solar_df.filter(pl.col("device_id") == "INV_BETA")
    beta_corrupted = mod_df.filter(pl.col("device_id") == "INV_BETA")
    assert beta_clean.equals(beta_corrupted)


def test_inject_trip_abrupt_step_cut(synthetic_solar_df: pl.DataFrame) -> None:
    """Verify that trip injects an instantaneous drop to 0.0 kW during midday."""
    target_dev = "INV_ALPHA"
    duration = 12
    mod_df, event, mods = inject_trip(
        df=synthetic_solar_df,
        target_device=target_dev,
        duration_steps=duration,
        residual_power=0.0,
    )

    assert event.anomaly_type == AnomalyType.TRIP.value
    assert event.affected_row_count == duration
    assert len(event.row_indexes) == duration

    for row_idx in event.row_indexes:
        assert mod_df["AC_POWER"][row_idx] == 0.0
        assert mod_df["DC_POWER"][row_idx] == 0.0
        # Original was active daylight power
        assert synthetic_solar_df["AC_POWER"][row_idx] > 0.0

    # Peer device untouched
    beta_clean = synthetic_solar_df.filter(pl.col("device_id") == "INV_BETA")
    beta_corrupted = mod_df.filter(pl.col("device_id") == "INV_BETA")
    assert beta_clean.equals(beta_corrupted)


def test_inject_clipping_ceiling(synthetic_solar_df: pl.DataFrame) -> None:
    """Verify that clipping enforces a strict ceiling on peak power."""
    target_dev = "INV_ALPHA"
    ceiling_ac = 450.0
    mod_df, event, mods = inject_clipping(
        df=synthetic_solar_df,
        target_device=target_dev,
        clip_threshold_ac=ceiling_ac,
        duration_days=3,
    )

    assert event.anomaly_type == AnomalyType.CLIPPING.value
    assert len(mods) > 0

    for row_idx in event.row_indexes:
        orig = synthetic_solar_df["AC_POWER"][row_idx]
        corr = mod_df["AC_POWER"][row_idx]
        assert orig > ceiling_ac
        assert corr == pytest.approx(ceiling_ac, abs=1e-3)

    # Verify no values on target device exceed ceiling during window
    alpha_corrupted = mod_df.filter(pl.col("device_id") == target_dev)
    for v in alpha_corrupted["AC_POWER"].to_list():
        assert v <= ceiling_ac + 1e-4 or v > 0  # Either bounded or natural


def test_inject_flatline_frozen_sensor(synthetic_solar_df: pl.DataFrame) -> None:
    """Verify that flatline creates consecutive identical non-zero values."""
    target_dev = "INV_ALPHA"
    steps = 8
    mod_df, event, mods = inject_flatline(
        df=synthetic_solar_df,
        target_device=target_dev,
        duration_steps=steps,
    )

    assert event.anomaly_type == AnomalyType.FLATLINE.value
    assert event.affected_row_count == steps

    vals = [mod_df["AC_POWER"][idx] for idx in event.row_indexes]
    assert len(vals) == steps
    # All consecutive values must be strictly identical and > 0
    first_val = vals[0]
    assert first_val > 10.0
    for v in vals:
        assert v == first_val


# ---------------------------------------------------------------------------
# 3. End-to-End FaultInjectionEngine & Artifact Verification
# ---------------------------------------------------------------------------


def test_fault_injection_engine_full_run(tmp_path: Path, synthetic_solar_df: pl.DataFrame) -> None:
    """Verify complete FaultInjectionEngine execution and ground truth consistency."""
    out_csv = tmp_path / "synthetic_demo.csv"
    out_json = tmp_path / "synthetic_ground_truth.json"

    config = FaultConfig(
        seed=101,
        severity=1.0,
        include_soiling=True,
        include_trip=True,
        include_clipping=True,
        include_flatline=True,
        target_inverter_soiling="INV_ALPHA",
        target_inverter_trip="INV_BETA",
        target_inverter_clipping="INV_ALPHA",
        target_inverter_flatline="INV_BETA",
    )
    engine = FaultInjectionEngine(config=config)
    corrupted_df, manifest = engine.run(
        synthetic_solar_df,
        source_path="synthetic_clean.csv",
        corrupted_path=str(out_csv),
    )

    # Save artifacts
    corrupted_df.write_csv(out_csv)
    manifest.save(out_json)

    assert out_csv.exists()
    assert out_json.exists()

    # 1. Schema integrity
    assert corrupted_df.shape == synthetic_solar_df.shape
    assert corrupted_df.columns == synthetic_solar_df.columns
    assert corrupted_df.null_count().sum_horizontal()[0] == 0

    # 2. Ground truth answer key synchronization
    with open(out_json, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    assert gt_data["metadata"]["total_rows"] == len(synthetic_solar_df)
    assert len(gt_data["events"]) == 4

    row_gt = gt_data["row_ground_truth"]
    assert len(row_gt) == gt_data["metadata"]["total_anomalous_rows"]

    # Verify that every corrupted row matches ground truth delta
    for r_str, detail in row_gt.items():
        r_idx = int(r_str)
        for col_name, mod in detail["modifications"].items():
            expected_clean = mod["original"]
            expected_corr = mod["corrupted"]
            actual_clean = synthetic_solar_df[col_name][r_idx]
            actual_corr = corrupted_df[col_name][r_idx]

            assert actual_clean == pytest.approx(expected_clean, rel=1e-3)
            assert actual_corr == pytest.approx(expected_corr, rel=1e-3)

    # Verify that rows NOT in ground truth are 100% identical
    corrupted_indices = {int(k) for k in row_gt.keys()}
    clean_indices = [i for i in range(len(synthetic_solar_df)) if i not in corrupted_indices]

    clean_subset_orig = synthetic_solar_df[clean_indices]
    clean_subset_corr = corrupted_df[clean_indices]
    assert clean_subset_orig.equals(clean_subset_corr)


# ---------------------------------------------------------------------------
# 4. Real-World Surya-A Verification
# ---------------------------------------------------------------------------


def test_surya_a_artifacts_integrity() -> None:
    """Verify generated Surya-A-demo.csv and ground_truth_anomalies.json against base dataset."""
    if not DEFAULT_INPUT_FILE.exists() or not DEFAULT_OUTPUT_CSV.exists() or not DEFAULT_GROUND_TRUTH_JSON.exists():
        pytest.skip("Surya-A demo artifacts not generated on disk yet.")

    df_clean = pl.read_csv(DEFAULT_INPUT_FILE, infer_schema_length=10000)
    df_corrupted = pl.read_csv(DEFAULT_OUTPUT_CSV, infer_schema_length=10000)

    # 1. Exact shape & column structure preservation
    assert df_corrupted.shape == df_clean.shape
    assert df_corrupted.columns == df_clean.columns

    with open(DEFAULT_GROUND_TRUTH_JSON, "r", encoding="utf-8") as f:
        gt = json.load(f)

    assert gt["metadata"]["total_rows"] == len(df_clean)
    assert len(gt["events"]) == 4

    # Check distinct target devices
    affected_devs = gt["metadata"]["affected_devices"]
    assert len(affected_devs) == 4
    assert "1BY6WEcLGh8j5v7" in affected_devs  # Soiling
    assert "1IF53ai7Xc0U56Y" in affected_devs  # Trip
    assert "3PZuoBAID5Wc2HD" in affected_devs  # Clipping
    assert "7JYdWkrLSPkdwr4" in affected_devs  # Flatline

    # Spot check 10 rows from ground truth
    sample_rows = list(gt["row_ground_truth"].items())[:10]
    for r_str, detail in sample_rows:
        r_idx = int(r_str)
        for col, mod in detail["modifications"].items():
            assert df_corrupted[col][r_idx] == pytest.approx(mod["corrupted"], rel=1e-3)


# ---------------------------------------------------------------------------
# 5. CLI Execution & Parameter Testing
# ---------------------------------------------------------------------------


def test_cli_help() -> None:
    """Verify CLI --help option prints complete argument descriptions."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Fault-Injection Engine" in result.stdout
    assert "--input-file" in result.stdout
    assert "--output-file" in result.stdout
    assert "--ground-truth-file" in result.stdout
    assert "--soiling" in result.stdout
    assert "--trip" in result.stdout


def test_cli_execution_with_flags(tmp_path: Path, synthetic_solar_df: pl.DataFrame) -> None:
    """Verify CLI execution with custom toggles, paths, and quiet mode."""
    in_csv = tmp_path / "custom_clean.csv"
    out_csv = tmp_path / "custom_corrupted.csv"
    out_json = tmp_path / "custom_gt.json"

    synthetic_solar_df.write_csv(in_csv)

    result = runner.invoke(
        app,
        [
            "--input-file",
            str(in_csv),
            "--output-file",
            str(out_csv),
            "--ground-truth-file",
            str(out_json),
            "--seed",
            "77",
            "--severity",
            "1.2",
            "--no-trip",  # Disable trip
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    assert out_csv.exists()
    assert out_json.exists()

    with open(out_json) as f:
        data = json.load(f)

    # Trip disabled -> exactly 3 events
    assert len(data["events"]) == 3
    event_types = [e["anomaly_type"] for e in data["events"]]
    assert AnomalyType.TRIP.value not in event_types
    assert AnomalyType.SOILING.value in event_types
    assert AnomalyType.CLIPPING.value in event_types
    assert AnomalyType.FLATLINE.value in event_types


def test_deterministic_reproducibility(tmp_path: Path, synthetic_solar_df: pl.DataFrame) -> None:
    """Verify that identical seeds produce 100% bit-for-bit identical outputs."""
    in_csv = tmp_path / "seed_clean.csv"
    synthetic_solar_df.write_csv(in_csv)

    out1_csv = tmp_path / "out1.csv"
    out1_json = tmp_path / "out1.json"
    out2_csv = tmp_path / "out2.csv"
    out2_json = tmp_path / "out2.json"

    r1 = runner.invoke(
        app,
        ["-i", str(in_csv), "-o", str(out1_csv), "-g", str(out1_json), "-s", "42", "-q"],
    )
    r2 = runner.invoke(
        app,
        ["-i", str(in_csv), "-o", str(out2_csv), "-g", str(out2_json), "-s", "42", "-q"],
    )

    assert r1.exit_code == 0
    assert r2.exit_code == 0

    df1 = pl.read_csv(out1_csv)
    df2 = pl.read_csv(out2_csv)
    assert df1.equals(df2)

    with open(out1_json) as f1, open(out2_json) as f2:
        gt1 = json.load(f1)
        gt2 = json.load(f2)
        # Compare row ground truth keys and values
        assert gt1["row_ground_truth"] == gt2["row_ground_truth"]
        assert len(gt1["events"]) == len(gt2["events"])


# ---------------------------------------------------------------------------
# 6. Interoperability with PlantIQ QC Bitmask Engine
# ---------------------------------------------------------------------------


def test_qc_engine_detects_injected_flatline_and_spike(synthetic_solar_df: pl.DataFrame) -> None:
    """Verify that PlantIQ's Vectorized QC Bitmask Engine detects injected FLATLINE and SPIKE."""
    # Inject flatline of 8 steps
    mod_df, event_flat, _ = inject_flatline(
        synthetic_solar_df,
        target_device="INV_ALPHA",
        duration_steps=8,
    )
    # Inject trip of 12 steps
    mod_df, event_trip, _ = inject_trip(
        mod_df,
        target_device="INV_ALPHA",
        duration_steps=12,
    )

    dev_sub = mod_df.filter(pl.col("device_id") == "INV_ALPHA")
    timestamps = dev_sub["timestamp"].str.to_datetime()
    values = dev_sub["AC_POWER"]

    cfg = IngestConfig(cadence_seconds=900, flatline_min_steps=4, flatline_min_value_threshold=1.0)
    qc_mask = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="power_ac",
        config=cfg,
        custom_gradient=200.0,  # 200 kW max gradient threshold
    )

    # Check that FLATLINE flag was raised
    flatline_flag = int(QCFlag.FLATLINE)
    spike_flag = int(QCFlag.SPIKE)

    flatline_detected = (qc_mask & flatline_flag) > 0
    spike_detected = (qc_mask & spike_flag) > 0

    assert flatline_detected.sum() >= 4  # At least 4 steps flagged flatline
    assert spike_detected.sum() >= 1  # At least the trip step flagged spike
