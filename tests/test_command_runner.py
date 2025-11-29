# tests/test_command_runner.py
import asyncio
import pytest
from unittest.mock import patch, AsyncMock
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
        mock_proc.communicate.return_value = (b"hello", b"")
        mock_proc.returncode = 0
        
        await sample_runner.trigger("test_trigger")
        
        assert sample_runner.get_status("TestCmd") == "success"  # After run
        result = sample_runner.get_result("TestCmd")
        assert result.success
        assert "hello" in result.output  # Combined
        assert result.state == "success"
        assert len(sample_runner.get_history("TestCmd")) == 1

@pytest.mark.asyncio
async def test_cancel(sample_runner):
    with patch("asyncio.create_subprocess_shell", new=AsyncMock()) as mock_shell:
        mock_proc = mock_shell.return_value
        mock_proc.communicate = asyncio.create_task(asyncio.sleep(1))  # Simulate long run
        
        await sample_runner.trigger("test_trigger")
        sample_runner.cancel_command("TestCmd")
        
        await asyncio.sleep(0.1)  # Let cancel propagate
        assert sample_runner.get_status("TestCmd") == "cancelled"
        result = sample_runner.get_result("TestCmd")
        assert result.state == "cancelled"

@pytest.mark.asyncio
async def test_auto_trigger_chaining():
    config1 = CommandConfig(name="Step1", command="echo step1", triggers=["start"], keep_history=1)
    config2 = CommandConfig(name="Step2", command="echo step2", triggers=["command_success:Step1"], keep_history=1)
    runner = CommandRunner([config1, config2])
    
    with patch("asyncio.create_subprocess_shell") as mock_shell:
        mock_proc = mock_shell.return_value
        mock_proc.communicate.return_value = (b"output", b"")
        mock_proc.returncode = 0
        
        await runner.trigger("start")
        
        assert runner.get_status("Step1") == "success"
        assert runner.get_status("Step2") == "success"  # Chained

@pytest.mark.asyncio
async def test_callback_on_trigger(sample_runner):
    callback_called = False
    def cb(payload):
        nonlocal callback_called
        callback_called = True
    
    sample_runner.on_trigger("test_trigger", cb)
    
    await sample_runner.trigger("test_trigger")
    
    assert callback_called

@pytest.mark.asyncio
async def test_cycle_detection(sample_runner):
    # Force a cycle by self-trigger
    with patch("logging.warning") as mock_warn:
        await sample_runner.trigger("test_trigger")  # First fire
        await sample_runner.trigger("test_trigger")  # Cycle if not guarded, but guarded skips
        
        assert mock_warn.called  # Warning on cycle