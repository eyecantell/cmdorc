# tests/test_command_runner/test_concurrency.py
import asyncio
from unittest.mock import patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus, RunState


@pytest.mark.asyncio
async def test_cancel_and_restart_policy(create_long_running_proc):
    cfg = CommandConfig(
        name="Sleepy",
        command="sleep 10",
        triggers=["start"],
        max_concurrent=1,
        on_retrigger="cancel_and_restart",
        keep_history=10,
    )
    runner = CommandRunner([cfg])
    # create_long_running_proc is already the proc object (injected by pytest)
    proc = create_long_running_proc

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_status("Sleepy", CommandStatus.RUNNING, timeout=1.0)
        first_run_id = runner.get_result("Sleepy").run_id

        await runner.trigger("start")
        await asyncio.sleep(0.2)

        assert await runner.wait_for_status("Sleepy", CommandStatus.RUNNING, timeout=2.0)
        second_run_id = runner.get_result("Sleepy").run_id
        assert first_run_id != second_run_id  # Verify it's a new run

        history = runner.get_history("Sleepy")
        assert len(history) >= 1
        # First run should be cancelled
        cancelled_runs = [r for r in history if r.state == RunState.CANCELLED]
        assert len(cancelled_runs) >= 1

@pytest.mark.asyncio
async def test_ignore_retrigger_policy(create_long_running_proc):
    cfg = CommandConfig(
        name="Sleepy",
        command="sleep 10",
        triggers=["start"],
        max_concurrent=1,
        on_retrigger="ignore",
        keep_history=10,
    )
    runner = CommandRunner([cfg])
    proc = create_long_running_proc
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_running("Sleepy", timeout=1.0)
        first_run_id = runner.get_result("Sleepy").run_id
        await runner.trigger("start")
        await asyncio.sleep(0.2)
        assert runner.get_result("Sleepy").run_id == first_run_id  # No restart
        history = runner.get_history("Sleepy")
        assert not any(r.state == RunState.CANCELLED for r in history)
        runner.cancel_command("Sleepy")  # Clean up
