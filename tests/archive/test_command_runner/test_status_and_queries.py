# tests/test_command_runner/test_status_and_queries.py
from unittest.mock import patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus


@pytest.mark.asyncio
async def test_get_status_with_run_id(mock_success_proc):
    cfg = CommandConfig(name="Test", command="echo ok", triggers=["go"])
    runner = CommandRunner([cfg])

    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("go")
        await runner.wait_for_status("Test", CommandStatus.SUCCESS, timeout=1.0)

        result = runner.get_result("Test")
        assert runner.get_status("Test", run_id=result.run_id) == CommandStatus.SUCCESS


@pytest.mark.asyncio
async def test_get_result_with_bad_run_id_raises():
    dummy_cfg = CommandConfig(name="Dummy", command="echo ok", triggers=[])
    runner = CommandRunner([dummy_cfg])
    with pytest.raises(ValueError, match="Run not found"):
        runner.get_result("Dummy", "fake-id")


@pytest.mark.asyncio
async def test_wait_for_helpers(create_long_running_proc):
    cfg = CommandConfig(name="Wait", command="sleep 3", triggers=["start"])
    runner = CommandRunner([cfg])
    # create_long_running_proc is already the proc object (injected by pytest)
    proc = create_long_running_proc

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_running("Wait", timeout=1.0)

        # Test error case
        with pytest.raises(ValueError, match="Unknown command: NonExistent"):
            await runner.wait_for_not_running("NonExistent", timeout=0.1)


def test_get_status_with_bad_run_id_raises():
    cfg = CommandConfig(name="Test", command="echo ok", triggers=[])
    runner = CommandRunner([cfg])
    with pytest.raises(ValueError, match="Run not found"):
        runner.get_status("Test", "fake-id")
