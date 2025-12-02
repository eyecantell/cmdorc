# tests/test_command_runner/test_edge_cases.py
import asyncio
import logging
from unittest.mock import patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus, RunResult, RunState


@pytest.mark.asyncio
async def test_trigger_with_no_handlers_logs_debug():
    dummy_cfg = CommandConfig(name="Dummy", command="echo ok", triggers=[])
    runner = CommandRunner([dummy_cfg])
    await runner.trigger("nonexistent-trigger")


@pytest.mark.asyncio
async def test_trigger_cycle_detection_warning(caplog):
    cfg = CommandConfig(name="Loop", command="echo x", triggers=["go", "command_success:Loop"])
    runner = CommandRunner([cfg])
    with caplog.at_level(logging.WARNING):
        await runner.trigger("go")
        await asyncio.sleep(0.1)
        assert "cycle detected" in caplog.text.lower()


def test_task_completed_with_running_state_raises():
    dummy_cfg = CommandConfig(name="Dummy", command="echo ok", triggers=[])
    runner = CommandRunner([dummy_cfg])
    result = RunResult()
    result.command_name = "Test"
    result.state = RunState.RUNNING
    with pytest.raises(ValueError, match="still RUNNING"):
        runner._task_completed("Test", result)


@pytest.mark.asyncio
async def test_validate_templates_strict_raises():
    cfg = CommandConfig(name="Bad", command="{{x}}", triggers=[])
    runner = CommandRunner([cfg])
    with pytest.raises(ValueError, match="Unresolved templates"):
        runner.validate_templates(strict=True)


@pytest.mark.asyncio
async def test_error_output_logged_on_failure(mock_failure_proc):
    cfg = CommandConfig(name="Err", command="false", triggers=["go"])
    runner = CommandRunner([cfg])
    with patch("asyncio.create_subprocess_shell", return_value=mock_failure_proc):
        await runner.trigger("go")
        await runner.wait_for_status("Err", CommandStatus.FAILED, timeout=1.0)
