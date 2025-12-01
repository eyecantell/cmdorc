# tests/test_command_runner/test_concurrency.py
import asyncio
import pytest
from unittest.mock import patch
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
    proc = create_long_running_proc()

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_status("Sleepy", CommandStatus.RUNNING, timeout=1.0)

        await runner.trigger("start")
        await asyncio.sleep(0.1)
        assert await runner.wait_for_status("Sleepy", CommandStatus.RUNNING, timeout=2.0)

        history = runner.get_history("Sleepy")
        assert len(history) >= 1
        assert any(r.state == RunState.CANCELLED for r in history[:-1])