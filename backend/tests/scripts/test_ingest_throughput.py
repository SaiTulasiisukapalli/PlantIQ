"""Unit and CLI tests for Ingestion Throughput Benchmark CLI.

Task: S2-AI-03 (NFR-1 Benchmark Test Suite)
Validates:
- Typer CLI execution, flags (--file, --target-throughput, --batch-size, --json, --verbose, --help).
- HeartbeatMonitor precision and event loop latency monitoring.
- Programmatic benchmark execution on real datasets.
- JSON output schema and metrics assertions.
- Error handling for nonexistent datasets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import pytest
from typer.testing import CliRunner

from backend.scripts.test_ingest_throughput import (
    DATASETS_DIR,
    DEFAULT_P1_WEATHER_FILE,
    HeartbeatMonitor,
    app,
    run_throughput_benchmark,
)

runner = CliRunner()


def test_cli_help() -> None:
    """Verify CLI --help option renders command description and available options."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Benchmark telemetry ingestion throughput" in result.output
    assert "--target-throughput" in result.output
    assert "--batch-size" in result.output
    assert "--json" in result.output
    assert "--verbose" in result.output


def test_cli_json_weather_benchmark() -> None:
    """Verify CLI execution with --json outputs valid metrics and passes NFR-1."""
    if not DEFAULT_P1_WEATHER_FILE.exists():
        pytest.skip(f"Dataset not found at {DEFAULT_P1_WEATHER_FILE}")

    result = runner.invoke(
        app,
        [
            "-f",
            str(DEFAULT_P1_WEATHER_FILE),
            "--target-throughput",
            "5000",
            "--json",
        ],
    )
    assert result.exit_code == 0

    data: Dict[str, Any] = json.loads(result.output)
    assert data["dataset_name"] == "Plant_1_Weather_Sensor_Data.csv"
    assert data["total_rows_processed"] == 3182
    assert data["observations_created"] > 0
    assert data["throughput_rows_per_sec"] > 5000.0
    assert data["max_heartbeat_delay_ms"] < 250.0
    assert data["event_loop_healthy"] is True
    assert data["throughput_met"] is True
    assert data["passed"] is True
    assert "qc_clean" in data
    assert "qc_gap" in data
    assert "qc_flatline" in data
    assert "qc_range" in data
    assert "qc_spike" in data


def test_cli_nonexistent_file() -> None:
    """Verify CLI aborts cleanly when input dataset does not exist."""
    result = runner.invoke(app, ["-f", "nonexistent_solar_data.csv"])
    assert result.exit_code != 0
    assert "File not found" in result.output


@pytest.mark.asyncio
async def test_heartbeat_monitor() -> None:
    """Verify HeartbeatMonitor records latency samples and detects stalls accurately."""
    monitor = HeartbeatMonitor(interval_ms=10.0)
    monitor.start()

    # Allow a few heartbeats to tick
    import asyncio
    await asyncio.sleep(0.05)

    max_delay = await monitor.stop()
    assert isinstance(max_delay, float)
    assert max_delay >= 0.0
    assert max_delay < 100.0  # Normal delay should be well below 100ms


@pytest.mark.asyncio
async def test_run_benchmark_programmatic() -> None:
    """Verify programmatic benchmark runner execution on weather dataset."""
    if not DEFAULT_P1_WEATHER_FILE.exists():
        pytest.skip(f"Dataset not found at {DEFAULT_P1_WEATHER_FILE}")

    passed, result, metrics = await run_throughput_benchmark(
        file_path=DEFAULT_P1_WEATHER_FILE,
        target_throughput=5000.0,
        batch_size=2000,
        quiet=True,
    )

    assert passed is True
    assert metrics["dataset_name"] == "Plant_1_Weather_Sensor_Data.csv"
    assert metrics["total_rows_processed"] == 3182
    assert metrics["passed"] is True
    assert metrics["throughput_rows_per_sec"] >= 5000.0
    assert metrics["event_loop_healthy"] is True
