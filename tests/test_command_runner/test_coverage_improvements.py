# tests/test_command_runner/test_coverage_improvements.py
"""
Additional tests to improve coverage of command_runner.py
Targets uncovered lines and edge cases.
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from cmdorc.command_runner import (
    CommandRunner, CommandConfig, CommandStatus, 
    RunState, RunResult
)


@pytest.mark.asyncio
async def test_timeout_exceeds(create_long_running_proc):
    """Test timeout_secs enforcement - covers lines 296-304"""
    cfg = CommandConfig(
        name="Timeout",
        command="sleep 100",
        triggers=["start"],
        timeout_secs=1,  # 1 second timeout
        keep_history=5,
    )
    runner = CommandRunner([cfg])
    proc = create_long_running_proc
    
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("start")
        await runner.wait_for_status("Timeout", CommandStatus.RUNNING, timeout=1.0)
        
        # Wait for timeout to trigger
        await asyncio.sleep(1.5)
        
        # Should be marked as failed due to timeout
        assert await runner.wait_for_status("Timeout", CommandStatus.FAILED, timeout=2.0)
        result = runner.get_result("Timeout")
        assert result.state == RunState.FAILED
        assert "Timeout" in result.error or "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_duration_str_formats():
    """Test RunResult.duration_str formatting - covers lines 62-64, 69-81"""
    result = RunResult()
    result.command_name = "Test"
    
    # No times set
    assert result.duration_str == "–"
    
    # Less than 60 seconds
    result.mark_running()
    await asyncio.sleep(0.1)
    result.mark_success()
    assert "s" in result.duration_str
    assert float(result.duration_str.replace("s", "")) < 1.0
    
    # Simulate longer durations by manually setting times
    import datetime
    
    # Test ~2.5 seconds
    result2 = RunResult()
    result2.command_name = "Test2"
    result2.start_time = datetime.datetime.now()
    result2.end_time = result2.start_time + datetime.timedelta(seconds=2.5)
    result2.state = RunState.SUCCESS
    assert result2.duration_str == "2.5s"
    
    # Test 1 minute 23 seconds
    result3 = RunResult()
    result3.command_name = "Test3"
    result3.start_time = datetime.datetime.now()
    result3.end_time = result3.start_time + datetime.timedelta(seconds=83)
    result3.state = RunState.SUCCESS
    assert "1m" in result3.duration_str
    
    # Test 1 hour 5 minutes
    result4 = RunResult()
    result4.command_name = "Test4"
    result4.start_time = datetime.datetime.now()
    result4.end_time = result4.start_time + datetime.timedelta(hours=1, minutes=5)
    result4.state = RunState.SUCCESS
    assert "1h" in result4.duration_str and "5m" in result4.duration_str


@pytest.mark.asyncio
async def test_get_result_returns_none_when_never_run():
    """Test get_result with no history - covers line 420"""
    cfg = CommandConfig(name="Never", command="echo test", triggers=["go"])
    runner = CommandRunner([cfg])
    
    # Never triggered, should return None
    result = runner.get_result("Never")
    assert result is None


@pytest.mark.asyncio
async def test_get_result_returns_live_run_first(mock_success_proc):
    """Test get_result prioritizes live runs over history - covers lines 414-420"""
    cfg = CommandConfig(name="Live", command="sleep 1", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])
    
    proc = AsyncMock()
    proc.returncode = None
    proc.communicate = AsyncMock(side_effect=asyncio.sleep(10))  # Long running
    
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        # Start a long-running command
        await runner.trigger("go")
        await runner.wait_for_status("Live", CommandStatus.RUNNING, timeout=1.0)
        
        # get_result should return the live run
        result = runner.get_result("Live")
        assert result is not None
        assert result.state == RunState.RUNNING
        
        # Cleanup
        runner.cancel_command("Live")


@pytest.mark.asyncio
async def test_get_history_and_live_runs():
    """Test get_history and get_live_runs - covers lines 424, 427"""
    cfg = CommandConfig(name="Multi", command="echo test", triggers=["go"], keep_history=5)
    runner = CommandRunner([cfg])
    
    # Initially empty
    assert runner.get_history("Multi") == []
    assert runner.get_live_runs("Multi") == []
    
    with patch("asyncio.create_subprocess_shell", return_value=AsyncMock(
        communicate=AsyncMock(return_value=(b"ok\n", b"")),
        returncode=0
    )):
        # Run twice
        await runner.trigger("go")
        await runner.wait_for_status("Multi", CommandStatus.SUCCESS, timeout=1.0)
        
        await runner.trigger("go")
        await runner.wait_for_status("Multi", CommandStatus.SUCCESS, timeout=1.0)
        
        # Should have 2 in history, 0 live
        history = runner.get_history("Multi")
        assert len(history) == 2
        assert runner.get_live_runs("Multi") == []


@pytest.mark.asyncio
async def test_get_commands_by_trigger_empty():
    """Test get_commands_by_trigger with no matches - covers line 434"""
    cfg = CommandConfig(name="Test", command="echo test", triggers=["real"])
    runner = CommandRunner([cfg])
    
    # Non-existent trigger
    cmds = runner.get_commands_by_trigger("fake")
    assert cmds == []


@pytest.mark.asyncio
async def test_has_trigger():
    """Test has_trigger method - covers line 437"""
    cfg = CommandConfig(name="Test", command="echo test", triggers=["exists"])
    runner = CommandRunner([cfg])
    
    assert runner.has_trigger("exists") is True
    assert runner.has_trigger("does_not_exist") is False


@pytest.mark.asyncio
async def test_add_var_and_set_vars():
    """Test variable management - covers lines 441-447"""
    cfg = CommandConfig(name="Test", command="echo {{msg}}", triggers=["go"])
    runner = CommandRunner([cfg])
    
    # add_var
    runner.add_var("msg", "hello")
    assert runner.vars["msg"] == "hello"
    
    # set_vars (bulk update)
    runner.set_vars({"msg": "world", "other": "value"})
    assert runner.vars["msg"] == "world"
    assert runner.vars["other"] == "value"


@pytest.mark.asyncio
async def test_validate_templates_non_strict():
    """Test validate_templates without strict mode - covers line 450"""
    cfg = CommandConfig(name="Bad", command="{{missing}}", triggers=["go"])
    runner = CommandRunner([cfg])
    
    # Non-strict returns dict of errors without raising
    errors = runner.validate_templates(strict=False)
    assert "Bad" in errors
    assert len(errors["Bad"]) > 0


@pytest.mark.asyncio
async def test_wait_for_status_with_list():
    """Test wait_for_status with list of statuses - covers line 460"""
    cfg = CommandConfig(name="Test", command="echo ok", triggers=["go"])
    runner = CommandRunner([cfg])
    
    with patch("asyncio.create_subprocess_shell", return_value=AsyncMock(
        communicate=AsyncMock(return_value=(b"ok\n", b"")),
        returncode=0
    )):
        await runner.trigger("go")
        
        # Wait for either RUNNING or SUCCESS
        reached = await runner.wait_for_status(
            "Test", 
            [CommandStatus.RUNNING, CommandStatus.SUCCESS], 
            timeout=1.0
        )
        assert reached is True


@pytest.mark.asyncio
async def test_wait_for_status_timeout():
    """Test wait_for_status timeout - covers line 479"""
    cfg = CommandConfig(name="Test", command="echo ok", triggers=["go"])
    runner = CommandRunner([cfg])
    
    # Never trigger it, so it stays IDLE
    reached = await runner.wait_for_status("Test", CommandStatus.RUNNING, timeout=0.1)
    assert reached is False


@pytest.mark.asyncio
async def test_duplicate_command_names_raises():
    """Test that duplicate command names are detected - covers line 142"""
    configs = [
        CommandConfig(name="Duplicate", command="echo 1", triggers=["a"]),
        CommandConfig(name="Duplicate", command="echo 2", triggers=["b"]),
    ]
    
    with pytest.raises(ValueError, match="Duplicate command names"):
        CommandRunner(configs)


@pytest.mark.asyncio
async def test_runner_with_list_of_configs():
    """Test CommandRunner init with list instead of RunnerConfig - covers line 140"""
    configs = [
        CommandConfig(name="Test", command="echo ok", triggers=["go"])
    ]
    
    # Should work with list directly
    runner = CommandRunner(configs)
    assert "Test" in runner._command_configs


@pytest.mark.asyncio
async def test_base_directory_override():
    """Test base_directory parameter - covers line 147-149"""
    cfg = CommandConfig(name="Test", command="echo ok", triggers=["go"])
    
    # With explicit base_directory
    runner = CommandRunner([cfg], base_directory="/custom/path")
    assert runner.vars["base_directory"] == "/custom/path"


@pytest.mark.asyncio
async def test_cancel_does_nothing_when_task_done():
    """Test RunResult.cancel when task is already done - covers line 84"""
    result = RunResult()
    result.command_name = "Test"
    result.task = AsyncMock()
    result.task.done.return_value = True  # Already done
    
    # Should not call cancel
    result.cancel()
    result.task.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_runresult_repr():
    """Test RunResult.__repr__ - covers line 119-123"""
    result = RunResult()
    result.command_name = "Test"
    result.mark_running()
    result.mark_success()
    
    repr_str = repr(result)
    assert "RunResult" in repr_str
    assert "Test" in repr_str
    assert "success" in repr_str or "SUCCESS" in repr_str