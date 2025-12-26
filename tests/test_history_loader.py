"""Tests for history_loader module."""

from __future__ import annotations

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, OutputStorageConfig, RunnerConfig
from cmdorc.command_runtime import CommandRuntime
from cmdorc.history_loader import HistoryLoader


class TestHistoryLoader:
    """Tests for HistoryLoader class."""

    def test_load_all_disabled_storage(self, tmp_path):
        """No loading when output storage is disabled."""
        runtime = CommandRuntime()
        runtime.register_command(
            CommandConfig(name="Test", command="echo test", triggers=["test"], keep_in_memory=5)
        )

        storage = OutputStorageConfig(keep_history=0)  # Disabled
        loader = HistoryLoader(runtime, storage)

        counts = loader.load_all()

        assert counts == {}

    def test_load_all_directory_not_exists(self, tmp_path):
        """No loading when directory doesn't exist."""
        runtime = CommandRuntime()
        runtime.register_command(
            CommandConfig(name="Test", command="echo test", triggers=["test"], keep_in_memory=5)
        )

        storage = OutputStorageConfig(directory=str(tmp_path / "nonexistent"), keep_history=10)
        loader = HistoryLoader(runtime, storage)

        counts = loader.load_all()

        assert counts == {}

    def test_load_command_with_keep_in_memory_zero(self, tmp_path):
        """Skip loading when keep_in_memory=0."""
        runtime = CommandRuntime()
        runtime.register_command(
            CommandConfig(name="Test", command="echo test", triggers=["test"], keep_in_memory=0)
        )

        storage = OutputStorageConfig(directory=str(tmp_path), keep_history=10)
        loader = HistoryLoader(runtime, storage)

        counts = loader.load_all()

        assert counts == {}

    async def test_load_from_disk_integration(self, tmp_path):
        """Integration test: write runs, restart, verify loading."""
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Phase 1: Create orchestrator and run commands
        config1 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner1 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test", command='echo "hello"', triggers=["test"], keep_in_memory=3
                )
            ],
            output_storage=config1,
        )
        orch1 = CommandOrchestrator(runner1)

        # Run 5 commands
        for _i in range(5):
            handle = await orch1.run_command("Test")
            await handle.wait()
            await asyncio.sleep(0.05)  # Ensure different mtimes

        # Verify files written
        test_dir = output_dir / "Test"
        run_dirs = list(test_dir.iterdir())
        assert len(run_dirs) == 5

        # Phase 2: Create new orchestrator (simulates restart)
        config2 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner2 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test", command='echo "hello"', triggers=["test"], keep_in_memory=3
                )
            ],
            output_storage=config2,
        )
        orch2 = CommandOrchestrator(runner2)

        # Verify history loaded (should have 3, limited by keep_in_memory)
        history = orch2.get_history("Test")
        assert len(history) == 3

        # Verify the loaded runs are the most recent 3
        assert all(result.command_name == "Test" for result in history)
        assert all(result.state.value == "success" for result in history)
        assert all(result.output.strip() == "hello" for result in history)

    async def test_load_unlimited_memory(self, tmp_path):
        """Test loading with keep_in_memory=-1 (unlimited)."""
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Phase 1: Write 10 runs
        config1 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner1 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test", command='echo "test"', triggers=["test"], keep_in_memory=10
                )
            ],
            output_storage=config1,
        )
        orch1 = CommandOrchestrator(runner1)

        for _ in range(10):
            handle = await orch1.run_command("Test")
            await handle.wait()
            await asyncio.sleep(0.05)

        # Phase 2: Restart with unlimited memory
        config2 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner2 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test",
                    command='echo "test"',
                    triggers=["test"],
                    keep_in_memory=-1,  # Unlimited
                )
            ],
            output_storage=config2,
        )
        orch2 = CommandOrchestrator(runner2)

        # Should load all 10 runs
        history = orch2.get_history("Test", limit=0)  # No limit
        assert len(history) == 10

    async def test_load_multiple_commands(self, tmp_path):
        """Test loading history for multiple commands."""
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Phase 1: Write runs for two commands
        config1 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner1 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test1", command='echo "test1"', triggers=["test1"], keep_in_memory=5
                ),
                CommandConfig(
                    name="Test2", command='echo "test2"', triggers=["test2"], keep_in_memory=5
                ),
            ],
            output_storage=config1,
        )
        orch1 = CommandOrchestrator(runner1)

        # Run each command 3 times
        for _ in range(3):
            h1 = await orch1.run_command("Test1")
            h2 = await orch1.run_command("Test2")
            await h1.wait()
            await h2.wait()
            await asyncio.sleep(0.05)

        # Phase 2: Restart
        config2 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner2 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test1", command='echo "test1"', triggers=["test1"], keep_in_memory=5
                ),
                CommandConfig(
                    name="Test2", command='echo "test2"', triggers=["test2"], keep_in_memory=5
                ),
            ],
            output_storage=config2,
        )
        orch2 = CommandOrchestrator(runner2)

        # Both commands should have loaded history
        history1 = orch2.get_history("Test1")
        history2 = orch2.get_history("Test2")

        assert len(history1) == 3
        assert len(history2) == 3

    async def test_load_with_fewer_files_than_limit(self, tmp_path):
        """Load all available files when fewer than keep_in_memory."""
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Phase 1: Write 2 runs
        config1 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner1 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test", command='echo "test"', triggers=["test"], keep_in_memory=5
                )
            ],
            output_storage=config1,
        )
        orch1 = CommandOrchestrator(runner1)

        for _ in range(2):
            handle = await orch1.run_command("Test")
            await handle.wait()
            await asyncio.sleep(0.05)

        # Phase 2: Restart with keep_in_memory=10 (more than available)
        config2 = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner2 = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test", command='echo "test"', triggers=["test"], keep_in_memory=10
                )
            ],
            output_storage=config2,
        )
        orch2 = CommandOrchestrator(runner2)

        # Should load all 2 available runs
        history = orch2.get_history("Test")
        assert len(history) == 2

    async def test_skip_directory_without_metadata(self, tmp_path):
        """Skip run directories without metadata.toml."""
        output_dir = tmp_path / "outputs"
        test_dir = output_dir / "Test"
        test_dir.mkdir(parents=True)

        # Create a run directory without metadata.toml
        bad_run = test_dir / "run-bad"
        bad_run.mkdir()
        (bad_run / "output.txt").write_text("orphaned output")

        # Create a valid run
        good_run = test_dir / "run-good"
        good_run.mkdir()
        (good_run / "metadata.toml").write_text(
            """
command_name = "Test"
run_id = "run-good"
state = "success"
duration_str = "1s"
"""
        )
        (good_run / "output.txt").write_text("valid output")

        # Load
        config = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test", command='echo "test"', triggers=["test"], keep_in_memory=5
                )
            ],
            output_storage=config,
        )
        orch = CommandOrchestrator(runner)

        # Should only load the valid run
        history = orch.get_history("Test")
        assert len(history) == 1
        assert history[0].run_id == "run-good"

    async def test_ignore_unknown_commands(self, tmp_path):
        """Ignore run directories for commands not in config."""
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        # Create run for command that doesn't exist in config
        unknown_dir = output_dir / "UnknownCommand"
        unknown_dir.mkdir()
        run_dir = unknown_dir / "run-123"
        run_dir.mkdir()
        (run_dir / "metadata.toml").write_text(
            """
command_name = "UnknownCommand"
run_id = "run-123"
state = "success"
duration_str = "1s"
"""
        )

        # Load with different command
        config = OutputStorageConfig(directory=str(output_dir), keep_history=10)
        runner = RunnerConfig(
            commands=[
                CommandConfig(
                    name="Test", command='echo "test"', triggers=["test"], keep_in_memory=5
                )
            ],
            output_storage=config,
        )
        orch = CommandOrchestrator(runner)

        # UnknownCommand should be ignored
        history = orch.get_history("Test")
        assert len(history) == 0
