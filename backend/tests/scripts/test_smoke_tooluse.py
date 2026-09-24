"""Unit and CLI tests for smoke_tooluse.py.

Task: S1-AI-05
Ensures that the smoke test CLI runs cleanly in mock/offline mode with zero
network dependencies, verifying both Anthropic and OpenAI-compatible providers,
streaming, error branches, and CLI exit codes.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from backend.scripts.smoke_tooluse import app, run_smoke_test

runner = CliRunner()


@pytest.mark.asyncio
async def test_run_smoke_test_anthropic_mock() -> None:
    """Verify run_smoke_test succeeds for Anthropic in mock mode."""
    success = await run_smoke_test(
        provider_name="anthropic",
        mock=True,
        test_streaming=False,
    )
    assert success is True


@pytest.mark.asyncio
async def test_run_smoke_test_openai_compatible_mock() -> None:
    """Verify run_smoke_test succeeds for OpenAI-compatible in mock mode."""
    success = await run_smoke_test(
        provider_name="openai_compatible",
        mock=True,
        test_streaming=False,
    )
    assert success is True


@pytest.mark.asyncio
async def test_run_smoke_test_with_streaming_mock() -> None:
    """Verify run_smoke_test succeeds with streaming flag enabled in mock mode."""
    success = await run_smoke_test(
        provider_name="anthropic",
        mock=True,
        test_streaming=True,
    )
    assert success is True

    openai_success = await run_smoke_test(
        provider_name="openai_compatible",
        mock=True,
        test_streaming=True,
    )
    assert openai_success is True


@pytest.mark.asyncio
async def test_run_smoke_test_invalid_provider() -> None:
    """Verify run_smoke_test handles invalid providers gracefully."""
    success = await run_smoke_test(
        provider_name="invalid_cloud_provider",
        mock=True,
    )
    assert success is False


def test_cli_smoke_tooluse_anthropic_mock() -> None:
    """Verify CLI invocation exit code and output for Anthropic mock."""
    result = runner.invoke(app, ["--mock", "--provider", "anthropic"])
    assert result.exit_code == 0
    assert "SUCCESS: Tool-use invocation verified for 'anthropic'!" in result.stdout
    assert "get_current_time" in result.stdout


def test_cli_smoke_tooluse_openai_mock() -> None:
    """Verify CLI invocation exit code and output for OpenAI-compatible mock."""
    result = runner.invoke(app, ["--mock", "--provider", "openai_compatible", "--stream"])
    assert result.exit_code == 0
    assert "SUCCESS: Tool-use invocation verified for 'openai_compatible'!" in result.stdout
    assert "get_current_time" in result.stdout
    assert "Streaming successfully yielded" in result.stdout


def test_cli_smoke_tooluse_invalid_provider_fails() -> None:
    """Verify CLI exits with non-zero code on invalid provider."""
    result = runner.invoke(app, ["--mock", "--provider", "unsupported_llm"])
    assert result.exit_code != 0
