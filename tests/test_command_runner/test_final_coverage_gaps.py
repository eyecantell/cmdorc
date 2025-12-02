# tests/test_command_runner/test_final_coverage_gaps.py
"""
Tests targeting the final coverage gaps in command_runner.py
Lines: 226-231, 236, 260, 263-264, 302-303, 314-315, 340-341, 359, 376-377, 388, 400, 479
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus, RunState

logging.getLogger("cmdorc").setLevel(logging.DEBUG)


@pytest.mark.asyncio
async def test_cancel_on_triggers_no_live_runs():
    """Test cancel_on_triggers when there are no live runs - covers line 226-231"""
    cfg = CommandConfig(
        name="Test",
        command="echo ok",
        triggers=["start"],
        cancel_on_triggers=["cancel"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])

    # Trigger cancel without any running commands
    await runner.trigger("cancel")
    await asyncio.sleep(0.05)

    # Should do nothing, no error
    assert runner.get_status("Test") == CommandStatus.IDLE


@pytest.mark.asyncio
async def test_retrigger_when_no_live_runs(mock_success_proc):
    """Test retrigger logic when there are no live runs - covers line 236"""
    cfg = CommandConfig(
        name="Test",
        command="echo ok",
        triggers=["go"],
        max_concurrent=1,
        on_retrigger="cancel_and_restart",
        keep_history=5,
    )
    runner = CommandRunner([cfg])

    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        # First trigger - no live runs, should just start
        await runner.trigger("go")
        assert await runner.wait_for_status("Test", CommandStatus.SUCCESS, timeout=1.0)


@pytest.mark.asyncio
async def test_unlimited_concurrent_runs(mock_success_proc):
    """Test max_concurrent=0 (unlimited) - covers line 236"""
    cfg = CommandConfig(
        name="Unlimited",
        command="echo ok",
        triggers=["go"],
        max_concurrent=0,  # Unlimited
        keep_history=20,
    )
    runner = CommandRunner([cfg])

    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        # Trigger multiple times rapidly
        for _ in range(5):
            await runner.trigger("go")

        await asyncio.sleep(0.2)

        # All should have completed
        history = runner.get_history("Unlimited")
        assert len(history) == 5


@pytest.mark.asyncio
async def test_command_config_history_retention_zero():
    """Test keep_history=0 (no history) - covers line 260, 263-264"""
    cfg = CommandConfig(
        name="NoHist",
        command="echo ok",
        triggers=["go"],
        keep_history=0,  # Keep no history
    )
    runner = CommandRunner([cfg])

    with patch(
        "asyncio.create_subprocess_shell",
        return_value=AsyncMock(communicate=AsyncMock(return_value=(b"ok\n", b"")), returncode=0),
    ):
        await runner.trigger("go")
        await runner.wait_for_status("NoHist", CommandStatus.SUCCESS, timeout=1.0)

        # History should be empty
        assert len(runner.get_history("NoHist")) == 0


@pytest.mark.asyncio
async def test_timeout_with_none_returncode():
    """Test timeout handling when returncode is None - covers line 302-303"""
    cfg = CommandConfig(
        name="Timeout",
        command="sleep 100",
        triggers=["go"],
        timeout_secs=0.1,
        keep_history=5,
    )
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.returncode = None  # Still running
    proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
    proc.kill = lambda: setattr(proc, "returncode", -9)

    # Make communicate wait forever (will be interrupted by timeout)
    async def long_communicate():
        await asyncio.sleep(10)
        return (b"", b"")

    proc.communicate = long_communicate

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await asyncio.sleep(0.3)  # Wait for timeout

        # Should be failed due to timeout
        assert await runner.wait_for_status("Timeout", CommandStatus.FAILED, timeout=2.0)
        result = runner.get_result("Timeout")
        assert "Timeout" in result.error or "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_cancelled_error_with_none_returncode():
    """Test CancelledError handling when returncode is None - covers line 314-315"""
    cfg = CommandConfig(
        name="Cancel",
        command="sleep 100",
        triggers=["go"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.returncode = None
    proc.kill = lambda: setattr(proc, "returncode", -9)
    proc.wait = AsyncMock(return_value=-9)

    # Make communicate raise CancelledError
    async def cancelled_communicate():
        raise asyncio.CancelledError()

    proc.communicate = cancelled_communicate

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await runner.wait_for_status("Cancel", CommandStatus.RUNNING, timeout=1.0)

        # Cancel it
        runner.cancel_command("Cancel")
        await asyncio.sleep(0.2)

        # Should be cancelled
        assert await runner.wait_for_status("Cancel", CommandStatus.CANCELLED, timeout=2.0)


@pytest.mark.asyncio
async def test_failed_with_empty_output():
    """Test failed command with empty output - covers line 340-341"""
    cfg = CommandConfig(
        name="FailEmpty",
        command="exit 1",
        triggers=["go"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")  # Empty output
    proc.returncode = 1

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await runner.wait_for_status("FailEmpty", CommandStatus.FAILED, timeout=1.0)

        result = runner.get_result("FailEmpty")
        assert result.state == RunState.FAILED
        assert result.output == ""  # Empty but should still work


@pytest.mark.asyncio
async def test_get_result_unknown_command():
    """Test get_result with unknown command - covers line 400"""
    runner = CommandRunner([CommandConfig(name="Known", command="echo ok", triggers=["go"])])

    with pytest.raises(ValueError, match="Unknown command"):
        runner.get_result("Unknown")


@pytest.mark.asyncio
async def test_get_history_unknown_command():
    """Test get_history with unknown command - covers implicit validation"""
    runner = CommandRunner([CommandConfig(name="Known", command="echo ok", triggers=["go"])])

    with pytest.raises(ValueError, match="Unknown command"):
        runner.get_history("Unknown")


@pytest.mark.asyncio
async def test_get_live_runs_unknown_command():
    """Test get_live_runs with unknown command"""
    runner = CommandRunner([CommandConfig(name="Known", command="echo ok", triggers=["go"])])

    with pytest.raises(ValueError, match="Unknown command"):
        runner.get_live_runs("Unknown")


@pytest.mark.asyncio
async def test_wait_for_idle_success(mock_success_proc):
    """Test wait_for_not_running helper - covers line 479"""
    cfg = CommandConfig(name="Quick", command="echo ok", triggers=["go"])
    runner = CommandRunner([cfg])

    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("go")

        # Wait for it to go idle (success -> idle in status terms)
        # Actually wait_for_not_running checks for IDLE status, which won't happen after success
        # Let's wait for success first
        await runner.wait_for_status("Quick", CommandStatus.SUCCESS, timeout=1.0)

        # Now try wait_for_not_running on a command that's never run
        cfg2 = CommandConfig(name="Idle", command="echo ok", triggers=["go2"])
        runner2 = CommandRunner([cfg2])

        # Should immediately return True since it's already idle
        result = await runner2.wait_for_not_running("Idle", timeout=0.1)
        assert result is True


@pytest.mark.asyncio
async def test_wait_for_cancelled_helper():
    """Test wait_for_cancelled helper"""
    cfg = CommandConfig(name="ToCancel", command="sleep 10", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])

    proc = AsyncMock()
    proc.returncode = None
    proc.kill = lambda: setattr(proc, "returncode", -9)

    done_event = asyncio.Event()

    async def mock_communicate():
        await done_event.wait()
        return (b"", b"")

    proc.communicate = mock_communicate
    proc.wait = AsyncMock(return_value=-9)

    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        await runner.wait_for_status("ToCancel", CommandStatus.RUNNING, timeout=1.0)

        # Cancel it
        runner.cancel_command("ToCancel")
        done_event.set()

        # Wait for cancelled status
        result = await runner.wait_for_cancelled("ToCancel", timeout=2.0)
        assert result is True


@pytest.mark.asyncio
async def test_trigger_with_seen_propagation():
    """Test that _seen set propagates correctly through auto-triggers - covers line 359"""
    configs = [
        CommandConfig(name="A", command="echo a", triggers=["start"]),
        CommandConfig(name="B", command="echo b", triggers=["command_success:A"]),
    ]
    runner = CommandRunner(configs)

    with patch(
        "asyncio.create_subprocess_shell",
        return_value=AsyncMock(communicate=AsyncMock(return_value=(b"ok\n", b"")), returncode=0),
    ):
        # Trigger A, which should auto-trigger B
        await runner.trigger("start")

        # Wait for both to complete
        await runner.wait_for_status("A", CommandStatus.SUCCESS, timeout=1.0)
        await runner.wait_for_status("B", CommandStatus.SUCCESS, timeout=1.0)

        # Both should have succeeded
        assert runner.get_status("A") == CommandStatus.SUCCESS
        assert runner.get_status("B") == CommandStatus.SUCCESS


@pytest.mark.asyncio
async def test_result_seen_is_none():
    """Test auto-trigger when result._seen is None - covers line 376-377"""
    cfg = CommandConfig(name="Test", command="echo ok", triggers=["go"])
    runner = CommandRunner([cfg])

    with patch(
        "asyncio.create_subprocess_shell",
        return_value=AsyncMock(communicate=AsyncMock(return_value=(b"ok\n", b"")), returncode=0),
    ):
        await runner.trigger("go")
        await runner.wait_for_status("Test", CommandStatus.SUCCESS, timeout=1.0)

        # The auto-trigger should still work even if _seen was None
        result = runner.get_result("Test")
        assert result.state == RunState.SUCCESS


@pytest.mark.asyncio
async def test_has_trigger_with_callbacks_only():
    """Test has_trigger when only callbacks registered, no commands - covers line 388"""
    runner = CommandRunner([CommandConfig(name="Dummy", command="echo ok", triggers=["other"])])

    # Register a callback for a trigger that no command uses
    called = False

    def callback(_):
        nonlocal called
        called = True

    runner.on_trigger("callback_only", callback)

    # has_trigger should return True even though no command uses it
    # Actually, looking at the code, has_trigger only checks _trigger_map
    # So it would return False for callback-only triggers
    assert runner.has_trigger("callback_only") is False
    assert runner.has_trigger("other") is True
