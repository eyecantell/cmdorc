"""Tests for RunHandle - public facade for command runs.

Comprehensive test suite covering:
- Property delegation to RunResult
- Async wait() functionality with and without timeout
- Edge cases (already-finalized runs, race conditions, etc.)
- Integration with executors
"""

from __future__ import annotations

import asyncio

import pytest

from cmdorc import (
    MockExecutor,
    ResolvedCommand,
    RunHandle,
    RunResult,
    RunState,
)

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def sample_result() -> RunResult:
    """Fresh RunResult for testing."""
    return RunResult(command_name="test_cmd", run_id="run-1")


@pytest.fixture
def sample_handle(sample_result: RunResult) -> RunHandle:
    """Fresh RunHandle for testing."""
    # Create handle in non-async context (no event loop yet)
    # The future will be created lazily on first wait()
    return RunHandle(sample_result)


# =====================================================================
# Basic Properties Tests
# =====================================================================


class TestPropertyDelegation:
    """Tests for property delegation to RunResult."""

    def test_command_name_property(self, sample_handle: RunHandle):
        """RunHandle.command_name should return result's command_name."""
        assert sample_handle.command_name == "test_cmd"

    def test_run_id_property(self, sample_handle: RunHandle):
        """RunHandle.run_id should return result's run_id."""
        assert sample_handle.run_id == "run-1"

    def test_state_property(self, sample_handle: RunHandle):
        """RunHandle.state should return result's state."""
        assert sample_handle.state == RunState.PENDING

    def test_success_property_pending(self, sample_handle: RunHandle):
        """RunHandle.success should be None for pending runs."""
        assert sample_handle.success is None

    def test_success_property_after_completion(
        self, sample_result: RunResult, sample_handle: RunHandle
    ):
        """RunHandle.success should reflect result's success status."""
        sample_result.mark_success()
        assert sample_handle.success is True

    def test_output_property(self, sample_handle: RunHandle):
        """RunHandle.output should return result's output."""
        assert sample_handle.output == ""

    def test_error_property(self, sample_handle: RunHandle):
        """RunHandle.error should return result's error."""
        assert sample_handle.error is None

    def test_is_finalized_property(self, sample_handle: RunHandle):
        """RunHandle.is_finalized should return result's is_finalized."""
        assert sample_handle.is_finalized is False

    def test_start_time_property(self, sample_handle: RunHandle):
        """RunHandle.start_time should return result's start_time."""
        assert sample_handle.start_time is None

    def test_end_time_property(self, sample_handle: RunHandle):
        """RunHandle.end_time should return result's end_time."""
        assert sample_handle.end_time is None

    def test_comment_property(self, sample_handle: RunHandle):
        """RunHandle.comment should return result's comment."""
        assert sample_handle.comment == ""

    def test_duration_str_property(self, sample_handle: RunHandle):
        """RunHandle.duration_str should return result's duration_str."""
        # Before any run starts
        assert sample_handle.duration_str == "-"

    def test_resolved_command_property_none(self, sample_handle: RunHandle):
        """RunHandle.resolved_command should be None before command is prepared."""
        assert sample_handle.resolved_command is None

    def test_resolved_command_property_with_value(
        self, sample_result: RunResult, sample_handle: RunHandle
    ):
        """RunHandle.resolved_command should return resolved command after preparation."""
        # Set a resolved command on the result
        resolved = ResolvedCommand(
            command="pytest tests/",
            cwd="/home/user/project",
            env={"PATH": "/usr/bin"},
            timeout_secs=300,
            vars={"test_dir": "tests"},
        )
        sample_result.resolved_command = resolved

        # Should be accessible via handle
        assert sample_handle.resolved_command is resolved
        assert sample_handle.resolved_command.command == "pytest tests/"
        assert sample_handle.resolved_command.cwd == "/home/user/project"
        assert sample_handle.resolved_command.timeout_secs == 300

    def test_all_properties_read_only(self, sample_handle: RunHandle):
        """All properties should be read-only (no setters)."""
        with pytest.raises(AttributeError):
            sample_handle.command_name = "new_name"

        with pytest.raises(AttributeError):
            sample_handle.run_id = "new-id"

        with pytest.raises(AttributeError):
            sample_handle.state = RunState.SUCCESS


# =====================================================================
# Wait Functionality Tests
# =====================================================================


class TestWaitFunctionality:
    """Tests for async wait() method."""

    async def test_wait_completes_on_success(self, sample_result: RunResult):
        """wait() should complete when run finishes successfully."""
        handle = RunHandle(sample_result)

        # Mark as running then success
        sample_result.mark_running()
        await asyncio.sleep(0.01)
        sample_result.mark_success()

        # Wait should complete
        result = await handle.wait()
        assert result is sample_result
        assert result.state == RunState.SUCCESS

    async def test_wait_completes_on_failure(self, sample_result: RunResult):
        """wait() should complete when run fails."""
        handle = RunHandle(sample_result)

        sample_result.mark_running()
        await asyncio.sleep(0.01)
        sample_result.mark_failed("Test error")

        result = await handle.wait()
        assert result.state == RunState.FAILED
        assert "Test error" in str(result.error)

    async def test_wait_completes_on_cancelled(self, sample_result: RunResult):
        """wait() should complete when run is cancelled."""
        handle = RunHandle(sample_result)

        sample_result.mark_running()
        await asyncio.sleep(0.01)
        sample_result.mark_cancelled("User request")

        result = await handle.wait()
        assert result.state == RunState.CANCELLED

    async def test_wait_timeout_success(self, sample_result: RunResult):
        """wait() with timeout should complete if run finishes in time."""
        handle = RunHandle(sample_result)

        sample_result.mark_running()
        await asyncio.sleep(0.01)
        sample_result.mark_success()

        # Timeout longer than execution time
        result = await handle.wait(timeout=1.0)
        assert result.state == RunState.SUCCESS

    async def test_wait_timeout_expiration(self, sample_result: RunResult):
        """wait() should raise TimeoutError if timeout expires."""
        handle = RunHandle(sample_result)

        sample_result.mark_running()
        # Don't mark as finished - timeout will expire

        with pytest.raises(asyncio.TimeoutError):
            await handle.wait(timeout=0.05)

    async def test_wait_already_finalized_run(self, sample_result: RunResult):
        """wait() should return immediately for already-finalized runs."""
        sample_result.mark_success()
        handle = RunHandle(sample_result)

        # Should return immediately without waiting
        result = await handle.wait()
        assert result.state == RunState.SUCCESS

    async def test_multiple_concurrent_waiters(self, sample_result: RunResult):
        """Multiple concurrent await wait() calls should all receive same result."""
        handle = RunHandle(sample_result)

        # Start multiple waiters concurrently
        tasks = [handle.wait() for _ in range(3)]

        # Give them time to start waiting
        await asyncio.sleep(0.01)

        # Complete the run
        sample_result.mark_success()

        # All waiters should complete with same result
        results = await asyncio.gather(*tasks)
        assert all(r is sample_result for r in results)
        assert all(r.state == RunState.SUCCESS for r in results)


# =====================================================================
# Edge Cases Tests
# =====================================================================


class TestEdgeCases:
    """Tests for edge cases and race conditions."""

    async def test_handle_for_already_finalized_run(self, sample_result: RunResult):
        """Creating handle for already-finalized run should work correctly."""
        sample_result.mark_success()
        handle = RunHandle(sample_result)

        # is_finalized should be immediately true
        assert handle.is_finalized is True

        # wait() should return immediately
        result = await asyncio.wait_for(handle.wait(), timeout=0.1)
        assert result.state == RunState.SUCCESS

    async def test_race_condition_finish_during_init(self):
        """Run finishing during init shouldn't cause issues."""
        result = RunResult(command_name="test", run_id="run-1")

        # Mark as finished
        result.mark_success()

        # Create handle after run is finished
        handle = RunHandle(result)

        # Should still work correctly
        result2 = await handle.wait()
        assert result2 is result
        assert result2.state == RunState.SUCCESS

    async def test_watcher_cleanup_on_task_cancellation(self, sample_result: RunResult):
        """Watcher task should handle cancellation gracefully."""
        handle = RunHandle(sample_result)

        # Create a wait task to initialize the watcher
        wait_task = asyncio.create_task(handle.wait())

        # Give it time to start the watcher
        await asyncio.sleep(0.01)

        # Get the watcher task
        watcher = handle._watcher_task
        assert watcher is not None

        # Cancel the watcher task
        watcher.cancel()

        # Wait for it to be cancelled
        with pytest.raises(asyncio.CancelledError):
            await watcher

        # The future should also be cancelled
        assert handle._future.cancelled()

        # Clean up the wait task
        wait_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait_task

    def test_repr_format(self, sample_handle: RunHandle):
        """__repr__ should provide useful debug information."""
        repr_str = repr(sample_handle)

        assert "RunHandle" in repr_str
        assert "test_cmd" in repr_str
        assert "run-1" in repr_str
        assert "PENDING" in repr_str


# =====================================================================
# Integration Tests with Executors
# =====================================================================


class TestIntegrationWithExecutor:
    """Tests for integration with executors."""

    async def test_full_flow_with_mock_executor(self):
        """Full flow: create result, handle, start executor, wait on handle."""
        result = RunResult(command_name="test", run_id="run-1")
        handle = RunHandle(result)

        # Simulate execution with MockExecutor
        executor = MockExecutor(delay=0.05)
        resolved = ResolvedCommand(
            command="echo hello",
            cwd=None,
            env={},
            timeout_secs=None,
            vars={},
        )

        await executor.start_run(result, resolved)

        # Wait for completion
        completed = await handle.wait()
        assert completed.state == RunState.SUCCESS
        # MockExecutor produces simulated output
        assert "Simulated" in completed.output or "hello" in completed.output

    async def test_cancellation_flow_via_executor(self):
        """Test that executor cancellation is observed by handle."""
        result = RunResult(command_name="test", run_id="run-1")
        handle = RunHandle(result)

        executor = MockExecutor(delay=1.0)  # Long delay
        resolved = ResolvedCommand(
            command="sleep 10",
            cwd=None,
            env={},
            timeout_secs=None,
            vars={},
        )

        task = asyncio.create_task(executor.start_run(result, resolved))

        # Let it start
        await asyncio.sleep(0.02)

        # Cancel via executor
        await executor.cancel_run(result, "Test cancellation")

        # Handle should see the cancelled state
        completed = await handle.wait(timeout=0.5)
        assert completed.state == RunState.CANCELLED

        # Wait for executor task to finish
        await task

    async def test_multiple_waiters_same_handle(self):
        """Multiple concurrent wait() calls on the same handle should all complete."""
        result = RunResult(command_name="test", run_id="run-1")
        handle = RunHandle(result)

        # Start multiple waiters on the SAME handle
        tasks = [handle.wait() for _ in range(3)]
        await asyncio.sleep(0.01)  # Let them start

        result.mark_success()

        results = await asyncio.gather(*tasks)
        assert len(results) == 3
        assert all(r is result for r in results)
        assert all(r.state == RunState.SUCCESS for r in results)

    async def test_multiple_independent_runs(self):
        """Multiple independent runs with their own handles should all complete."""
        results = [RunResult(command_name="test", run_id=f"run-{i}") for i in range(3)]
        handles = [RunHandle(r) for r in results]
        tasks = [h.wait() for h in handles]

        await asyncio.sleep(0.01)

        for r in results:
            r.mark_success()

        await asyncio.gather(*tasks)
        assert all(r.state == RunState.SUCCESS for r in results)


# =====================================================================
# Internal Access Tests
# =====================================================================


class TestInternalAccess:
    """Tests for advanced internal access patterns."""

    def test_internal_result_access(self, sample_handle: RunHandle):
        """_result should provide access to underlying RunResult."""
        assert sample_handle._result is not None
        assert isinstance(sample_handle._result, RunResult)

    async def test_internal_result_state_changes(self, sample_handle: RunHandle):
        """State changes via _result should be visible via handle properties."""
        assert sample_handle.state == RunState.PENDING

        sample_handle._result.mark_running()
        assert sample_handle.state == RunState.RUNNING

        sample_handle._result.mark_success()
        assert sample_handle.state == RunState.SUCCESS


# =====================================================================
# Timeout Edge Cases
# =====================================================================


class TestTimeoutEdgeCases:
    """Tests for timeout-related edge cases."""

    async def test_wait_with_zero_timeout_failing(self, sample_result: RunResult):
        """wait(timeout=0) on pending run should timeout immediately."""
        handle = RunHandle(sample_result)

        with pytest.raises(asyncio.TimeoutError):
            await handle.wait(timeout=0.0)

    async def test_wait_with_negative_timeout(self, sample_result: RunResult):
        """wait() with negative timeout should timeout immediately."""
        handle = RunHandle(sample_result)

        with pytest.raises(asyncio.TimeoutError):
            await handle.wait(timeout=-1.0)

    async def test_wait_with_zero_timeout_on_finished(self, sample_result: RunResult):
        """wait(timeout=0) on finished run should return immediately."""
        sample_result.mark_success()
        handle = RunHandle(sample_result)

        result = await handle.wait(timeout=0.0)
        assert result.state == RunState.SUCCESS

    async def test_very_short_timeout_on_quick_run(self):
        """Very short timeout should work on quick-finishing runs."""
        result = RunResult(command_name="test", run_id="run-1")
        handle = RunHandle(result)

        # Finish immediately
        result.mark_success()

        # Even 0.001s timeout should work
        completed = await handle.wait(timeout=0.001)
        assert completed.state == RunState.SUCCESS
