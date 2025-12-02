# tests/test_command_runner/test_cancellation.py
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus, RunState
import logging
logging.getLogger("cmdorc").setLevel(logging.DEBUG)

@pytest.mark.asyncio
async def test_cancel_on_triggers_stops_running_command():
    """Test that cancel_on_triggers actually cancels running commands."""
    cfg = CommandConfig(
        name="Cancelable",
        command="sleep 100",
        triggers=["start"],
        cancel_on_triggers=["stop", "abort"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])

    # Create a properly synchronized mock process
    proc = AsyncMock()
    proc.returncode = None
    killed_event = asyncio.Event()

    def kill_handler():
        """Synchronous kill that sets returncode and signals event."""
        proc.returncode = -9
        killed_event.set()

    proc.kill = Mock(side_effect=kill_handler)
    proc.terminate = Mock(side_effect=kill_handler)

    async def communicate_waits():
        """Wait for kill signal, then return."""
        await killed_event.wait()
        return (b"", b"")

    proc.communicate = communicate_waits

    async def wait_for_kill():
        """Wait for kill signal, then return exit code."""
        await killed_event.wait()
        return -9

    proc.wait = wait_for_kill

    with patch("asyncio.create_subprocess_shell", new=AsyncMock(return_value=proc)):
        # Start the command
        await runner.trigger("start")
        assert await runner.wait_for_status("Cancelable", CommandStatus.RUNNING, timeout=1.0)

        # Give the execute coroutine time to reach communicate() and start waiting
        await asyncio.sleep(0.1)

        # Verify we have a live run
        live_runs = runner.get_live_runs("Cancelable")
        assert len(live_runs) == 1, "Should have 1 live run before cancellation"

        # Trigger cancellation via cancel_on_triggers
        await runner.trigger("stop")

        # Give time for:
        # 1. trigger() to call run.cancel()
        # 2. task.cancel() to propagate CancelledError
        # 3. _execute() to catch it and call proc.kill()
        # 4. kill_handler to set the event
        # 5. communicate() to return
        # 6. _task_completed() to finalize
        await asyncio.sleep(0.3)

        # Should now be cancelled
        assert await runner.wait_for_status("Cancelable", CommandStatus.CANCELLED, timeout=1.0)
        result = runner.get_result("Cancelable")
        assert result.state == RunState.CANCELLED

        # Verify no live runs remain
        live_runs = runner.get_live_runs("Cancelable")
        assert len(live_runs) == 0, "Should have no live runs after cancellation"


@pytest.mark.asyncio
async def test_cancel_all_cancels_multiple(create_long_running_proc):
    configs = [
        CommandConfig(name="A", command="sleep 100", triggers=["start"]),
        CommandConfig(name="B", command="sleep 100", triggers=["start"]),
    ]
    runner = CommandRunner(configs)
    proc = create_long_running_proc
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_running("A", timeout=1.0)
        assert await runner.wait_for_running("B", timeout=1.0)
        runner.cancel_all()
        assert await runner.wait_for_cancelled("A", timeout=2.0)
        assert await runner.wait_for_cancelled("B", timeout=2.0)
