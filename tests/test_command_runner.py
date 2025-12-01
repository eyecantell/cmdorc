# tests/test_command_runner.py
from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, patch

import pytest
import logging

from cmdorc.command_config import CommandConfig
from cmdorc.command_runner import CommandRunner, CommandStatus, RunState

logging.getLogger("cmdorc").setLevel(logging.DEBUG)

@pytest.fixture
def echo_config() -> List[CommandConfig]:
    return [
        CommandConfig(
            name="Echo",
            command="echo {{msg}}",
            triggers=["go"],
            timeout_secs=0.15,
            max_concurrent=1,
            on_retrigger="cancel_and_restart",
            keep_history=10,
        )
    ]


@pytest.fixture
async def runner(echo_config):
    r = CommandRunner(echo_config)
    r.set_vars({"msg": "hello"})
    yield r
    r.cancel_all()
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_nested_template_resolution():
    runner = CommandRunner([CommandConfig(name="T", command="cd {{dir}} && ls {{sub}}", triggers=["run"])])
    runner.set_vars({"base": "/home", "dir": "{{base}}/proj", "sub": "src"})
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("run")
        await asyncio.sleep(0.05)
    proc.communicate.assert_awaited_once()


@pytest.mark.asyncio
async def test_template_cycle_detection():
    runner = CommandRunner([CommandConfig(name="Boom", command="{{a}}", triggers=["boom"])])
    runner.set_vars({"a": "{{b}}", "b": "{{a}}"})
    await runner.trigger("boom")
    await asyncio.sleep(0.1)
    assert runner.get_status("Boom") == CommandStatus.FAILED


@pytest.mark.asyncio
async def test_success(runner: CommandRunner):
    proc = AsyncMock()
    proc.communicate.return_value = (b"hello\n", b"")
    proc.returncode = 0
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await asyncio.sleep(0.05)
        assert runner.get_status("Echo") == CommandStatus.SUCCESS


@pytest.mark.asyncio
async def test_failure(runner: CommandRunner):
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"boom")
    proc.returncode = 1
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await asyncio.sleep(0.05)
        assert runner.get_status("Echo") == CommandStatus.FAILED


@pytest.mark.asyncio
async def test_timeout(runner: CommandRunner):
    proc = AsyncMock()
    proc.returncode = None
    proc.wait.side_effect = asyncio.TimeoutError
    proc.communicate.side_effect = lambda: asyncio.sleep(999)

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await asyncio.sleep(0.5)
        assert runner.get_status("Echo") == CommandStatus.FAILED
        assert runner.get_result("Echo").error == "Timeout exceeded"

@pytest.mark.asyncio
async def test_cancel_and_restart_policy():
    cfg = CommandConfig(
        name="Sleepy",
        command="sleep 1",
        triggers=["start"],
        max_concurrent=1,
        on_retrigger="cancel_and_restart",
        keep_history=10,
    )
    runner = CommandRunner([cfg])

    await runner.trigger("start")
    assert await runner.wait_for_status("Sleepy", CommandStatus.RUNNING, timeout=2.0)

    await runner.trigger("start")  # cancels and restarts
    assert await runner.wait_for_status("Sleepy", CommandStatus.SUCCESS, timeout=2.0)

    history = runner.get_history("Sleepy")
    assert len(history) == 2
    assert history[0].state == RunState.CANCELLED
    assert history[1].state == RunState.SUCCESS

    runner.cancel_all()
    await asyncio.sleep(0.1)

@pytest.mark.asyncio
async def test_trigger_cycle_detection():
    cfg = CommandConfig(
        name="Loop",
        command="echo hello",
        triggers=["go", "command_success:Loop"],
    )
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.communicate.return_value = (b"hello\n", b"")
    proc.returncode = 0

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        with patch("logging.warning") as mock_warn:
            await runner.trigger("go")
            await asyncio.sleep(0.5)  # first run → success → self-trigger → cycle warning

            assert mock_warn.called
            assert "cycle" in mock_warn.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_auto_trigger_chaining():
    configs = [
        CommandConfig(name="A", command="echo a", triggers=["begin"]),
        CommandConfig(name="B", command="echo b", triggers=["command_success:A"]),
    ]
    runner = CommandRunner(configs)

    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("begin")
        await asyncio.sleep(0.3)
        assert runner.get_status("A") == CommandStatus.SUCCESS
        assert runner.get_status("B") == CommandStatus.SUCCESS


@pytest.mark.asyncio
async def test_history_retention():
    cfg = CommandConfig(name="H", command="echo x", triggers=["run"], keep_history=2)
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        for _ in range(5):
            await runner.trigger("run")
            await asyncio.sleep(0.02)
        assert len(runner.get_history("H")) == 2