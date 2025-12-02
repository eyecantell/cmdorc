# tests/test_command_runner/test_run_command.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus, RunState
import logging
logging.getLogger("cmdorc").setLevel(logging.DEBUG)

@pytest.mark.asyncio
async def test_run_command_basic_success(create_proc):
    cfg = CommandConfig(name="Echo", command="echo hello", triggers=["go"])
    runner = CommandRunner([cfg])

    proc = create_proc(stdout=b"hello\n", stderr=b"", returncode=0)

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        result = await runner.run_command("Echo")

    assert result.state == RunState.SUCCESS
    assert "hello" in result.output.strip()
    assert result.duration_secs is not None


@pytest.mark.asyncio
async def test_run_command_respects_concurrency_limit(create_proc):
    cfg = CommandConfig(
        name="Limited",
        command="sleep 5",
        triggers=["go"],
        max_concurrent=1,
        on_retrigger="cancel_and_restart",
        keep_history=10,  # safe
    )
    runner = CommandRunner([cfg])

    hanging = create_proc(delay=100.0)
    success = create_proc(stdout=b"ok\n", returncode=0)

    with patch("asyncio.create_subprocess_shell", side_effect=[hanging, success]):
        # First run starts and hangs
        first_task = asyncio.create_task(runner.run_command("Limited"))
        assert await runner.wait_for_running("Limited", timeout=1.0)

        # Second run cancels first and finishes
        result2 = await runner.run_command("Limited")

        assert result2.state == RunState.SUCCESS
        assert "ok" in result2.output
        assert result2.trigger_event == "run_command:Limited"

        assert await runner.wait_for_not_running("Limited", timeout=1.0)

        # Now history has both runs
        history = runner.get_history("Limited")
        states = [r.state for r in history]
        assert RunState.SUCCESS in states
        assert RunState.CANCELLED in states
        assert len(history) == 2

        # First task was cancelled
        with pytest.raises(asyncio.CancelledError):
            await first_task


@pytest.mark.asyncio
async def test_run_command_with_override_vars():
    cfg = CommandConfig(
        name="Templated",
        command="echo {{ greeting }} {{ name }}",
        triggers=["hi"],
    )
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.communicate.return_value = (b"Hello World\n", b"")
    proc.returncode = 0

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        result = await runner.run_command("Templated", greeting="Hola", name="amigo")

        # Check that override vars were used
        proc.communicate.assert_called_once()
        # The actual command passed to shell
        actual_cmd = proc.communicate.call_args[0][0]  # Not directly accessible, but we can check via side effect
        # Instead: verify output contains resolved values
        assert "Hola amigo" in result.output.strip()


@pytest.mark.asyncio
async def test_run_command_preserves_original_vars_after_override():
    cfg = CommandConfig(name="Test", command="echo {{ x }}", triggers=[])
    runner = CommandRunner([cfg])
    runner.set_vars({"x": "original"})

    mock_proc = AsyncMock(communicate=AsyncMock(return_value=(b"temp\n", b"")), returncode=0)

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        await runner.run_command("Test", x="temp")

    # Original var should be restored
    resolved = runner._resolve_template("{{ x }}")
    assert resolved == "original"


@pytest.mark.asyncio
async def test_run_command_triggers_auto_events_and_chains(create_proc):
    configs = [
        CommandConfig(name="A", command="echo a", triggers=[]),  # no explicit trigger
        CommandConfig(name="B", command="echo b", triggers=["command_success:A"]),
    ]
    runner = CommandRunner(configs)

    with patch("asyncio.create_subprocess_shell", return_value=create_proc):
        await runner.run_command("A")

        # B should be auto-triggered
        assert await runner.wait_for_status("B", CommandStatus.SUCCESS, timeout=1.0)
        assert runner.get_result("B").state == RunState.SUCCESS


@pytest.mark.asyncio
async def test_run_command_async_fire_and_forget():
    cfg = CommandConfig(name="Fire", command="echo fire", triggers=[])
    runner = CommandRunner([cfg])

    mock_proc = AsyncMock(communicate=AsyncMock(return_value=(b"fire\n", b"")), returncode=0)

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        runner.run_command_async("Fire")

        # Give it a moment
        assert await runner.wait_for_status("Fire", CommandStatus.SUCCESS, timeout=1.0)
        result = runner.get_result("Fire")
        assert result.state == RunState.SUCCESS
        assert "fire" in result.output


@pytest.mark.asyncio
async def test_run_command_raises_if_command_not_found(sample_command_config):
    runner = sample_command_config

    with pytest.raises(ValueError, match="Command 'Unknown' not found"):
        await runner.run_command("Unknown")


@pytest.mark.asyncio
async def test_run_command_emits_command_started_and_finished(create_proc):
    started_called = 0
    finished_called = 0

    def on_started(_):
        nonlocal started_called
        started_called += 1

    def on_finished(_):
        nonlocal finished_called
        finished_called += 1

    cfg = CommandConfig(name="Events", command="echo ok", triggers=[])
    runner = CommandRunner([cfg])
    runner.on_trigger("command_started:Events", on_started)
    runner.on_trigger("command_finished:Events", on_finished)

    with patch("asyncio.create_subprocess_shell", return_value=create_proc):
        await runner.run_command("Events")

    assert started_called == 1
    assert finished_called == 1


@pytest.mark.asyncio
async def test_run_command_cycle_detection_still_works():
    cfg = CommandConfig(name="Boom", command="echo boom", triggers=["command_success:Boom"])
    runner = CommandRunner([cfg])

    mock_proc = AsyncMock(communicate=AsyncMock(return_value=(b"boom\n", b"")), returncode=0)

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        await runner.run_command("Boom")

        # Should detect cycle and not infinitely loop
        await asyncio.sleep(0.2)
        history = runner.get_history("Boom")
        # Only one run (the original), no infinite spawning
        assert len([r for r in history if r.state == RunState.SUCCESS]) == 1


@pytest.mark.asyncio
async def test_run_command_cancel_on_triggers_still_works():
    cfg = CommandConfig(
        name="Long",
        command="sleep 10",
        triggers=[],
        cancel_on_triggers=["stop"],
    )
    runner = CommandRunner([cfg])

    long_proc = AsyncMock()
    long_proc.communicate = AsyncMock(side_effect=asyncio.sleep(10))

    with patch("asyncio.create_subprocess_shell", return_value=long_proc):
        task = asyncio.create_task(runner.run_command("Long"))
        assert await runner.wait_for_running("Long", timeout=1.0)

        await runner.trigger("stop")

        # Should be cancelled
        result = await task
        assert result.state == RunState.CANCELLED