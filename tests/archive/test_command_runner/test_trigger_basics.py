# tests/test_command_runner/test_trigger_basics.py
import logging
from unittest.mock import patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus

logging.getLogger("cmdorc").setLevel(logging.DEBUG)


@pytest.mark.asyncio
async def test_success(mock_success_proc):
    cfg = CommandConfig(name="Echo", command="echo hello", triggers=["go"])
    runner = CommandRunner([cfg])

    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("go")
        live_runs = runner.get_live_runs("Echo")
        if live_runs:
            live_runs[0]._seen = None  # Force None to cover 'else' branch
        assert await runner.wait_for_status("Echo", CommandStatus.SUCCESS, timeout=1.0)


@pytest.mark.asyncio
async def test_failure(mock_failure_proc):
    cfg = CommandConfig(name="Fail", command="false", triggers=["go"])
    runner = CommandRunner([cfg])

    with patch("asyncio.create_subprocess_shell", return_value=mock_failure_proc):
        await runner.trigger("go")
        assert await runner.wait_for_status("Fail", CommandStatus.FAILED, timeout=1.0)


@pytest.mark.asyncio
async def test_auto_trigger_chaining(mock_success_proc):
    configs = [
        CommandConfig(name="A", command="echo a", triggers=["begin"]),
        CommandConfig(name="B", command="echo b", triggers=["command_success:A"]),
    ]
    runner = CommandRunner(configs)

    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("begin")
        assert await runner.wait_for_status("A", CommandStatus.SUCCESS, timeout=1.0)
        assert await runner.wait_for_status("B", CommandStatus.SUCCESS, timeout=1.0)
