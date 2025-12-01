# tests/test_command_runner/test_cancellation.py
import pytest
import asyncio
from unittest.mock import patch
from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus, RunState


@pytest.mark.asyncio
async def test_cancel_on_triggers_stops_running_command(create_long_running_proc):
    cfg = CommandConfig(
        name="Cancelable",
        command="sleep 100",
        triggers=["start"],
        cancel_on_triggers=["stop", "abort"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    proc = create_long_running_proc()

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_status("Cancelable", CommandStatus.RUNNING, timeout=1.0)
        await asyncio.sleep(0.1)

        await runner.trigger("stop")
        await asyncio.sleep(0.1)

        assert await runner.wait_for_status("Cancelable", CommandStatus.CANCELLED, timeout=2.0)
        result = runner.get_result("Cancelable")
        assert result.state == RunState.CANCELLED


@pytest.mark.asyncio
async def test_cancel_on_triggers_multiple_triggers(create_long_running_proc):
    cfg = CommandConfig(
        name="Multi",
        command="sleep 100",
        triggers=["go"],
        cancel_on_triggers=["stop1", "stop2", "stop3"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    proc = create_long_running_proc()

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        assert await runner.wait_for_status("Multi", CommandStatus.RUNNING, timeout=1.0)
        await asyncio.sleep(0.1)

        await runner.trigger("stop2")
        await asyncio.sleep(0.1)

        assert await runner.wait_for_status("Multi", CommandStatus.CANCELLED, timeout=2.0)


@pytest.mark.asyncio
async def test_cancel_on_triggers_doesnt_restart(create_long_running_proc):
    cfg = CommandConfig(
        name="NoRestart",
        command="sleep 100",
        triggers=["start"],
        cancel_on_triggers=["stop"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    proc = create_long_running_proc()

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_status("NoRestart", CommandStatus.RUNNING, timeout=1.0)
        await asyncio.sleep(0.1)

        await runner.trigger("stop")
        await asyncio.sleep(0.1)

        assert await runner.wait_for_status("NoRestart", CommandStatus.CANCELLED, timeout=2.0)
        assert runner.get_status("NoRestart") == CommandStatus.CANCELLED
        assert len(runner.get_live_runs("NoRestart")) == 0