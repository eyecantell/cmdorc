# tests/test_command_runner/test_error_handling.py
"""
Test error handling and exception paths in command_runner.py
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus, RunState


@pytest.mark.asyncio
async def test_subprocess_exception_handling():
    """Test handling of subprocess creation failures - covers line 320"""
    cfg = CommandConfig(name="Fail", command="invalid", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])

    # Make subprocess creation raise an exception
    with patch("asyncio.create_subprocess_shell", side_effect=RuntimeError("Subprocess failed")):
        await runner.trigger("go")
        await runner.wait_for_status("Fail", CommandStatus.FAILED, timeout=1.0)

        result = runner.get_result("Fail")
        assert result.state == RunState.FAILED
        assert "Subprocess failed" in result.error


@pytest.mark.asyncio
async def test_communicate_exception_during_cancellation():
    """Test handling of exceptions during process cleanup - covers lines 311-315"""
    cfg = CommandConfig(name="Test", command="sleep 10", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.returncode = None

    # Make wait() raise an exception
    proc.wait = AsyncMock(side_effect=RuntimeError("Wait failed"))
    proc.kill = lambda: None

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await runner.wait_for_status("Test", CommandStatus.RUNNING, timeout=1.0)

        # Cancel should handle the exception gracefully
        runner.cancel_command("Test")
        await asyncio.sleep(0.2)

        # Should still be marked as cancelled
        assert runner.get_status("Test") == CommandStatus.CANCELLED


@pytest.mark.asyncio
async def test_error_output_without_strip():
    """Test error output handling when output is empty - covers line 341"""
    cfg = CommandConfig(name="Test", command="false", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])

    # Process that fails but has no output
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")  # Empty output
    proc.returncode = 1

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await runner.wait_for_status("Test", CommandStatus.FAILED, timeout=1.0)

        # Should handle empty output gracefully
        result = runner.get_result("Test")
        assert result.state == RunState.FAILED


@pytest.mark.asyncio
async def test_get_status_with_invalid_run_id():
    """Test get_status with run_id that doesn't exist - covers line 396"""
    cfg = CommandConfig(name="Test", command="echo ok", triggers=["go"])
    runner = CommandRunner([cfg])

    with pytest.raises(ValueError, match="Run not found"):
        runner.get_status("Test", run_id="nonexistent-id")


@pytest.mark.asyncio
async def test_template_recursion_depth_exceeded():
    """Test template resolution with deep nesting - covers RecursionError in _resolve_template"""
    cfg = CommandConfig(name="Test", command="{{a}}", triggers=["go"])
    runner = CommandRunner([cfg])

    # Create a chain longer than max_depth
    for i in range(15):
        runner.add_var(f"v{i}", f"{{{{v{i + 1}}}}}")
    runner.add_var("v15", "final")

    with pytest.raises(RecursionError, match="max template nesting depth"):
        runner._resolve_template("{{v0}}")


@pytest.mark.asyncio
async def test_empty_trigger_list_no_error():
    """Test that commands with empty triggers work correctly"""
    cfg = CommandConfig(name="NoTriggers", command="echo test", triggers=[])
    runner = CommandRunner([cfg])

    # Should initialize without error
    assert "NoTriggers" in runner._command_configs

    # Triggering random events should not run it
    await runner.trigger("random")
    assert runner.get_status("NoTriggers") == CommandStatus.IDLE


@pytest.mark.asyncio
async def test_cancel_all_with_no_running_commands():
    """Test cancel_all when nothing is running"""
    cfg = CommandConfig(name="Idle", command="echo test", triggers=["go"])
    runner = CommandRunner([cfg])

    # Should not raise an error
    runner.cancel_all()
    assert runner.get_status("Idle") == CommandStatus.IDLE


@pytest.mark.asyncio
async def test_multiple_cancel_calls_safe():
    """Test that calling cancel multiple times is safe"""
    cfg = CommandConfig(name="Test", command="sleep 10", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.returncode = None
    proc.wait = AsyncMock(return_value=-9)
    proc.kill = lambda: setattr(proc, "returncode", -9)

    done_event = asyncio.Event()

    async def mock_communicate():
        await done_event.wait()
        return (b"", b"")

    proc.communicate = mock_communicate

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await runner.wait_for_status("Test", CommandStatus.RUNNING, timeout=1.0)

        # Cancel multiple times
        runner.cancel_command("Test")
        runner.cancel_command("Test")
        runner.cancel_command("Test")

        done_event.set()
        await asyncio.sleep(0.2)

        # Should handle gracefully
        assert runner.get_status("Test") == CommandStatus.CANCELLED


@pytest.mark.asyncio
async def test_trigger_with_both_commands_and_callbacks():
    """Test trigger that fires both commands and callbacks - covers line 226"""
    cfg = CommandConfig(name="Cmd", command="echo test", triggers=["shared"])
    runner = CommandRunner([cfg])

    callback_called = asyncio.Event()

    def callback(_):
        callback_called.set()

    runner.on_trigger("shared", callback)

    with patch(
        "asyncio.create_subprocess_shell",
        return_value=AsyncMock(communicate=AsyncMock(return_value=(b"ok\n", b"")), returncode=0),
    ):
        await runner.trigger("shared")

        # Both should execute
        await runner.wait_for_status("Cmd", CommandStatus.SUCCESS, timeout=1.0)
        await asyncio.wait_for(callback_called.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_history_trimming_edge_case():
    """Test history trimming when keep_history is exactly reached"""
    cfg = CommandConfig(
        name="Trim",
        command="echo test",
        triggers=["go"],
        keep_history=3,  # Keep exactly 3
    )
    runner = CommandRunner([cfg])

    with patch(
        "asyncio.create_subprocess_shell",
        return_value=AsyncMock(communicate=AsyncMock(return_value=(b"ok\n", b"")), returncode=0),
    ):
        # Run exactly 3 times
        for _ in range(3):
            await runner.trigger("go")
            await runner.wait_for_status("Trim", CommandStatus.SUCCESS, timeout=1.0)

        # Should have exactly 3
        assert len(runner.get_history("Trim")) == 3

        # Run one more time
        await runner.trigger("go")
        await runner.wait_for_status("Trim", CommandStatus.SUCCESS, timeout=1.0)

        # Should still have exactly 3 (oldest removed)
        assert len(runner.get_history("Trim")) == 3
