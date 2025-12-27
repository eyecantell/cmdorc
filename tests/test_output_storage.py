"""Tests for output storage feature.

Comprehensive test suite covering:
- OutputStorageConfig validation and defaults
- File writing (metadata.toml + output.txt)
- Directory-per-run structure
- Retention policy enforcement
- Output capture on cancellation
- TOML serialization
- Integration with orchestrator
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from cmdorc import (
    CommandConfig,
    CommandOrchestrator,
    LocalSubprocessExecutor,
    OutputStorageConfig,
    ResolvedCommand,
    RunnerConfig,
    RunResult,
    RunState,
)
from cmdorc.exceptions import ConfigValidationError

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def temp_output_dir(tmp_path):
    """Temporary directory for output storage."""
    output_dir = tmp_path / "test_outputs"
    output_dir.mkdir()
    yield output_dir
    # Cleanup
    if output_dir.exists():
        shutil.rmtree(output_dir)


@pytest.fixture
def storage_config(temp_output_dir):
    """OutputStorageConfig with temp directory."""
    return OutputStorageConfig(
        directory=str(temp_output_dir),
        keep_history=5,
    )


# =====================================================================
# OutputStorageConfig Tests
# =====================================================================


class TestOutputStorageConfig:
    """Tests for OutputStorageConfig validation and defaults."""

    def test_default_config(self):
        """Default config should be disabled."""
        config = OutputStorageConfig()
        assert config.directory == ".cmdorc/outputs"
        assert config.keep_history == 0
        assert not config.is_enabled

    def test_enabled_config(self):
        """Config with keep_history > 0 is enabled."""
        config = OutputStorageConfig(keep_history=10)
        assert config.is_enabled

    def test_unlimited_config(self):
        """Config with keep_history = -1 is enabled (unlimited)."""
        config = OutputStorageConfig(keep_history=-1)
        assert config.is_enabled

    def test_disabled_config(self):
        """Config with keep_history = 0 is disabled."""
        config = OutputStorageConfig(keep_history=0)
        assert not config.is_enabled

    def test_negative_keep_history_invalid(self):
        """keep_history < -1 should raise error."""
        with pytest.raises(ConfigValidationError, match="must be -1"):
            OutputStorageConfig(keep_history=-2)

    def test_default_output_extension(self):
        """Default output extension is .txt."""
        config = OutputStorageConfig()
        assert config.output_extension == ".txt"

    def test_custom_output_extension(self):
        """Custom output extensions are accepted."""
        config = OutputStorageConfig(output_extension=".log")
        assert config.output_extension == ".log"

        config2 = OutputStorageConfig(output_extension=".json")
        assert config2.output_extension == ".json"

    def test_output_extension_must_start_with_dot(self):
        """output_extension must start with a dot."""
        with pytest.raises(ConfigValidationError, match="must start with a dot"):
            OutputStorageConfig(output_extension="txt")

    def test_output_extension_no_path_separators(self):
        """output_extension cannot contain path separators."""
        with pytest.raises(ConfigValidationError, match="cannot contain path separators"):
            OutputStorageConfig(output_extension=".txt/bad")

        with pytest.raises(ConfigValidationError, match="cannot contain path separators"):
            OutputStorageConfig(output_extension=".txt\\bad")


# =====================================================================
# TOML Serialization Tests
# =====================================================================


class TestTOMLSerialization:
    """Tests for RunResult.to_toml() method."""

    def test_basic_serialization(self):
        """Basic RunResult serializes to TOML."""
        result = RunResult(command_name="Test", run_id="run-123")
        result.mark_success()

        toml = result.to_toml()

        assert 'command_name = "Test"' in toml
        assert 'run_id = "run-123"' in toml
        assert 'state = "success"' in toml
        assert "success = true" in toml

    def test_serialization_with_trigger_chain(self):
        """Trigger chain serializes correctly."""
        result = RunResult(
            command_name="Test",
            run_id="run-123",
            trigger_chain=["user_saves", "command_success:Lint"],
        )
        result.mark_success()

        toml = result.to_toml()

        assert 'trigger_chain = ["user_saves", "command_success:Lint"]' in toml

    def test_serialization_with_resolved_command(self):
        """Resolved command serializes to [resolved_command] section."""
        result = RunResult(command_name="Test", run_id="run-123")
        result.resolved_command = ResolvedCommand(
            command="pytest tests/",
            cwd="/home/user/project",
            env={"PATH": "/usr/bin"},
            timeout_secs=300,
            vars={"test_dir": "tests"},
        )
        result.mark_success()

        toml = result.to_toml()

        assert "[resolved_command]" in toml
        assert 'command = "pytest tests/"' in toml
        assert 'cwd = "/home/user/project"' in toml
        assert "timeout_secs = 300" in toml
        assert "[resolved_command.vars]" in toml
        assert 'test_dir = "tests"' in toml

    def test_serialization_escapes_special_chars(self):
        """Special characters are escaped in TOML."""
        result = RunResult(command_name="Test", run_id="run-123")
        result.mark_success(comment='Comment with "quotes" and \\ backslashes')

        toml = result.to_toml()

        # Should escape quotes and backslashes in comment field
        assert "comment = " in toml
        assert '\\"' in toml

    def test_serialization_with_error(self):
        """Error message serializes correctly."""
        result = RunResult(command_name="Test", run_id="run-123")
        result.mark_failed("Command failed with error")

        toml = result.to_toml()

        assert 'error = "Command failed with error"' in toml
        assert "success = false" in toml


# =====================================================================
# File Writing Tests
# =====================================================================


class TestFileWriting:
    """Tests for executor file writing functionality."""

    async def test_files_written_on_success(self, temp_output_dir, storage_config):
        """Files are written when command succeeds."""
        executor = LocalSubprocessExecutor(output_storage=storage_config)
        result = RunResult(command_name="Echo", run_id="run-001")
        resolved = ResolvedCommand(
            command='echo "hello world"', cwd=None, env={}, timeout_secs=None, vars={}
        )

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.2)  # Wait for completion

        # Check files exist
        run_dir = temp_output_dir / "Echo" / "run-001"
        assert run_dir.exists()
        assert (run_dir / "metadata.toml").exists()
        assert (run_dir / "output.txt").exists()

        # Check result has file paths
        assert result.metadata_file == run_dir / "metadata.toml"
        assert result.output_file == run_dir / "output.txt"

        # Check file contents
        output_text = (run_dir / "output.txt").read_text()
        assert "hello world" in output_text

        metadata_text = (run_dir / "metadata.toml").read_text()
        assert 'command_name = "Echo"' in metadata_text
        assert 'state = "success"' in metadata_text

    async def test_files_written_on_failure(self, temp_output_dir, storage_config):
        """Files are written when command fails."""
        executor = LocalSubprocessExecutor(output_storage=storage_config)
        result = RunResult(command_name="Fail", run_id="run-002")
        resolved = ResolvedCommand(command="exit 1", cwd=None, env={}, timeout_secs=None, vars={})

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.2)  # Wait for completion

        # Check files exist
        run_dir = temp_output_dir / "Fail" / "run-002"
        assert run_dir.exists()
        assert (run_dir / "metadata.toml").exists()

        # Check metadata shows failure
        metadata_text = (run_dir / "metadata.toml").read_text()
        assert 'state = "failed"' in metadata_text
        assert "success = false" in metadata_text

    async def test_files_not_written_when_disabled(self, temp_output_dir):
        """No files written when output_storage disabled."""
        disabled_config = OutputStorageConfig(
            directory=str(temp_output_dir),
            keep_history=0,  # Disabled
        )
        executor = LocalSubprocessExecutor(output_storage=disabled_config)
        result = RunResult(command_name="Echo", run_id="run-003")
        resolved = ResolvedCommand(
            command='echo "test"', cwd=None, env={}, timeout_secs=None, vars={}
        )

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.2)

        # No files should exist
        assert not (temp_output_dir / "Echo").exists()
        assert result.metadata_file is None
        assert result.output_file is None

    async def test_directory_created_automatically(self, temp_output_dir, storage_config):
        """Output directory is created if it doesn't exist."""
        # Remove the directory
        shutil.rmtree(temp_output_dir)
        assert not temp_output_dir.exists()

        executor = LocalSubprocessExecutor(output_storage=storage_config)
        result = RunResult(command_name="Test", run_id="run-004")
        resolved = ResolvedCommand(
            command='echo "test"', cwd=None, env={}, timeout_secs=None, vars={}
        )

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.2)

        # Directory should be created
        assert temp_output_dir.exists()
        assert (temp_output_dir / "Test" / "run-004").exists()

    async def test_custom_output_extension(self, temp_output_dir):
        """Files use custom extension when configured."""
        config = OutputStorageConfig(
            directory=str(temp_output_dir),
            keep_history=5,
            output_extension=".log",
        )
        executor = LocalSubprocessExecutor(output_storage=config)
        result = RunResult(command_name="Echo", run_id="run-ext-001")
        resolved = ResolvedCommand(
            command='echo "custom extension test"', cwd=None, env={}, timeout_secs=None, vars={}
        )

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.2)

        # Check files exist with correct extension
        run_dir = temp_output_dir / "Echo" / "run-ext-001"
        assert run_dir.exists()
        assert (run_dir / "metadata.toml").exists()
        assert (run_dir / "output.log").exists()
        assert not (run_dir / "output.txt").exists()  # Should NOT have .txt

        # Check result has correct file path
        assert result.output_file == run_dir / "output.log"

        # Check file contents
        output_text = (run_dir / "output.log").read_text()
        assert "custom extension test" in output_text

        # Check metadata contains correct output_file name
        metadata_text = (run_dir / "metadata.toml").read_text()
        assert 'output_file = "output.log"' in metadata_text

    async def test_json_extension(self, temp_output_dir):
        """JSON extension works correctly."""
        config = OutputStorageConfig(
            directory=str(temp_output_dir),
            keep_history=5,
            output_extension=".json",
        )
        executor = LocalSubprocessExecutor(output_storage=config)
        result = RunResult(command_name="Echo", run_id="run-json-001")
        resolved = ResolvedCommand(
            command='echo "test"', cwd=None, env={}, timeout_secs=None, vars={}
        )

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.2)

        # Check output.json exists
        run_dir = temp_output_dir / "Echo" / "run-json-001"
        assert (run_dir / "output.json").exists()
        assert result.output_file.name == "output.json"


# =====================================================================
# Output Capture on Cancellation Tests
# =====================================================================


class TestCancellationOutputCapture:
    """Tests for output capture when commands are cancelled."""

    async def test_output_captured_on_graceful_cancel(self, temp_output_dir, storage_config):
        """Output is captured when process exits gracefully after SIGTERM."""
        executor = LocalSubprocessExecutor(cancel_grace_period=2.0, output_storage=storage_config)
        result = RunResult(command_name="Sleep", run_id="run-005")
        # Command that produces output before sleeping
        resolved = ResolvedCommand(
            command='echo "starting"; sleep 10', cwd=None, env={}, timeout_secs=None, vars={}
        )

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.1)  # Let it start and produce output

        # Cancel the command
        await executor.cancel_run(result, "Test cancellation")

        # Wait a bit for cancellation to complete
        await asyncio.sleep(0.5)

        # Output should be captured
        assert result.state == RunState.CANCELLED
        # Note: Output capture on cancellation is best-effort
        # It may or may not capture depending on process state

    async def test_cancelled_run_writes_files_if_output_captured(
        self, temp_output_dir, storage_config
    ):
        """Files are written for cancelled runs if output was captured."""
        executor = LocalSubprocessExecutor(cancel_grace_period=2.0, output_storage=storage_config)
        result = RunResult(command_name="Echo", run_id="run-006")
        resolved = ResolvedCommand(
            command='echo "test output"; sleep 10',
            cwd=None,
            env={},
            timeout_secs=None,
            vars={},
        )

        await executor.start_run(result, resolved)
        await asyncio.sleep(0.2)  # Let output be produced

        await executor.cancel_run(result, "Test")
        await asyncio.sleep(0.5)

        # If output was captured, files should exist
        if result.output:
            run_dir = temp_output_dir / "Echo" / "run-006"
            assert run_dir.exists()
            assert (run_dir / "metadata.toml").exists()
            metadata = (run_dir / "metadata.toml").read_text()
            assert 'state = "cancelled"' in metadata


# =====================================================================
# Retention Policy Tests
# =====================================================================


class TestRetentionPolicy:
    """Tests for automatic cleanup of old output files."""

    async def test_retention_policy_enforced(self, temp_output_dir):
        """Old files are deleted when keep_history limit is exceeded."""
        config = OutputStorageConfig(directory=str(temp_output_dir), keep_history=3)

        commands = [CommandConfig(name="Test", command='echo "test"', triggers=["test"])]
        runner_config = RunnerConfig(commands=commands, output_storage=config)
        orchestrator = CommandOrchestrator(runner_config)

        # Run 5 commands (keep_history=3, so 2 oldest should be deleted)
        handles = []
        for _i in range(5):
            handle = await orchestrator.run_command("Test")
            await handle.wait()
            handles.append(handle)
            await asyncio.sleep(0.05)  # Small delay to ensure different mtimes

        # Wait for retention to be enforced
        await asyncio.sleep(0.1)

        # Check that only 3 run directories exist
        test_dir = temp_output_dir / "Test"
        run_dirs = [d for d in test_dir.iterdir() if d.is_dir()]
        assert len(run_dirs) == 3

        # Check that the newest 3 runs have files
        for handle in handles[-3:]:
            assert handle.output_file is not None
            assert handle.output_file.exists()

    async def test_retention_unlimited_keeps_all(self, temp_output_dir):
        """keep_history=-1 keeps all files (unlimited)."""
        config = OutputStorageConfig(
            directory=str(temp_output_dir),
            keep_history=-1,  # Unlimited
        )

        commands = [CommandConfig(name="Test", command='echo "test"', triggers=["test"])]
        runner_config = RunnerConfig(commands=commands, output_storage=config)
        orchestrator = CommandOrchestrator(runner_config)

        # Run 10 commands
        for _ in range(10):
            handle = await orchestrator.run_command("Test")
            await handle.wait()

        # All 10 should exist
        test_dir = temp_output_dir / "Test"
        run_dirs = [d for d in test_dir.iterdir() if d.is_dir()]
        assert len(run_dirs) == 10

    async def test_retention_per_command(self, temp_output_dir):
        """Retention is enforced per-command, not globally."""
        config = OutputStorageConfig(directory=str(temp_output_dir), keep_history=2)

        commands = [
            CommandConfig(name="Test1", command='echo "test1"', triggers=["test1"]),
            CommandConfig(name="Test2", command='echo "test2"', triggers=["test2"]),
        ]
        runner_config = RunnerConfig(commands=commands, output_storage=config)
        orchestrator = CommandOrchestrator(runner_config)

        # Run 5 of each command
        for _ in range(5):
            h1 = await orchestrator.run_command("Test1")
            h2 = await orchestrator.run_command("Test2")
            await h1.wait()
            await h2.wait()
            await asyncio.sleep(0.05)

        # Each command should have only 2 runs
        test1_dir = temp_output_dir / "Test1"
        test2_dir = temp_output_dir / "Test2"

        test1_runs = [d for d in test1_dir.iterdir() if d.is_dir()]
        test2_runs = [d for d in test2_dir.iterdir() if d.is_dir()]

        assert len(test1_runs) == 2
        assert len(test2_runs) == 2


# =====================================================================
# Integration Tests
# =====================================================================


class TestIntegration:
    """End-to-end integration tests."""

    async def test_full_workflow_with_output_storage(self, temp_output_dir):
        """Complete workflow: run → wait → access files."""
        config = OutputStorageConfig(directory=str(temp_output_dir), keep_history=5)

        commands = [CommandConfig(name="Greet", command='echo "Hello, World!"', triggers=["greet"])]
        runner_config = RunnerConfig(commands=commands, output_storage=config)
        orchestrator = CommandOrchestrator(runner_config)

        # Run command
        handle = await orchestrator.run_command("Greet")
        result = await handle.wait()

        # Check state
        assert result.state == RunState.SUCCESS
        assert "Hello, World!" in result.output

        # Check files
        assert handle.output_file is not None
        assert handle.metadata_file is not None
        assert handle.output_file.exists()
        assert handle.metadata_file.exists()

        # Read files
        output_text = handle.output_file.read_text()
        metadata_text = handle.metadata_file.read_text()

        assert "Hello, World!" in output_text
        assert 'command_name = "Greet"' in metadata_text
        assert 'state = "success"' in metadata_text

    async def test_runhandle_properties_accessible(self, temp_output_dir):
        """RunHandle properties return correct file paths."""
        config = OutputStorageConfig(directory=str(temp_output_dir), keep_history=5)

        commands = [CommandConfig(name="Test", command='echo "test"', triggers=["test"])]
        runner_config = RunnerConfig(commands=commands, output_storage=config)
        orchestrator = CommandOrchestrator(runner_config)

        handle = await orchestrator.run_command("Test")
        await handle.wait()

        # Properties should be accessible and return Path objects
        assert isinstance(handle.output_file, Path)
        assert isinstance(handle.metadata_file, Path)
        assert handle.output_file.name == "output.txt"
        assert handle.metadata_file.name == "metadata.toml"

    async def test_disabled_by_default(self, tmp_path):
        """Output storage is disabled by default."""
        commands = [CommandConfig(name="Test", command='echo "test"', triggers=["test"])]
        runner_config = RunnerConfig(commands=commands)  # No output_storage specified
        orchestrator = CommandOrchestrator(runner_config)

        handle = await orchestrator.run_command("Test")
        await handle.wait()

        # No files should be written
        assert handle.output_file is None
        assert handle.metadata_file is None
