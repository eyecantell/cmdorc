# tests/test_command_runner_phase2.py
"""
Phase 2 test coverage: Core missing features
- cancel_on_triggers behavior
- ignore retrigger policy
- Manual cancellation (cancel_command, cancel_all)
- max_concurrent variations (0, >1)
- Multiple commands per trigger
- External callbacks (on_trigger/off_trigger)
"""
from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, patch, Mock

import pytest
import logging

from cmdorc.command_config import CommandConfig
from cmdorc.command_runner import CommandRunner, CommandStatus, RunState

logging.getLogger("cmdorc").setLevel(logging.DEBUG)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_success_proc():
    """Mock process that succeeds immediately."""
    proc = AsyncMock()
    proc.communicate.return_value = (b"success\n", b"")
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=None)
    return proc


def create_long_running_proc():
    proc = AsyncMock()
    proc.returncode = None
    killed = asyncio.Event()

    async def communicate_impl():
        await killed.wait()
        proc.returncode = -9
        return (b"", b"")

    def kill_sync():
        proc.returncode = -9
        killed.set()

    proc.communicate = communicate_impl
    proc.kill = kill_sync          # ← THIS MUST BE A SYNC FUNCTION
    proc.terminate = kill_sync

    async def wait_impl():
        await killed.wait()
        return -9

    proc.wait = wait_impl

    return proc


# ============================================================================
# TEST: cancel_on_triggers
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_on_triggers_stops_running_command():
    """When a cancel_on_trigger fires, running command should be cancelled."""
    cfg = CommandConfig(
        name="Cancelable",
        command="sleep 100",
        triggers=["start", "stop"],  # Add "stop" to triggers
        cancel_on_triggers=["stop", "abort"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    
    proc = create_long_running_proc()
    
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        # Start the command
        await runner.trigger("start")
        assert await runner.wait_for_status("Cancelable", CommandStatus.RUNNING, timeout=1.0)
        
        # Give the subprocess mock time to actually start waiting
        await asyncio.sleep(0.1)
        
        # Fire cancel trigger
        await runner.trigger("stop")
        await asyncio.sleep(0.1)  # Yield to loop for cancellation to propagate
        
        # Should be cancelled - give it more time since subprocess needs to respond to kill
        assert await runner.wait_for_status("Cancelable", CommandStatus.CANCELLED, timeout=5.0)
        result = runner.get_result("Cancelable")
        assert result.state == RunState.CANCELLED


@pytest.mark.asyncio
async def test_cancel_on_triggers_multiple_triggers():
    """Any trigger in cancel_on_triggers list should work."""
    cfg = CommandConfig(
        name="Multi",
        command="sleep 100",
        triggers=["go", "stop2"],  # Add "stop2" to triggers
        cancel_on_triggers=["stop1", "stop2", "stop3"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    
    proc = create_long_running_proc()
    
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("go")
        assert await runner.wait_for_status("Multi", CommandStatus.RUNNING, timeout=1.0)
        
        # Give the subprocess mock time to actually start waiting
        await asyncio.sleep(0.1)
        
        # Try the second cancel trigger
        await runner.trigger("stop2")
        await asyncio.sleep(0.1)  # Yield to loop for cancellation to propagate
        
        assert await runner.wait_for_status("Multi", CommandStatus.CANCELLED, timeout=5.0)


@pytest.mark.asyncio
async def test_cancel_on_triggers_doesnt_restart(mock_success_proc):
    """cancel_on_triggers should ONLY cancel, not restart the command."""
    cfg = CommandConfig(
        name="NoRestart",
        command="echo test",
        triggers=["start", "stop"],  # Add "stop" to triggers
        cancel_on_triggers=["stop"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    
    proc = create_long_running_proc()
    
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_status("NoRestart", CommandStatus.RUNNING, timeout=1.0)
        
        # Give the subprocess mock time to actually start waiting
        await asyncio.sleep(0.1)
        
        await runner.trigger("stop")
        await asyncio.sleep(0.1)  # Yield to loop for cancellation to propagate
        
        # Should be cancelled, not restarted
        assert await runner.wait_for_status("NoRestart", CommandStatus.CANCELLED, timeout=5.0)
        assert runner.get_status("NoRestart") == CommandStatus.CANCELLED
        assert len(runner.get_live_runs("NoRestart")) == 0


# ============================================================================
# TEST: ignore retrigger policy
# ============================================================================

@pytest.mark.asyncio
async def test_ignore_retrigger_policy():
    """With on_retrigger='ignore', new triggers should be ignored while running."""
    cfg = CommandConfig(
        name="Ignorer",
        command="sleep 10",
        triggers=["run"],
        max_concurrent=1,
        on_retrigger="ignore",
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    
    proc = create_long_running_proc()
    
    with patch("asyncio.create_subprocess_shell", return_value=proc) as mock_create:
        # Start first run
        await runner.trigger("run")
        assert await runner.wait_for_running("Ignorer", timeout=1.0)
        first_run_id = runner.get_result("Ignorer").run_id
        
        # Try to trigger again - should be ignored
        await runner.trigger("run")
        await asyncio.sleep(0.1)
        
        # Should still have only one run with same run_id
        assert len(runner.get_live_runs("Ignorer")) == 1
        assert runner.get_result("Ignorer").run_id == first_run_id
        
        # Should have only called create_subprocess_shell once
        assert mock_create.call_count == 1
        
        # Cleanup
        runner.cancel_all()
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_ignore_allows_run_after_completion(mock_success_proc):
    """After command completes, ignore policy should allow new runs."""
    cfg = CommandConfig(
        name="IgnoreThenRun",
        command="echo done",
        triggers=["go"],
        max_concurrent=1,
        on_retrigger="ignore",
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        # First run
        await runner.trigger("go")
        assert await runner.wait_for_status("IgnoreThenRun", CommandStatus.SUCCESS, timeout=1.0)
        first_run_id = runner.get_result("IgnoreThenRun").run_id
        
        # Second run should work now
        await runner.trigger("go")
        assert await runner.wait_for_status("IgnoreThenRun", CommandStatus.SUCCESS, timeout=1.0)
        second_run_id = runner.get_result("IgnoreThenRun").run_id
        
        assert first_run_id != second_run_id
        assert len(runner.get_history("IgnoreThenRun")) == 2


# ============================================================================
# TEST: Manual cancellation
# ============================================================================

@pytest.mark.asyncio
async def test_cancel_command_single():
    """cancel_command() should cancel a specific running command."""
    cfg = CommandConfig(
        name="ToBeCancelled",
        command="sleep 100",
        triggers=["start"],
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    
    proc = create_long_running_proc()
    
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        assert await runner.wait_for_running("ToBeCancelled", timeout=1.0)
        
        # Cancel it
        runner.cancel_command("ToBeCancelled")
        
        assert await runner.wait_for_cancelled("ToBeCancelled", timeout=2.0)


@pytest.mark.asyncio
async def test_cancel_all_multiple_commands():
    """cancel_all() should cancel all running commands."""
    configs = [
        CommandConfig(name="Cmd1", command="sleep 100", triggers=["go1"], keep_history=5),
        CommandConfig(name="Cmd2", command="sleep 100", triggers=["go2"], keep_history=5),
        CommandConfig(name="Cmd3", command="sleep 100", triggers=["go3"], keep_history=5),
    ]
    runner = CommandRunner(configs)
    
    proc1 = create_long_running_proc()
    proc2 = create_long_running_proc()
    proc3 = create_long_running_proc()
    
    with patch("asyncio.create_subprocess_shell", side_effect=[proc1, proc2, proc3]):
        # Start all three
        await runner.trigger("go1")
        await runner.trigger("go2")
        await runner.trigger("go3")
        
        assert await runner.wait_for_running("Cmd1", timeout=1.0)
        assert await runner.wait_for_running("Cmd2", timeout=1.0)
        assert await runner.wait_for_running("Cmd3", timeout=1.0)
        
        # Cancel all
        runner.cancel_all()
        
        # All should be cancelled
        assert await runner.wait_for_cancelled("Cmd1", timeout=2.0)
        assert await runner.wait_for_cancelled("Cmd2", timeout=2.0)
        assert await runner.wait_for_cancelled("Cmd3", timeout=2.0)


@pytest.mark.asyncio
async def test_cancel_command_with_multiple_concurrent_runs():
    """cancel_command() should cancel all concurrent runs of that command."""
    cfg = CommandConfig(
        name="Parallel",
        command="sleep 100",
        triggers=["start"],
        max_concurrent=3,  # Allow 3 concurrent
        keep_history=10,
    )
    runner = CommandRunner([cfg])
    
    procs = [create_long_running_proc() for _ in range(3)]
    
    with patch("asyncio.create_subprocess_shell", side_effect=procs):
        # Start 3 concurrent runs
        await runner.trigger("start")
        await runner.trigger("start")
        await runner.trigger("start")
        await asyncio.sleep(0.1)
        
        assert len(runner.get_live_runs("Parallel")) == 3
        
        # Cancel all of them
        runner.cancel_command("Parallel")
        await asyncio.sleep(0.3)
        
        # All should be cancelled
        assert len(runner.get_live_runs("Parallel")) == 0
        history = runner.get_history("Parallel")
        assert len(history) == 3
        assert all(r.state == RunState.CANCELLED for r in history)


# ============================================================================
# TEST: max_concurrent variations
# ============================================================================

@pytest.mark.asyncio
async def test_max_concurrent_zero_unlimited(mock_success_proc):
    """max_concurrent=0 should allow unlimited parallel runs."""
    cfg = CommandConfig(
        name="Unlimited",
        command="echo test",
        triggers=["go"],
        max_concurrent=0,  # Unlimited
        keep_history=20,
    )
    runner = CommandRunner([cfg])
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        # Fire 10 triggers rapidly
        for _ in range(10):
            await runner.trigger("go")
        
        await asyncio.sleep(0.2)
        
        # Should have had 10 concurrent runs (now in history)
        history = runner.get_history("Unlimited")
        assert len(history) == 10
        assert all(r.state == RunState.SUCCESS for r in history)


@pytest.mark.asyncio
async def test_max_concurrent_three():
    """max_concurrent=3 should allow exactly 3 concurrent runs."""
    cfg = CommandConfig(
        name="Three",
        command="sleep 100",
        triggers=["run"],
        max_concurrent=3,
        on_retrigger="ignore",  # Don't restart, just ignore
        keep_history=10,
    )
    runner = CommandRunner([cfg])
    
    procs = [create_long_running_proc() for _ in range(5)]
    
    with patch("asyncio.create_subprocess_shell", side_effect=procs):
        # Try to start 5 runs
        for _ in range(5):
            await runner.trigger("run")
        
        await asyncio.sleep(0.2)
        
        # Should have exactly 3 live runs
        assert len(runner.get_live_runs("Three")) == 3
        
        # Clean up
        runner.cancel_all()
        await asyncio.sleep(0.3)


@pytest.mark.asyncio
async def test_max_concurrent_with_cancel_and_restart():
    """max_concurrent with cancel_and_restart should cancel all and start new."""
    cfg = CommandConfig(
        name="Restarter",
        command="sleep 100",
        triggers=["go"],
        max_concurrent=2,
        on_retrigger="cancel_and_restart",
        keep_history=10,
    )
    runner = CommandRunner([cfg])
    
    procs = [create_long_running_proc() for _ in range(3)]
    
    with patch("asyncio.create_subprocess_shell", side_effect=procs):
        # Start 2 runs (hits max)
        await runner.trigger("go")
        await runner.trigger("go")
        await asyncio.sleep(0.1)
        assert len(runner.get_live_runs("Restarter")) == 2
        
        # Third trigger should cancel all and start fresh
        await runner.trigger("go")
        await asyncio.sleep(0.3)
        
        # Should have 1 live run (the new one)
        live = runner.get_live_runs("Restarter")
        assert len(live) == 1
        
        # History should show 2 cancelled
        history = runner.get_history("Restarter")
        cancelled_count = sum(1 for r in history if r.state == RunState.CANCELLED)
        assert cancelled_count == 2
        
        # Clean up
        runner.cancel_all()
        await asyncio.sleep(0.2)


# ============================================================================
# TEST: Multiple commands per trigger
# ============================================================================

@pytest.mark.asyncio
async def test_multiple_commands_same_trigger(mock_success_proc):
    """Multiple commands can share the same trigger and all should run."""
    configs = [
        CommandConfig(name="First", command="echo 1", triggers=["shared"], keep_history=5),
        CommandConfig(name="Second", command="echo 2", triggers=["shared"], keep_history=5),
        CommandConfig(name="Third", command="echo 3", triggers=["shared"], keep_history=5),
    ]
    runner = CommandRunner(configs)
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("shared")
        
        # Use wait_for_status instead of random sleep
        assert await runner.wait_for_status("First", CommandStatus.SUCCESS, timeout=1.0)
        assert await runner.wait_for_status("Second", CommandStatus.SUCCESS, timeout=1.0)
        assert await runner.wait_for_status("Third", CommandStatus.SUCCESS, timeout=1.0)
        
        # All three should have run
        assert runner.get_status("First") == CommandStatus.SUCCESS
        assert runner.get_status("Second") == CommandStatus.SUCCESS
        assert runner.get_status("Third") == CommandStatus.SUCCESS


@pytest.mark.asyncio
async def test_get_commands_by_trigger(mock_success_proc):
    """get_commands_by_trigger() should return all commands for a trigger."""
    configs = [
        CommandConfig(name="A", command="echo a", triggers=["test", "other"]),
        CommandConfig(name="B", command="echo b", triggers=["test"]),
        CommandConfig(name="C", command="echo c", triggers=["different"]),
    ]
    runner = CommandRunner(configs)
    
    test_cmds = runner.get_commands_by_trigger("test")
    assert len(test_cmds) == 2
    assert {c.name for c in test_cmds} == {"A", "B"}
    
    other_cmds = runner.get_commands_by_trigger("other")
    assert len(other_cmds) == 1
    assert other_cmds[0].name == "A"
    
    assert runner.has_trigger("test") is True
    assert runner.has_trigger("nonexistent") is False


# ============================================================================
# TEST: External callbacks (on_trigger/off_trigger)
# ============================================================================

@pytest.mark.asyncio
async def test_on_trigger_callback_fires():
    """Callbacks registered with on_trigger should be called."""
    runner = CommandRunner([
        CommandConfig(name="Dummy", command="echo test", triggers=["other"])
    ])
    
    callback_data = {"count": 0}
    
    def my_callback(data):
        callback_data["count"] += 1
    
    runner.on_trigger("my_event", my_callback)
    
    await runner.trigger("my_event")
    await asyncio.sleep(0.05)
    
    assert callback_data["count"] == 1


@pytest.mark.asyncio
async def test_on_trigger_async_callback():
    """Async callbacks should work too."""
    runner = CommandRunner([
        CommandConfig(name="Dummy", command="echo test", triggers=["other"])
    ])
    
    callback_data = {"value": None}
    
    async def async_callback(data):
        await asyncio.sleep(0.01)
        callback_data["value"] = "async_done"
    
    runner.on_trigger("async_event", async_callback)
    
    await runner.trigger("async_event")
    await asyncio.sleep(0.1)
    
    assert callback_data["value"] == "async_done"


@pytest.mark.asyncio
async def test_off_trigger_removes_callback():
    """off_trigger should unregister callbacks."""
    runner = CommandRunner([
        CommandConfig(name="Dummy", command="echo test", triggers=["other"])
    ])
    
    callback_data = {"count": 0}
    
    def my_callback(data):
        callback_data["count"] += 1
    
    runner.on_trigger("test", my_callback)
    await runner.trigger("test")
    await asyncio.sleep(0.05)
    assert callback_data["count"] == 1
    
    # Unregister
    runner.off_trigger("test", my_callback)
    await runner.trigger("test")
    await asyncio.sleep(0.05)
    
    # Should still be 1
    assert callback_data["count"] == 1


@pytest.mark.asyncio
async def test_multiple_callbacks_same_trigger():
    """Multiple callbacks can be registered to the same trigger."""
    runner = CommandRunner([
        CommandConfig(name="Dummy", command="echo test", triggers=["other"])
    ])
    
    results = []
    
    def callback1(data):
        results.append("cb1")
    
    def callback2(data):
        results.append("cb2")
    
    def callback3(data):
        results.append("cb3")
    
    runner.on_trigger("multi", callback1)
    runner.on_trigger("multi", callback2)
    runner.on_trigger("multi", callback3)
    
    await runner.trigger("multi")
    await asyncio.sleep(0.05)
    
    assert len(results) == 3
    assert "cb1" in results
    assert "cb2" in results
    assert "cb3" in results


@pytest.mark.asyncio
async def test_callback_exception_doesnt_break_trigger(mock_success_proc, caplog):
    """If a callback raises an exception, other callbacks and commands should still run."""
    cfg = CommandConfig(name="Cmd", command="echo test", triggers=["test"], keep_history=5)
    runner = CommandRunner([cfg])
    
    results = []
    
    def bad_callback(data):
        raise ValueError("Intentional error")
    
    def good_callback(data):
        results.append("good")
    
    runner.on_trigger("test", bad_callback)
    runner.on_trigger("test", good_callback)
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("test")
        await asyncio.sleep(0.1)
        
        # Good callback should have run
        assert "good" in results
        
        # Command should have run
        assert runner.get_status("Cmd") == CommandStatus.SUCCESS
        
        # Should have logged the error
        assert "Trigger callback error" in caplog.text or "Intentional error" in caplog.text


# ============================================================================
# TEST: keep_history edge cases
# ============================================================================

@pytest.mark.asyncio
async def test_keep_history_zero(mock_success_proc):
    """keep_history=0 should not store any history."""
    cfg = CommandConfig(
        name="NoHistory",
        command="echo test",
        triggers=["run"],
        keep_history=0,
    )
    runner = CommandRunner([cfg])
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        # Run it a few times
        for _ in range(3):
            await runner.trigger("run")
            await asyncio.sleep(0.1)
        
        # Should have no history
        assert len(runner.get_history("NoHistory")) == 0
        
        # get_result() should return None after completion with no history
        result = runner.get_result("NoHistory")
        assert result is None


@pytest.mark.asyncio
async def test_keep_history_exact_retention(mock_success_proc):
    """History should be trimmed to exactly keep_history count."""
    cfg = CommandConfig(
        name="Limited",
        command="echo test",
        triggers=["run"],
        keep_history=3,
    )
    runner = CommandRunner([cfg])
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        # Run 10 times
        for i in range(10):
            await runner.trigger("run")
            await asyncio.sleep(0.05)
        
        await asyncio.sleep(0.2)  # Make sure all complete
        
        # Should have exactly 3 in history
        history = runner.get_history("Limited")
        assert len(history) == 3
        
        # They should be the LAST 3 runs
        assert all(r.state == RunState.SUCCESS for r in history)


# ============================================================================
# TEST: Duplicate history prevention
# ============================================================================

@pytest.mark.asyncio
async def test_no_duplicate_history_entries(mock_success_proc):
    """Ensure _task_completed doesn't add duplicates to history."""
    cfg = CommandConfig(
        name="NoDup",
        command="echo test",
        triggers=["go"],
        keep_history=10
    )
    runner = CommandRunner([cfg])
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("go")
        assert await runner.wait_for_status("NoDup", CommandStatus.SUCCESS, timeout=1.0)
        
        history = runner.get_history("NoDup")
        run_ids = [r.run_id for r in history]
        
        # Should have exactly 1 entry
        assert len(history) == 1, f"Expected 1 history entry, got {len(history)}"
        
        # All run_ids should be unique (no duplicates)
        assert len(run_ids) == len(set(run_ids)), f"Found duplicate run_ids in history: {run_ids}"


@pytest.mark.asyncio
async def test_multiple_commands_no_cross_contamination(mock_success_proc):
    """Multiple commands should not cause cross-contamination in history."""
    configs = [
        CommandConfig(name="A", command="echo a", triggers=["shared"], keep_history=5),
        CommandConfig(name="B", command="echo b", triggers=["shared"], keep_history=5),
        CommandConfig(name="C", command="echo c", triggers=["shared"], keep_history=5),
    ]
    runner = CommandRunner(configs)
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        # Trigger all at once
        await runner.trigger("shared")
        
        # Wait for all to complete
        assert await runner.wait_for_status("A", CommandStatus.SUCCESS, timeout=1.0)
        assert await runner.wait_for_status("B", CommandStatus.SUCCESS, timeout=1.0)
        assert await runner.wait_for_status("C", CommandStatus.SUCCESS, timeout=1.0)
        
        # Each should have exactly 1 entry with unique run_ids
        for name in ["A", "B", "C"]:
            history = runner.get_history(name)
            assert len(history) == 1, f"Command {name} should have 1 history entry, got {len(history)}"
            
            # Verify no duplicates within this command's history
            run_ids = [r.run_id for r in history]
            assert len(run_ids) == len(set(run_ids)), f"Command {name} has duplicate run_ids"
            
            # Verify the run_id matches the command name
            assert history[0].command_name == name


# ============================================================================
# TEST: Edge cases and error conditions
# ============================================================================

@pytest.mark.asyncio
async def test_trigger_nonexistent_trigger_does_nothing():
    """Triggering a non-registered trigger should not cause errors."""
    runner = CommandRunner([
        CommandConfig(name="Cmd", command="echo test", triggers=["real_trigger"])
    ])
    
    # Should not raise
    await runner.trigger("fake_trigger")
    await asyncio.sleep(0.05)
    
    # Command should not have run
    assert runner.get_status("Cmd") == CommandStatus.IDLE


@pytest.mark.asyncio
async def test_cancel_command_when_not_running():
    """Cancelling a command that's not running should not cause errors."""
    runner = CommandRunner([
        CommandConfig(name="Idle", command="echo test", triggers=["go"])
    ])
    
    # Should not raise
    runner.cancel_command("Idle")
    
    assert runner.get_status("Idle") == CommandStatus.IDLE


@pytest.mark.asyncio
async def test_get_result_with_invalid_run_id():
    """Getting a result with invalid run_id should raise ValueError."""
    runner = CommandRunner([
        CommandConfig(name="Cmd", command="echo test", triggers=["go"])
    ])
    
    with pytest.raises(ValueError, match="Run not found"):
        runner.get_result("Cmd", run_id="fake-uuid-12345")


@pytest.mark.asyncio
async def test_get_status_unknown_command():
    """Getting status of unknown command should raise ValueError."""
    runner = CommandRunner([
        CommandConfig(name="Known", command="echo test", triggers=["go"])
    ])
    
    with pytest.raises(ValueError, match="Unknown command"):
        runner.get_status("Unknown")

@pytest.mark.asyncio
async def test_get_status_with_run_id(mock_success_proc):
    cfg = CommandConfig(name="Test", command="echo ok", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])
    
    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        await runner.trigger("go")
        await runner.wait_for_status("Test", CommandStatus.SUCCESS, timeout=1.0)
        
        result = runner.get_result("Test")
        assert runner.get_status("Test", run_id=result.run_id) == CommandStatus.SUCCESS

@pytest.mark.asyncio
async def test_command_with_no_triggers(mock_success_proc):
    """A command with no triggers should be valid but never auto-run."""
    cfg = CommandConfig(
        name="NoTriggers",
        command="echo manual",
        triggers=[],  # Empty triggers list
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    
    # Trigger random events - command should not run
    await runner.trigger("random1")
    await runner.trigger("random2")
    await asyncio.sleep(0.1)
    
    assert runner.get_status("NoTriggers") == CommandStatus.IDLE