# tests/test_command_runner.py
import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
from cmdorc.command_config import CommandConfig  # ← ADD THIS
from cmdorc.command_runner import CommandRunner, RunResult



@pytest.mark.asyncio
async def test_command_runner_init(sample_runner):
    assert len(sample_runner._command_configs) == 1
    assert sample_runner.vars["message"] == "hello"
    assert "test_trigger" in sample_runner._trigger_map
    assert sample_runner.get_status("TestCmd") == "idle"

@pytest.mark.asyncio
async def test_trigger_and_execute(sample_runner):
    with patch("asyncio.create_subprocess_shell", new=AsyncMock()) as mock_shell:
        mock_proc = mock_shell.return_value
        mock_proc.communicate.return_value = (b"hello world\n", b"")
        mock_proc.returncode = 0

        await sample_runner.trigger("test_trigger")

        # Give the task a tiny moment to finish
        await asyncio.sleep(0.01)

        assert sample_runner.get_status("TestCmd") == "success"
        result = sample_runner.get_result("TestCmd")
        assert result.success
        assert "hello world" in result.output


@pytest.mark.asyncio
async def test_cancel(sample_runner):
    with patch("asyncio.create_subprocess_shell", new=AsyncMock()) as mock_shell:
        mock_proc = mock_shell.return_value
        mock_proc.communicate.side_effect = asyncio.sleep(10)  # never finishes

        await sample_runner.trigger("test_trigger")
        await asyncio.sleep(0.01)  # let task start
        sample_runner.cancel_command("TestCmd")
        await asyncio.sleep(0.01)

        assert sample_runner.get_status("TestCmd") == "cancelled"


@pytest.mark.asyncio
async def test_auto_trigger_chaining():
    config1 = CommandConfig(name="Step1", command="echo 1", triggers=["start"])
    config2 = CommandConfig(name="Step2", command="echo 2", triggers=["command_success:Step1"])
    runner = CommandRunner([config1, config2])

    with patch("asyncio.create_subprocess_shell") as mock_shell:
        mock_proc = mock_shell.return_value
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0

        await runner.trigger("start")
        await asyncio.sleep(0.02)  # let chain complete

        assert runner.get_status("Step2") == "success"


@pytest.mark.asyncio
async def test_cycle_detection():
    cmd = CommandConfig(
        name="Cycle",
        command="echo cycle",
        triggers=["cycle", "command_success:Cycle"],  # self-trigger
    )
    runner = CommandRunner([cmd])

    with patch("logging.warning") as mock_warn:
        await runner.trigger("cycle")
        await asyncio.sleep(0.01)
        await runner.trigger("cycle")  # second call triggers cycle guard
        # Give the task a tiny moment to finish
        await asyncio.sleep(0.01)

        assert mock_warn.called




@pytest.mark.asyncio
async def test_callback_on_trigger(sample_runner):
    callback_called = False
    def cb(payload):
        nonlocal callback_called
        callback_called = True
    
    sample_runner.on_trigger("test_trigger", cb)
    # Give the task a tiny moment to finish
    await asyncio.sleep(0.01)
    
    await sample_runner.trigger("test_trigger")
    # Give the task a tiny moment to finish
    await asyncio.sleep(0.01)
    
    assert callback_called
