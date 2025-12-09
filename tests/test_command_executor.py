# tests/test_command_executor.py
"""
Comprehensive test suite for CommandExecutor implementations.

Tests both MockExecutor and LocalSubprocessExecutor.
"""

import asyncio
import sys

import pytest

from cmdorc.command_executor import CommandExecutor
from cmdorc.local_subprocess_executor import LocalSubprocessExecutor
from cmdorc.mock_executor import MockExecutor
from cmdorc.run_result import ResolvedCommand, RunResult, RunState

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture
def mock_executor():
    """Fresh MockExecutor."""
    return MockExecutor()


@pytest.fixture
def local_executor():
    """Fresh LocalSubprocessExecutor."""
    return LocalSubprocessExecutor(cancel_grace_period=0.5)


@pytest.fixture
def sample_result():
    """Sample RunResult for testing."""
    return RunResult(command_name="test_cmd", run_id="test-run-123")


@pytest.fixture
def simple_resolved():
    """Simple resolved command."""
    return ResolvedCommand(
        command="echo 'Hello World'",
        cwd=None,
        env={},
        timeout_secs=None,
        vars={},
    )


# ================================================================
# MockExecutor Tests
# ================================================================


@pytest.mark.asyncio
async def test_mock_executor_success(mock_executor, sample_result, simple_resolved):
    """Test MockExecutor simulates successful execution."""
    await mock_executor.start_run(sample_result, simple_resolved)

    # Wait for completion
    await asyncio.sleep(0.05)

    assert sample_result.state == RunState.SUCCESS
    assert sample_result.success is True
    assert sample_result.output == "Simulated output"
    assert len(mock_executor.started) == 1


@pytest.mark.asyncio
async def test_mock_executor_failure(sample_result, simple_resolved):
    """Test MockExecutor simulates failure."""
    executor = MockExecutor(should_fail=True, failure_message="Test error")

    await executor.start_run(sample_result, simple_resolved)
    await asyncio.sleep(0.05)

    assert sample_result.state == RunState.FAILED
    assert sample_result.success is False
    assert sample_result.error == "Test error"


@pytest.mark.asyncio
async def test_mock_executor_delay(sample_result, simple_resolved):
    """Test MockExecutor respects delay."""
    executor = MockExecutor(delay=0.1)

    await executor.start_run(sample_result, simple_resolved)

    # Should still be running
    await asyncio.sleep(0.05)
    assert sample_result.state == RunState.RUNNING

    # Should complete after full delay
    await asyncio.sleep(0.1)
    assert sample_result.state == RunState.SUCCESS


@pytest.mark.asyncio
async def test_mock_executor_cancellation(mock_executor, sample_result, simple_resolved):
    """Test MockExecutor cancellation."""
    mock_executor.delay = 0.2

    await mock_executor.start_run(sample_result, simple_resolved)
    await asyncio.sleep(0.05)  # Let it start

    assert sample_result.state == RunState.RUNNING

    # Cancel it
    await mock_executor.cancel_run(sample_result, comment="Test cancel")

    assert sample_result.state == RunState.CANCELLED
    assert len(mock_executor.cancelled) == 1
    assert mock_executor.cancelled[0][1] == "Test cancel"


@pytest.mark.asyncio
async def test_mock_executor_cleanup(mock_executor, simple_resolved):
    """Test MockExecutor cleanup."""
    # Start multiple runs
    results = [RunResult(command_name="test", run_id=f"run-{i}") for i in range(3)]

    for result in results:
        await mock_executor.start_run(result, simple_resolved)

    await mock_executor.cleanup()

    assert mock_executor.cleaned_up is True


@pytest.mark.asyncio
async def test_mock_executor_reset(mock_executor, sample_result, simple_resolved):
    """Test MockExecutor reset clears history."""
    await mock_executor.start_run(sample_result, simple_resolved)
    await mock_executor.cancel_run(sample_result)

    assert len(mock_executor.started) == 1
    assert len(mock_executor.cancelled) == 1

    mock_executor.reset()

    assert len(mock_executor.started) == 0
    assert len(mock_executor.cancelled) == 0


# ================================================================
# LocalSubprocessExecutor Tests
# ================================================================


@pytest.mark.asyncio
async def test_local_executor_success(local_executor):
    """Test LocalSubprocessExecutor runs simple command successfully."""
    result = RunResult(command_name="echo_test")
    resolved = ResolvedCommand(
        command="echo 'Hello World'",
        cwd=None,
        env={},
        timeout_secs=None,
        vars={},
    )

    await local_executor.start_run(result, resolved)

    # Wait for completion
    await asyncio.sleep(0.5)

    assert result.state == RunState.SUCCESS
    assert result.success is True
    assert "Hello World" in result.output
    assert result.start_time is not None
    assert result.end_time is not None
    assert result.duration is not None


@pytest.mark.asyncio
async def test_local_executor_failure(local_executor):
    """Test LocalSubprocessExecutor handles command failure."""
    result = RunResult(command_name="failing_cmd")
    resolved = ResolvedCommand(
        command="exit 42",
        cwd=None,
        env={},
        timeout_secs=None,
        vars={},
    )

    await local_executor.start_run(result, resolved)
    await asyncio.sleep(0.5)

    assert result.state == RunState.FAILED
    assert result.success is False
    assert "exited with code 42" in str(result.error)


@pytest.mark.asyncio
async def test_local_executor_output_capture(local_executor):
    """Test LocalSubprocessExecutor captures output."""
    result = RunResult(command_name="multiline_output")
    resolved = ResolvedCommand(
        command="echo 'Line 1' && echo 'Line 2' && echo 'Line 3'",
        cwd=None,
        env={},
        timeout_secs=None,
        vars={},
    )

    await local_executor.start_run(result, resolved)
    await asyncio.sleep(0.5)

    assert result.state == RunState.SUCCESS
    assert "Line 1" in result.output
    assert "Line 2" in result.output
    assert "Line 3" in result.output


@pytest.mark.asyncio
async def test_local_executor_timeout(local_executor):
    """Test LocalSubprocessExecutor enforces timeout."""
    result = RunResult(command_name="timeout_test")
    resolved = ResolvedCommand(
        command="sleep 10",  # Long sleep
        cwd=None,
        env={},
        timeout_secs=0.2,  # Short timeout
        vars={},
    )

    await local_executor.start_run(result, resolved)
    await asyncio.sleep(0.5)

    assert result.state == RunState.FAILED
    assert result.success is False
    assert "timed out" in str(result.error).lower()


@pytest.mark.asyncio
async def test_local_executor_cancellation(local_executor):
    """Test LocalSubprocessExecutor cancellation."""
    result = RunResult(command_name="cancellable_cmd")
    resolved = ResolvedCommand(
        command="sleep 10",  # Long-running
        cwd=None,
        env={},
        timeout_secs=None,
        vars={},
    )

    await local_executor.start_run(result, resolved)
    await asyncio.sleep(0.1)  # Let it start

    assert result.state == RunState.RUNNING

    # Cancel it
    await local_executor.cancel_run(result, comment="User stopped")

    assert result.state == RunState.CANCELLED
    assert result.success is None


@pytest.mark.asyncio
async def test_local_executor_cancel_finished_is_noop(local_executor):
    """Test cancelling finished run is a no-op."""
    result = RunResult(command_name="fast_cmd")
    resolved = ResolvedCommand(
        command="echo 'done'",
        cwd=None,
        env={},
        timeout_secs=None,
        vars={},
    )

    await local_executor.start_run(result, resolved)
    await asyncio.sleep(0.5)  # Wait for completion

    assert result.state == RunState.SUCCESS

    # Try to cancel (should be no-op)
    await local_executor.cancel_run(result)

    # State should remain SUCCESS
    assert result.state == RunState.SUCCESS


@pytest.mark.asyncio
async def test_local_executor_environment_variables(local_executor):
    """Test LocalSubprocessExecutor passes environment variables."""
    result = RunResult(command_name="env_test")

    # Command that prints an environment variable
    if sys.platform == "win32":
        command = "echo %TEST_VAR%"
    else:
        command = "echo $TEST_VAR"

    resolved = ResolvedCommand(
        command=command,
        cwd=None,
        env={"TEST_VAR": "test_value_123"},
        timeout_secs=None,
        vars={},
    )

    await local_executor.start_run(result, resolved)
    await asyncio.sleep(0.5)

    assert result.state == RunState.SUCCESS
    assert "test_value_123" in result.output


@pytest.mark.asyncio
async def test_local_executor_concurrent_runs(local_executor):
    """Test LocalSubprocessExecutor handles concurrent runs."""
    results = []

    for i in range(3):
        result = RunResult(command_name=f"concurrent_{i}")
        resolved = ResolvedCommand(
            command=f"echo 'Run {i}'",
            cwd=None,
            env={},
            timeout_secs=None,
            vars={},
        )

        await local_executor.start_run(result, resolved)
        results.append(result)

    # Wait for all to complete
    await asyncio.sleep(1.0)

    # All should succeed
    for i, result in enumerate(results):
        assert result.state == RunState.SUCCESS
        assert f"Run {i}" in result.output


@pytest.mark.asyncio
async def test_local_executor_cleanup(local_executor):
    """Test LocalSubprocessExecutor cleanup cancels active runs."""
    results = []

    # Start multiple long-running commands
    for i in range(3):
        result = RunResult(command_name=f"cleanup_test_{i}")
        resolved = ResolvedCommand(
            command="sleep 10",
            cwd=None,
            env={},
            timeout_secs=None,
            vars={},
        )

        await local_executor.start_run(result, resolved)
        results.append(result)

    await asyncio.sleep(0.2)  # Let them start

    # All should be running
    for result in results:
        assert result.state == RunState.RUNNING

    # Cleanup
    await local_executor.cleanup()

    # Verify cleanup
    assert len(local_executor._processes) == 0
    assert len(local_executor._tasks) == 0


@pytest.mark.asyncio
async def test_local_executor_supports_features(local_executor):
    """Test LocalSubprocessExecutor feature support."""
    assert local_executor.supports_feature("timeout")
    assert local_executor.supports_feature("output_capture")
    assert local_executor.supports_feature("signal_handling")
    assert not local_executor.supports_feature("unknown_feature")


# ================================================================
# Abstract Interface Tests
# ================================================================


def test_executor_is_abstract():
    """Test that CommandExecutor cannot be instantiated."""
    with pytest.raises(TypeError):
        CommandExecutor()


@pytest.mark.asyncio
async def test_executor_default_cleanup():
    """Test that default cleanup implementation does nothing."""

    class MinimalExecutor(CommandExecutor):
        async def start_run(self, result, resolved):
            pass

        async def cancel_run(self, result, comment=None):
            pass

    executor = MinimalExecutor()
    await executor.cleanup()  # Should not raise


def test_executor_default_supports_feature():
    """Test that default supports_feature returns False."""

    class MinimalExecutor(CommandExecutor):
        async def start_run(self, result, resolved):
            pass

        async def cancel_run(self, result, comment=None):
            pass

    executor = MinimalExecutor()
    assert executor.supports_feature("anything") is False
