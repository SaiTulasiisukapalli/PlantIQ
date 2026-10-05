"""Unit and CLI tests for eval_mapping.py evaluation benchmark.

Task: S2-AI-02
Validates:
- Benchmark dataset registry completeness and ground truth format.
- Mock LLM transport and deterministic multilingual inference.
- Programmatic evaluation engine enforcing >= 85% accuracy requirement.
- Typer CLI execution, flags (--mock-llm, --json, --verbose, --min-accuracy),
  and exit code assertions.
"""

from __future__ import annotations

import json
from typing import Any, Dict
import pytest
from typer.testing import CliRunner

from backend.scripts.eval_mapping import (
    EVALUATION_DATASETS,
    app,
    create_mock_eval_provider,
    run_evaluation,
)

runner = CliRunner()


def test_evaluation_datasets_registry() -> None:
    """Verify evaluation benchmark dataset definitions and integrity."""
    assert len(EVALUATION_DATASETS) == 6

    total_headers = sum(len(ds.headers) for ds in EVALUATION_DATASETS)
    assert total_headers == 51

    dataset_names = [ds.name for ds in EVALUATION_DATASETS]
    assert "Kaggle Solar PV (Plants 1 & 2)" in dataset_names
    assert "SMA Solar Inverters (Sunny Tripower)" in dataset_names
    assert "Huawei FusionSolar SCADA" in dataset_names
    assert "Campbell Scientific Weather Stations" in dataset_names
    assert "Meteocontrol & Schneider Loggers" in dataset_names
    assert "Multilingual & Foreign Headers (Tier 2 LLM Stress Test)" in dataset_names


def test_mock_eval_provider_responses() -> None:
    """Verify mock provider returns valid responses for evaluation stress tests."""
    provider = create_mock_eval_provider()
    assert provider is not None
    assert hasattr(provider, "chat")


def test_run_evaluation_programmatic() -> None:
    """Verify programmatic evaluation execution achieves >= 85% Top-1 accuracy."""
    passed, accuracy, summary = run_evaluation(
        threshold=0.80,
        min_accuracy=85.0,
        mock_llm=True,
        verbose=False,
    )

    assert passed is True
    assert accuracy >= 85.0
    assert accuracy == 100.0  # 51 / 51 matches
    assert summary["total_headers"] == 51
    assert summary["correct_count"] == 51
    assert summary["failed_count"] == 0
    assert summary["exact_matches"] >= 35
    assert summary["fuzzy_matches"] >= 5
    assert summary["llm_fallbacks"] >= 2


def test_cli_help() -> None:
    """Verify CLI --help option prints descriptive documentation."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Run the Column Mapping Auto-Suggester Benchmark Suite." in result.stdout
    assert "--threshold" in result.stdout
    assert "--min-accuracy" in result.stdout
    assert "--json" in result.stdout


def test_cli_default_run() -> None:
    """Verify CLI execution passes with default settings and mock LLM."""
    result = runner.invoke(app, ["--mock-llm"])
    assert result.exit_code == 0
    assert "Benchmark Result: PASSED" in result.stdout
    assert "100.00%" in result.stdout


def test_cli_json_output() -> None:
    """Verify CLI --json flag outputs parseable JSON report without Rich markup."""
    result = runner.invoke(app, ["--mock-llm", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert data["passed"] is True
    assert data["accuracy_pct"] == 100.0
    assert data["total_headers"] == 51
    assert data["correct_count"] == 51
    assert data["failed_count"] == 0
    assert len(data["datasets"]) == 6


def test_cli_verbose_flag() -> None:
    """Verify CLI --verbose flag includes detailed header prediction table."""
    result = runner.invoke(app, ["--mock-llm", "--verbose"])
    assert result.exit_code == 0
    assert "Detailed Header Predictions" in result.stdout
    assert "DATE_TIME" in result.stdout
    assert "Benchmark Result: PASSED" in result.stdout


def test_cli_failing_threshold_exit_code() -> None:
    """Verify CLI exits with code 1 if accuracy falls below an impossible requirement."""
    result = runner.invoke(app, ["--mock-llm", "--min-accuracy", "101.0"])
    assert result.exit_code == 1
    assert "Benchmark Result: FAILED" in result.stdout
