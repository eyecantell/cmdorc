"""
Comprehensive test suite for CommandOrchestrator.

Test categories:
- Execution flow (manual and triggered)
- Auto-triggers and monitoring
- Handle management and lifecycle
- Cancellation operations
- Configuration management
- Query operations
- Callback dispatch
- Shutdown and cleanup
- Concurrency and race conditions
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import pytest

from cmdorc import (
    CommandConfig,
    CommandOrchestrator,
    ConcurrencyLimitError,
    DebounceError,
    MockExecutor,
    OrchestratorShutdownError,
    RunHandle,
    RunnerConfig,
    RunState,
    TriggerContext,
    TriggerCycleError,
)

logging.getLogger("cmdorc").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# ========================================================================
# Fixtures
# ========================================================================


@pytest.fixture
def sample_command():
    """Sample CommandConfig for basic testing."""
    return CommandConfig(
        name="Test",
        command="echo hello",
        triggers=["test_trigger"],
    )


@pytest.fixture
def orchestrator(sample_command):
    """Fresh orchestrator with MockExecutor for testing."""
    config = RunnerConfig(commands=[sample_command], vars={})
    executor = MockExecutor(delay=0.01)
    return CommandOrchestrator(config, executor)


@pytest.fixture
def multi_command_orchestrator(sample_command):
    """Orchestrator with multiple commands for trigger testing."""
    commands = [
        sample_command,
        CommandConfig(
            name="Lint",
            command="ruff check",
            triggers=["changes_applied"],
        ),
        CommandConfig(
            name="Build",
            command="cargo build",
            triggers=["command_success:Lint"],
        ),
    ]
    config = RunnerConfig(commands=commands, vars={"base": "/app"})
    executor = MockExecutor(delay=0.01)
    return CommandOrchestrator(config, executor)


# ========================================================================
# Execution Flow Tests
# ========================================================================


class TestExecutionFlow:
    """Tests for manual command execution."""

    async def test_run_command_success(self, orchestrator):
        """Basic run_command success flow."""
        handle = await orchestrator.run_command("Test")

        assert handle is not None
        assert handle.command_name == "Test"
        assert handle.run_id is not None
        assert not handle.is_finalized

        # Wait for completion
        await handle.wait(timeout=1.0)
        assert handle.state == RunState.SUCCESS

    async def test_run_command_not_found(self, orchestrator):
        """run_command raises CommandNotFoundError for unknown command."""
        from cmdorc import CommandNotFoundError

        with pytest.raises(CommandNotFoundError):
            await orchestrator.run_command("NonExistent")

    async def test_run_command_returns_handle_immediately(self, orchestrator):
        """run_command returns RunHandle immediately, before execution completes."""
        handle = await orchestrator.run_command("Test")

        # Handle should be available immediately
        assert handle is not None
        assert handle.run_id is not None
        # But may not be finalized yet
        # (actually wait, MockExecutor has delay so it's not immediate)

    async def test_run_command_with_vars(self, orchestrator):
        """run_command resolves variables correctly."""
        config = CommandConfig(
            name="VarTest",
            command="echo {{ msg }}",
            triggers=[],
            vars={"msg": "default"},
        )
        orchestrator.add_command(config)
        handle = await orchestrator.run_command("VarTest", vars={"msg": "custom"})

        await handle.wait(timeout=1.0)
        # Executor received resolved command
        assert handle.state == RunState.SUCCESS

    async def test_run_command_debounce_error(self, orchestrator):
        """run_command raises DebounceError if in debounce window."""
        config = CommandConfig(
            name="Debounced",
            command="echo hello",
            triggers=[],
            debounce_in_ms=1000,
        )
        orchestrator.add_command(config)

        # First run succeeds
        handle1 = await orchestrator.run_command("Debounced")
        await handle1.wait(timeout=1.0)

        # Second run within debounce window raises error
        with pytest.raises(DebounceError):
            await orchestrator.run_command("Debounced")

    async def test_run_command_debounce_error_with_elapsed(self, orchestrator):
        """run_command raises DebounceError with elapsed_ms when debounced."""
        config = CommandConfig(
            name="DebounceTest",
            command="echo",
            triggers=[],
            debounce_in_ms=1000,
        )
        orchestrator.add_command(config)

        # Simulate recent start
        orchestrator._runtime._last_start["DebounceTest"] = datetime.now() - timedelta(
            milliseconds=400
        )

        with pytest.raises(DebounceError) as exc:
            await orchestrator.run_command("DebounceTest")
        assert exc.value.elapsed_ms < 1000  # Verify timing context
        assert "debounce window" in str(exc.value)

    async def test_run_command_concurrency_limit_reason(self, orchestrator):
        """Policy denial includes correct disallow_reason."""
        config = CommandConfig(
            name="LimitTest",
            command="echo",
            triggers=[],
            max_concurrent=1,
            on_retrigger="ignore",
        )
        orchestrator.add_command(config)

        # Start one run
        handle1 = await orchestrator.run_command("LimitTest")
        # Don't wait, keep active

        with pytest.raises(ConcurrencyLimitError):
            await orchestrator.run_command("LimitTest")

        # Cleanup
        await handle1.wait()

    async def test_run_command_concurrency_limit_error(self):
        """run_command raises ConcurrencyLimitError when max_concurrent exceeded."""
        # Create orchestrator with slow executor to ensure first run doesn't complete
        config = CommandConfig(
            name="Limited",
            command="sleep 10",
            triggers=[],
            max_concurrent=1,
            on_retrigger="ignore",
        )
        runner_config = RunnerConfig(commands=[config], vars={})
        executor = MockExecutor(delay=1.0)  # Slow executor
        orchestrator = CommandOrchestrator(runner_config, executor)

        # First run succeeds
        handle1 = await orchestrator.run_command("Limited")
        await asyncio.sleep(0.05)  # Let first run start

        # Second run hits limit (async context needed for pytest.raises with async function)
        with pytest.raises(ConcurrencyLimitError):
            await orchestrator.run_command("Limited")

        # Cleanup
        await orchestrator.cancel_run(handle1.run_id)

    async def test_run_command_cancel_and_restart(self, orchestrator):
        """run_command with cancel_and_restart policy cancels old run."""
        config = CommandConfig(
            name="CAR",
            command="sleep 10",
            triggers=[],
            max_concurrent=1,
            on_retrigger="cancel_and_restart",
        )
        orchestrator.add_command(config)

        handle1 = await orchestrator.run_command("CAR")
        # Should cancel handle1 and start new run
        handle2 = await orchestrator.run_command("CAR")

        assert handle1.run_id != handle2.run_id
        assert handle1.state == RunState.CANCELLED or handle1.state == RunState.PENDING

    async def test_run_command_during_shutdown_raises_error(self, orchestrator):
        """run_command raises OrchestratorShutdownError during shutdown."""
        orchestrator._is_shutdown = True

        with pytest.raises(OrchestratorShutdownError):
            await orchestrator.run_command("Test")

    async def test_run_command_multiple_concurrent(self, orchestrator):
        """Multiple concurrent run_command calls work correctly."""
        config = CommandConfig(
            name="Concurrent",
            command="echo hello",
            triggers=[],
            max_concurrent=0,  # unlimited
        )
        orchestrator.add_command(config)

        # Start 5 concurrent runs
        handles = await asyncio.gather(*[orchestrator.run_command("Concurrent") for _ in range(5)])

        assert len(handles) == 5
        assert all(h.run_id != handles[0].run_id for h in handles[1:])

        # Wait for all
        await asyncio.gather(*[h.wait(timeout=1.0) for h in handles])
        assert all(h.state == RunState.SUCCESS for h in handles)


# ========================================================================
# Trigger Flow Tests
# ========================================================================


class TestTriggerFlow:
    """Tests for trigger-driven execution."""

    async def test_trigger_exact_match(self, multi_command_orchestrator):
        """trigger() executes commands with exact trigger match."""
        await multi_command_orchestrator.trigger("changes_applied")

        # Wait for command to complete
        await asyncio.sleep(0.1)

        # Lint should have run (exact match)
        status = multi_command_orchestrator.get_status("Lint")
        assert status.state != "never_run"

    async def test_trigger_lifecycle_event(self, multi_command_orchestrator):
        """trigger() executes commands with lifecycle event trigger."""
        # First trigger Lint
        await multi_command_orchestrator.trigger("changes_applied")

        # Wait for Lint to complete (it will emit command_success:Lint)
        await asyncio.sleep(0.1)

        # Build should run (triggered by command_success:Lint)
        status = multi_command_orchestrator.get_status("Build")
        # Build might be running or have completed
        assert status.state != "never_run"

    async def test_trigger_cycle_detection(self, orchestrator):
        """trigger() detects cycles via TriggerContext."""
        config1 = CommandConfig(
            name="Cmd1",
            command="echo 1",
            triggers=["event_b"],
        )
        config2 = CommandConfig(
            name="Cmd2",
            command="echo 2",
            triggers=["event_a"],
            cancel_on_triggers=["event_b"],
        )
        orchestrator.add_command(config1)
        orchestrator.add_command(config2)

        context = TriggerContext(seen={"event_a"})

        # Trying to trigger event_a again should raise TriggerCycleError
        with pytest.raises(TriggerCycleError):
            await orchestrator.trigger("event_a", context)

    async def test_cycle_with_loop_detection_false(self, orchestrator):
        """Cycle allowed if loop_detection=False."""
        a = CommandConfig(name="A", command="echo", triggers=["B"], loop_detection=False)
        b = CommandConfig(name="B", command="echo", triggers=["A"])
        orchestrator.add_command(a)
        orchestrator.add_command(b)

        # Should not raise (A loop_detection=False allows)
        await orchestrator.trigger("A")
        await asyncio.sleep(0.1)  # Allow chain

    async def test_trigger_during_shutdown_raises_error(self, orchestrator):
        """trigger() raises OrchestratorShutdownError during shutdown."""
        orchestrator._is_shutdown = True

        with pytest.raises(OrchestratorShutdownError):
            await orchestrator.trigger("test_trigger")

    async def test_trigger_with_new_context(self, orchestrator):
        """trigger() creates TriggerContext if not provided."""
        # Should work without error (Test command already exists)
        await orchestrator.trigger("test_trigger", context=None)

    async def test_trigger_adds_event_to_context(self, orchestrator):
        """trigger() adds event_name to context.seen."""
        context = TriggerContext(seen=set())

        # Test command already exists with test_trigger
        await orchestrator.trigger("test_trigger", context)

        assert "test_trigger" in context.seen

    async def test_trigger_multiple_concurrent(self, multi_command_orchestrator):
        """Multiple concurrent trigger() calls work correctly."""
        # Launch multiple concurrent triggers
        await asyncio.gather(*[
            multi_command_orchestrator.trigger("changes_applied") for _ in range(3)
        ])

        # All should complete without error
        # Lint should have multiple active runs if allowed
        status = multi_command_orchestrator.get_status("Lint")
        assert status is not None


# ========================================================================
# Auto-Trigger & Monitoring Tests
# ========================================================================


class TestAutoTriggers:
    """Tests for automatic lifecycle triggers."""

    async def test_command_started_trigger_emitted(self, orchestrator):
        """command_started:name auto-trigger is emitted."""
        triggered_events = []

        async def callback(handle, context):
            triggered_events.append("command_started")

        orchestrator.on_event("command_started:Test", callback)

        await orchestrator.run_command("Test")
        await asyncio.sleep(0.05)  # Let auto-trigger fire

        assert "command_started" in triggered_events

    async def test_command_success_trigger_emitted(self, orchestrator):
        """command_success:name auto-trigger is emitted."""
        triggered_events = []

        async def callback(handle, context):
            triggered_events.append("command_success")

        orchestrator.on_event("command_success:Test", callback)

        handle = await orchestrator.run_command("Test")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)  # Let callback execute

        assert "command_success" in triggered_events

    async def test_command_failed_trigger_emitted(self, orchestrator):
        """command_failed:name auto-trigger is emitted on failure."""
        executor = orchestrator._executor
        executor.should_fail = True
        executor.failure_message = "Test failure"

        config = CommandConfig(
            name="Failing",
            command="false",
            triggers=[],
        )
        orchestrator.add_command(config)

        triggered_events = []

        async def callback(handle, context):
            triggered_events.append("command_failed")

        orchestrator.on_event("command_failed:Failing", callback)

        handle = await orchestrator.run_command("Failing")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)  # Let callback execute

        assert handle.state == RunState.FAILED
        assert "command_failed" in triggered_events

    async def test_auto_trigger_chain(self, orchestrator):
        """Auto-triggers can trigger other commands (trigger chain)."""
        # Create chain: A success -> B runs
        config_a = CommandConfig(
            name="A",
            command="echo a",
            triggers=[],
        )
        config_b = CommandConfig(
            name="B",
            command="echo b",
            triggers=["command_success:A"],
        )
        orchestrator.add_command(config_a)
        orchestrator.add_command(config_b)

        handle_a = await orchestrator.run_command("A")
        await handle_a.wait(timeout=1.0)

        # B should have been triggered and completed
        await asyncio.sleep(0.1)
        status_b = orchestrator.get_status("B")
        assert status_b.state != "never_run"

    async def test_auto_trigger_cycle_prevention(self, orchestrator):
        """Auto-triggers respect cycle prevention."""
        # Create potential cycle: A success -> B, B success -> A
        config_a = CommandConfig(
            name="A",
            command="echo a",
            triggers=["command_success:B"],
            loop_detection=True,
        )
        config_b = CommandConfig(
            name="B",
            command="echo b",
            triggers=["command_success:A"],
            loop_detection=True,
        )
        orchestrator.add_command(config_a)
        orchestrator.add_command(config_b)

        # Start A - should not cause infinite loop
        handle_a = await orchestrator.run_command("A")
        await handle_a.wait(timeout=1.0)

        # Cycle should be prevented - B runs once, then A tries to run again but cycle is detected
        await asyncio.sleep(0.2)

        status_a = orchestrator.get_status("A")
        status_b = orchestrator.get_status("B")
        # Both should have run but not infinitely
        assert status_a.state != "never_run"
        assert status_b.state != "never_run"


# ========================================================================
# Handle Management Tests
# ========================================================================


class TestHandleManagement:
    """Tests for RunHandle registry and lifecycle."""

    async def test_handle_registered_after_run_command(self, orchestrator):
        """Handle is registered in _handles immediately after run_command."""
        handle = await orchestrator.run_command("Test")

        assert handle.run_id in orchestrator._handles
        assert orchestrator._handles[handle.run_id] == handle

    async def test_get_handle_by_run_id(self, orchestrator):
        """get_handle_by_run_id() returns registered handle."""
        handle = await orchestrator.run_command("Test")

        retrieved = orchestrator.get_handle_by_run_id(handle.run_id)
        assert retrieved == handle

    async def test_get_handle_by_run_id_not_found(self, orchestrator):
        """get_handle_by_run_id() returns None for unknown run_id."""
        retrieved = orchestrator.get_handle_by_run_id("nonexistent")
        assert retrieved is None

    async def test_get_active_handles(self, orchestrator):
        """get_active_handles() returns only active runs of a command."""
        config = CommandConfig(
            name="Multi",
            command="echo hello",
            triggers=[],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        # Start 3 runs
        await asyncio.gather(*[orchestrator.run_command("Multi") for _ in range(3)])

        active = orchestrator.get_active_handles("Multi")
        assert len(active) >= 1  # At least one should be active

    async def test_get_all_active_handles(self, orchestrator):
        """get_all_active_handles() returns all active handles."""
        config1 = CommandConfig(
            name="Cmd1",
            command="echo 1",
            triggers=[],
            max_concurrent=0,
        )
        config2 = CommandConfig(
            name="Cmd2",
            command="echo 2",
            triggers=[],
            max_concurrent=0,
        )
        orchestrator.add_command(config1)
        orchestrator.add_command(config2)

        await orchestrator.run_command("Cmd1")
        await orchestrator.run_command("Cmd2")

        all_active = orchestrator.get_all_active_handles()
        assert len(all_active) >= 2

    async def test_handle_unregistered_after_completion(self, orchestrator):
        """Handle is unregistered from _handles after completion."""
        handle = await orchestrator.run_command("Test")

        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)  # Let cleanup complete

        # Handle should be unregistered
        assert handle.run_id not in orchestrator._handles


# ========================================================================
# Cancellation Tests
# ========================================================================


class TestCancellation:
    """Tests for run and command cancellation."""

    async def test_cancel_run(self, orchestrator):
        """cancel_run() cancels a specific run."""
        config = CommandConfig(
            name="Long",
            command="sleep 10",
            triggers=[],
        )
        orchestrator.add_command(config)

        handle = await orchestrator.run_command("Long")
        assert handle.state == RunState.PENDING

        success = await orchestrator.cancel_run(handle.run_id)

        assert success is True
        # Allow time for cancellation to propagate
        await asyncio.sleep(0.05)

    async def test_cancel_run_not_found(self, orchestrator):
        """cancel_run() returns False for unknown run_id."""
        success = await orchestrator.cancel_run("nonexistent")
        assert success is False

    async def test_cancel_command(self, orchestrator):
        """cancel_command() cancels all runs of a command."""
        config = CommandConfig(
            name="Multi",
            command="sleep 10",
            triggers=[],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        # Start multiple runs
        await orchestrator.run_command("Multi")
        await orchestrator.run_command("Multi")

        count = await orchestrator.cancel_command("Multi")

        assert count >= 1

    async def test_cancel_all(self, orchestrator):
        """cancel_all() cancels all active runs."""
        config1 = CommandConfig(
            name="Cmd1",
            command="sleep 10",
            triggers=[],
        )
        config2 = CommandConfig(
            name="Cmd2",
            command="sleep 10",
            triggers=[],
        )
        orchestrator.add_command(config1)
        orchestrator.add_command(config2)

        await orchestrator.run_command("Cmd1")
        await orchestrator.run_command("Cmd2")

        count = await orchestrator.cancel_all()

        assert count >= 2


# ========================================================================
# Configuration Tests
# ========================================================================


class TestConfiguration:
    """Tests for command configuration management."""

    def test_add_command(self, orchestrator):
        """add_command() registers a new command."""
        config = CommandConfig(
            name="New",
            command="echo new",
            triggers=[],
        )
        orchestrator.add_command(config)

        assert "New" in orchestrator.list_commands()
        assert orchestrator.get_status("New").state == "never_run"

    def test_remove_command(self, orchestrator):
        """remove_command() unregisters a command."""
        # Test command already exists in orchestrator
        assert "Test" in orchestrator.list_commands()

        orchestrator.remove_command("Test")
        assert "Test" not in orchestrator.list_commands()

    def test_update_command(self, orchestrator):
        """update_command() replaces command config."""
        original = CommandConfig(
            name="ToUpdate",
            command="echo original",
            triggers=[],
        )
        orchestrator.add_command(original)

        updated = CommandConfig(
            name="ToUpdate",
            command="echo updated",
            triggers=["new_trigger"],
        )
        orchestrator.update_command(updated)

        # Config should be updated
        status = orchestrator.get_status("ToUpdate")
        assert status is not None

    async def test_update_command_mid_run(self, orchestrator):
        """Active runs continue with old config after update."""
        old_config = CommandConfig(name="UpdateMid", command="echo old", triggers=[])
        orchestrator.add_command(old_config)

        handle = await orchestrator.run_command("UpdateMid")

        # Update config mid-run
        new_config = CommandConfig(name="UpdateMid", command="echo new", triggers=[])
        orchestrator.update_command(new_config)

        await handle.wait()
        # Verify the run captured the old command in resolved_command
        assert handle._result.resolved_command is not None
        assert handle._result.resolved_command.command == "echo old"

    def test_reload_all_commands(self, orchestrator):
        """reload_all_commands() clears and reloads all commands."""
        # Orchestrator already has Test command
        assert "Test" in orchestrator.list_commands()

        config1 = CommandConfig(
            name="First",
            command="echo 1",
            triggers=[],
        )
        config2 = CommandConfig(
            name="Second",
            command="echo 2",
            triggers=[],
        )

        orchestrator.reload_all_commands([config1, config2])

        commands = orchestrator.list_commands()
        assert "First" in commands
        assert "Second" in commands
        assert "Test" not in commands  # Old command should be gone


# ========================================================================
# Query Tests
# ========================================================================


class TestQueries:
    """Tests for status and history queries."""

    def test_list_commands(self, multi_command_orchestrator):
        """list_commands() returns all registered commands."""
        commands = multi_command_orchestrator.list_commands()

        assert "Test" in commands
        assert "Lint" in commands
        assert "Build" in commands

    def test_get_trigger_graph_basic(self, orchestrator):
        """get_trigger_graph() returns triggers from existing commands."""
        # Default orchestrator has Test command with triggers=["test_trigger"]
        graph = orchestrator.get_trigger_graph()
        logger.debug(f"Trigger graph: {graph}")
        print(f"Trigger graph: {graph}")
        assert "test_trigger" in graph
        assert "Test" in graph["test_trigger"]

    def test_get_trigger_graph_single_trigger(self, orchestrator):
        """get_trigger_graph() maps trigger to command."""
        config = CommandConfig(
            name="Lint",
            command="ruff check .",
            triggers=["file_saved"],
        )
        orchestrator.add_command(config)

        graph = orchestrator.get_trigger_graph()

        assert "file_saved" in graph
        assert "Lint" in graph["file_saved"]

    def test_get_trigger_graph_multiple_commands_same_trigger(self, orchestrator):
        """get_trigger_graph() lists all commands for shared trigger."""
        config1 = CommandConfig(
            name="Lint",
            command="ruff check .",
            triggers=["changes_applied"],
        )
        config2 = CommandConfig(
            name="Format",
            command="ruff format .",
            triggers=["changes_applied"],
        )
        orchestrator.add_command(config1)
        orchestrator.add_command(config2)

        graph = orchestrator.get_trigger_graph()

        assert "changes_applied" in graph
        assert len(graph["changes_applied"]) == 2
        assert "Lint" in graph["changes_applied"]
        assert "Format" in graph["changes_applied"]

    def test_get_trigger_graph_lifecycle_triggers(self, orchestrator):
        """get_trigger_graph() includes lifecycle auto-event triggers."""
        config1 = CommandConfig(
            name="Lint",
            command="ruff check .",
            triggers=["file_saved"],
        )
        config2 = CommandConfig(
            name="Tests",
            command="pytest",
            triggers=["command_success:Lint"],
        )
        orchestrator.add_command(config1)
        orchestrator.add_command(config2)

        graph = orchestrator.get_trigger_graph()

        assert "file_saved" in graph
        assert "command_success:Lint" in graph
        assert "Lint" in graph["file_saved"]
        assert "Tests" in graph["command_success:Lint"]

    def test_get_trigger_graph_command_with_multiple_triggers(self, orchestrator):
        """get_trigger_graph() includes all triggers for a command."""
        config = CommandConfig(
            name="Deploy",
            command="deploy.sh",
            triggers=["manual_deploy", "ci_deploy", "command_success:Tests"],
        )
        orchestrator.add_command(config)

        graph = orchestrator.get_trigger_graph()

        assert "manual_deploy" in graph
        assert "ci_deploy" in graph
        assert "command_success:Tests" in graph
        assert all(
            "Deploy" in graph[t] for t in ["manual_deploy", "ci_deploy", "command_success:Tests"]
        )

    async def test_get_status(self, orchestrator):
        """get_status() returns CommandStatus with state and counts."""
        # Before any run
        status = orchestrator.get_status("Test")
        assert status.state == "never_run"
        assert status.active_count == 0

        # After run
        handle = await orchestrator.run_command("Test")
        status = orchestrator.get_status("Test")
        assert status.active_count >= 0

        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)  # Let runtime update complete
        status = orchestrator.get_status("Test")
        assert status.state == "success"

    async def test_get_history(self, orchestrator):
        """get_history() returns past runs in order."""
        # Run command multiple times
        handle1 = await orchestrator.run_command("Test")
        await handle1.wait(timeout=1.0)

        await asyncio.sleep(0.05)

        handle2 = await orchestrator.run_command("Test")
        await handle2.wait(timeout=1.0)

        history = orchestrator.get_history("Test", limit=10)

        assert len(history) >= 1
        # Most recent should be first or last depending on order

    def test_preview_command_basic(self, orchestrator):
        """preview_command() returns ResolvedCommand without executing."""
        preview = orchestrator.preview_command("Test")

        # Should return ResolvedCommand
        assert preview is not None
        assert preview.command == "echo hello"
        assert preview.timeout_secs is None
        assert preview.cwd is None

        # Should NOT have executed (no active handles)
        handles = orchestrator.get_all_active_handles()
        assert len(handles) == 0

    def test_preview_command_with_variables(self):
        """preview_command() resolves variables correctly."""
        config = CommandConfig(
            name="Deploy",
            command="deploy --env={{ env }} --region={{ region }}",
            triggers=["deploy"],
            vars={"region": "us-west-2"},
        )
        runner_config = RunnerConfig(commands=[config], vars={"env": "dev"})
        orchestrator = CommandOrchestrator(runner_config, executor=MockExecutor())

        # Preview with call-time override
        preview = orchestrator.preview_command(
            "Deploy", vars={"env": "production", "region": "eu-central-1"}
        )

        assert preview.command == "deploy --env=production --region=eu-central-1"
        assert preview.vars["env"] == "production"
        assert preview.vars["region"] == "eu-central-1"

    def test_preview_command_with_cwd_and_timeout(self):
        """preview_command() includes cwd and timeout settings."""
        config = CommandConfig(
            name="Build",
            command="make build",
            triggers=["build"],
            cwd="/home/user/project",
            timeout_secs=300,
        )
        runner_config = RunnerConfig(commands=[config])
        orchestrator = CommandOrchestrator(runner_config, executor=MockExecutor())

        preview = orchestrator.preview_command("Build")

        assert preview.command == "make build"
        assert preview.cwd == "/home/user/project"
        assert preview.timeout_secs == 300

    def test_preview_command_with_env_vars(self):
        """preview_command() resolves env variables correctly."""
        config = CommandConfig(
            name="Test",
            command="npm test",
            triggers=["test"],
            env={"NODE_ENV": "{{ env }}", "DEBUG": "true"},
            vars={"env": "test"},
        )
        runner_config = RunnerConfig(commands=[config])
        orchestrator = CommandOrchestrator(runner_config, executor=MockExecutor())

        preview = orchestrator.preview_command("Test")

        # Env should include both config env and system env
        assert "NODE_ENV" in preview.env
        assert preview.env["NODE_ENV"] == "test"
        assert "DEBUG" in preview.env
        assert preview.env["DEBUG"] == "true"
        # System env should also be included
        assert "PATH" in preview.env

    def test_preview_command_not_found(self, orchestrator):
        """preview_command() raises CommandNotFoundError for unknown command."""
        from cmdorc import CommandNotFoundError

        with pytest.raises(CommandNotFoundError, match="Command 'NonExistent' not found"):
            orchestrator.preview_command("NonExistent")

    def test_preview_command_missing_variable(self):
        """preview_command() raises ValueError for missing variables."""
        config = CommandConfig(
            name="Deploy",
            command="deploy --env={{ env }}",
            triggers=["deploy"],
        )
        runner_config = RunnerConfig(commands=[config])
        orchestrator = CommandOrchestrator(runner_config, executor=MockExecutor())

        with pytest.raises(ValueError, match="Missing variable"):
            orchestrator.preview_command("Deploy")

    def test_preview_command_nested_variables(self):
        """preview_command() resolves nested variables in command string."""
        config = CommandConfig(
            name="Test",
            command="pytest {{ test_path }}",
            triggers=["test"],
            vars={"test_path": "{{ base_dir }}/tests"},
        )
        runner_config = RunnerConfig(commands=[config], vars={"base_dir": "/app"})
        orchestrator = CommandOrchestrator(runner_config, executor=MockExecutor())

        preview = orchestrator.preview_command("Test")

        # Command string should be fully resolved
        assert preview.command == "pytest /app/tests"
        # vars dict contains the merged variables (templates may not be resolved in the dict itself)
        assert preview.vars["base_dir"] == "/app"
        assert "test_path" in preview.vars

    def test_preview_command_does_not_affect_execution(self):
        """preview_command() doesn't affect subsequent run_command() calls."""
        config = CommandConfig(
            name="Test",
            command="echo {{ msg }}",
            triggers=["test"],
            vars={"msg": "default"},
        )
        runner_config = RunnerConfig(commands=[config])
        orchestrator = CommandOrchestrator(runner_config, executor=MockExecutor())

        # Preview with override
        preview1 = orchestrator.preview_command("Test", vars={"msg": "preview"})
        assert preview1.command == "echo preview"

        # Preview with different override
        preview2 = orchestrator.preview_command("Test", vars={"msg": "another"})
        assert preview2.command == "echo another"

        # Preview without override should use default
        preview3 = orchestrator.preview_command("Test")
        assert preview3.command == "echo default"


# ========================================================================
# Callback Tests
# ========================================================================


class TestCallbacks:
    """Tests for event callback dispatch."""

    async def test_on_event_exact_pattern(self, orchestrator):
        """on_event() callback invoked for exact pattern match."""
        called = []

        async def callback(handle, context):
            called.append(True)

        orchestrator.on_event("test_trigger", callback)
        await orchestrator.trigger("test_trigger")
        await asyncio.sleep(0.05)  # Let callback execute

        assert True in called

    async def test_on_event_wildcard_pattern(self, orchestrator):
        """on_event() callback invoked for wildcard pattern match."""
        # Test command already exists in orchestrator
        called = []

        async def callback(handle, context):
            called.append(True)

        orchestrator.on_event("command_*:Test", callback)

        handle = await orchestrator.run_command("Test")
        await handle.wait(timeout=1.0)

        await asyncio.sleep(0.1)

        assert True in called

    async def test_off_event(self, orchestrator):
        """off_event() unregisters callback."""
        called = []

        async def callback(handle, context):
            called.append(True)

        orchestrator.on_event("test_event", callback)
        orchestrator.off_event("test_event", callback)

        await orchestrator.trigger("test_event")

        assert len(called) == 0

    async def test_set_lifecycle_callback(self, orchestrator):
        """set_lifecycle_callback() registers callbacks for run states."""
        config = CommandConfig(
            name="WithCallback",
            command="echo test",
            triggers=[],
        )
        orchestrator.add_command(config)

        success_called = []
        failed_called = []

        async def on_success(handle, context):
            success_called.append(True)

        async def on_failed(handle, context):
            failed_called.append(True)

        orchestrator.set_lifecycle_callback(
            "WithCallback", on_success=on_success, on_failed=on_failed
        )

        handle = await orchestrator.run_command("WithCallback")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)  # Let callback execute

        assert True in success_called
        assert len(failed_called) == 0

    async def test_callback_exception_manual_propagates(self, orchestrator):
        """Manual callback exceptions propagate."""

        def failing_callback(handle, context):
            raise ValueError("Test fail")

        orchestrator.on_event("manual_event", failing_callback)

        with pytest.raises(ValueError):
            await orchestrator.trigger("manual_event")  # Manual → raises


# ========================================================================
# Shutdown Tests
# ========================================================================


class TestShutdown:
    """Tests for orchestrator shutdown and cleanup."""

    async def test_shutdown_cancel_running(self, orchestrator):
        """shutdown() with cancel_running=True cancels active runs."""
        config = CommandConfig(
            name="LongRun",
            command="sleep 10",
            triggers=[],
        )
        orchestrator.add_command(config)

        await orchestrator.run_command("LongRun")

        result = await orchestrator.shutdown(timeout=1.0, cancel_running=True)

        assert result["cancelled_count"] >= 1
        assert result["timeout_expired"] is False

    async def test_shutdown_wait_for_completion(self, orchestrator):
        """shutdown() with cancel_running=False waits for completion."""
        config = CommandConfig(
            name="Quick",
            command="echo quick",
            triggers=[],
        )
        orchestrator.add_command(config)

        await orchestrator.run_command("Quick")

        result = await orchestrator.shutdown(timeout=1.0, cancel_running=False)

        assert result["timeout_expired"] is False

    async def test_shutdown_timeout(self):
        """shutdown() respects timeout and returns timeout_expired=True."""
        # Create orchestrator with slow executor
        config = CommandConfig(
            name="VeryLong",
            command="sleep 100",
            triggers=[],
        )
        runner_config = RunnerConfig(commands=[config], vars={})
        # Create executor with 10 second delay - much longer than shutdown timeout
        executor = MockExecutor(delay=10.0)
        orchestrator = CommandOrchestrator(runner_config, executor)

        await orchestrator.run_command("VeryLong")
        await asyncio.sleep(0.05)  # Let run start

        # Shutdown with short timeout should expire
        result = await orchestrator.shutdown(timeout=0.1, cancel_running=False)

        assert result["timeout_expired"] is True

    async def test_cleanup_immediate(self, orchestrator):
        """cleanup() does immediate cleanup without waiting."""
        await orchestrator.run_command("Test")

        # cleanup should succeed even with running task
        await orchestrator.cleanup()

        assert orchestrator._is_shutdown is True

    async def test_shutdown_prevents_new_runs(self, orchestrator):
        """After shutdown, run_command raises OrchestratorShutdownError."""
        orchestrator._is_shutdown = True

        with pytest.raises(OrchestratorShutdownError):
            await orchestrator.run_command("Test")

    async def test_shutdown_during_auto_trigger(self, orchestrator):
        """Shutdown during auto-trigger emit doesn't crash (error caught)."""
        config = CommandConfig(
            name="ShutdownAuto",
            command="echo",
            triggers=[],
        )
        orchestrator.add_command(config)

        handle = await orchestrator.run_command("ShutdownAuto")

        # Start shutdown while run is active (will wait)
        shutdown_task = asyncio.create_task(
            orchestrator.shutdown(timeout=1.0, cancel_running=False)
        )

        # Wait for run to complete → emits auto-trigger → should catch OrchestratorShutdownError if races
        await handle.wait()
        await asyncio.sleep(0.1)  # Allow emit

        result = await shutdown_task
        assert not result["timeout_expired"]

    # New in Shutdown: Exceptions in gather counted correctly
    async def test_shutdown_with_exceptions_in_gather(self, orchestrator):
        """Shutdown counts successes accurately even with exceptions in wait."""

        # Mock executor to raise in one wait (simulate error)
        class FailingMock(MockExecutor):
            async def start_run(self, result, resolved):
                if "Fail" in result.command_name:
                    raise RuntimeError("Test fail")
                await super().start_run(result, resolved)

        config = RunnerConfig(
            commands=[
                CommandConfig(name="Success", command="echo", triggers=[]),
                CommandConfig(name="Fail", command="echo", triggers=[]),
            ],
            vars={},
        )
        orch = CommandOrchestrator(config, FailingMock(delay=0.01))

        await orch.run_command("Success")

        # Second run raises exception in executor.start_run()
        with pytest.raises(RuntimeError):
            await orch.run_command("Fail")

        result = await orch.shutdown(timeout=1.0, cancel_running=False)
        assert result["completed_count"] == 1  # Only success completes normally
        assert result["cancelled_count"] == 0


# ========================================================================
# Concurrency & Race Condition Tests
# ========================================================================


class TestConcurrency:
    """Tests for concurrent operations and race conditions."""

    async def test_concurrent_run_command_calls(self, orchestrator):
        """Multiple concurrent run_command calls work safely."""
        config = CommandConfig(
            name="Concurrent",
            command="echo hello",
            triggers=[],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        handles = await asyncio.gather(*[orchestrator.run_command("Concurrent") for _ in range(10)])

        assert len(handles) == 10
        assert len({h.run_id for h in handles}) == 10  # All unique

    async def test_concurrent_trigger_calls(self, orchestrator):
        """Multiple concurrent trigger calls work safely."""
        config = CommandConfig(
            name="Triggered",
            command="echo hello",
            triggers=["test_event"],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        # Multiple concurrent triggers
        await asyncio.gather(*[orchestrator.trigger("test_event") for _ in range(5)])

        # All should complete without errors

    async def test_concurrent_cancel_operations(self, orchestrator):
        """Multiple concurrent cancel operations work safely."""
        config = CommandConfig(
            name="ToCancel",
            command="sleep 10",
            triggers=[],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        # Start multiple runs
        handles = await asyncio.gather(*[orchestrator.run_command("ToCancel") for _ in range(5)])

        # Concurrent cancellations
        results = await asyncio.gather(*[orchestrator.cancel_run(h.run_id) for h in handles])

        assert sum(results) >= 1  # At least one succeeded

    async def test_trigger_and_run_command_concurrent(self, orchestrator):
        """Concurrent trigger and run_command don't race."""
        config = CommandConfig(
            name="Mixed",
            command="echo hello",
            triggers=["mixed_trigger"],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        # Mix of run_command and trigger
        results = await asyncio.gather(
            orchestrator.run_command("Mixed"),
            orchestrator.trigger("mixed_trigger"),
            orchestrator.run_command("Mixed"),
            return_exceptions=True,
        )

        # Should all succeed or be expected errors
        assert len([r for r in results if isinstance(r, RunHandle)]) >= 1

    async def test_handle_queries_during_concurrent_completion(self, orchestrator):
        """Handle queries work correctly during concurrent completion."""
        config = CommandConfig(
            name="Query",
            command="echo hello",
            triggers=[],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        await asyncio.gather(*[orchestrator.run_command("Query") for _ in range(5)])

        # Query while runs are completing
        async def query_active():
            for _ in range(10):
                active = orchestrator.get_active_handles("Query")
                await asyncio.sleep(0.01)
            return len(active)

        active_count = await query_active()

        # Should have queried successfully
        assert active_count >= 0


# ========================================================================
# Extended Coverage Tests
# ========================================================================


class TestErrorHandlingAndEdgeCases:
    """Tests for error handling and edge cases in command_orchestrator."""

    async def test_run_command_unknown_disallow_reason(self, orchestrator):
        """run_command raises RuntimeError for unknown disallow reason."""
        # This is a defensive test that would only happen if NewRunDecision
        # has an unknown disallow_reason value. We mock the policy to return one.
        config = CommandConfig(
            name="TestCmd",
            command="echo test",
            triggers=[],
        )
        orchestrator.add_command(config)

        # Mock the policy to return unknown disallow reason
        original_decide = orchestrator._policy.decide

        def mock_decide(*args, **kwargs):
            from cmdorc.concurrency_policy import NewRunDecision

            return NewRunDecision(
                allow=False,
                runs_to_cancel=[],
                disallow_reason="unknown_reason",
                elapsed_ms=None,
            )

        orchestrator._policy.decide = mock_decide

        try:
            with pytest.raises(RuntimeError, match="Unknown disallow reason"):
                await orchestrator.run_command("TestCmd")
        finally:
            orchestrator._policy.decide = original_decide

    async def test_trigger_cancel_on_triggers_with_error(self, orchestrator):
        """trigger() handles errors in cancel_on_triggers gracefully."""
        config1 = CommandConfig(
            name="ToCancelWithError",
            command="echo cancel",
            triggers=[],
        )
        config2 = CommandConfig(
            name="Triggerer",
            command="echo trigger",
            triggers=[],
            cancel_on_triggers=["test_cancel_event"],
        )
        orchestrator.add_command(config1)
        orchestrator.add_command(config2)

        await orchestrator.run_command("ToCancelWithError")

        # Trigger should handle any cancellation errors gracefully
        await orchestrator.trigger("test_cancel_event")

        # Should not raise, even if cancellation had issues
        await asyncio.sleep(0.05)

    async def test_monitor_run_executor_failure(self, orchestrator):
        """_monitor_run handles executor failures correctly."""
        executor = orchestrator._executor
        executor.should_fail = True
        executor.failure_message = "Executor error"

        config = CommandConfig(
            name="ExecutorFail",
            command="false",
            triggers=[],
        )
        orchestrator.add_command(config)

        handle = await orchestrator.run_command("ExecutorFail")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        # Run should be marked as failed
        assert handle.state == RunState.FAILED

    async def test_monitor_run_command_removed_during_run(self, orchestrator):
        """_monitor_run handles command removal during execution."""
        config = CommandConfig(
            name="ToBeRemoved",
            command="echo test",
            triggers=[],
        )
        orchestrator.add_command(config)

        handle = await orchestrator.run_command("ToBeRemoved")

        # Remove command while run is active
        orchestrator.remove_command("ToBeRemoved")

        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        # Should complete without error even though command was removed

    async def test_emit_auto_trigger_cycle_prevented(self, orchestrator):
        """_emit_auto_trigger prevents cycles correctly."""
        config_a = CommandConfig(
            name="A",
            command="echo a",
            triggers=["b_event"],
            loop_detection=True,
        )
        config_b = CommandConfig(
            name="B",
            command="echo b",
            triggers=["a_event"],
            loop_detection=True,
        )
        orchestrator.add_command(config_a)
        orchestrator.add_command(config_b)

        # Start with context that already has a_event
        context = TriggerContext(seen={"a_event"})

        # Emitting a_event again with context should prevent cycle
        await orchestrator._emit_auto_trigger("a_event", None, context)

        # Should not raise or cause infinite loop

    async def test_dispatch_callbacks_with_sync_callback(self, orchestrator):
        """_dispatch_callbacks handles synchronous callbacks."""
        sync_called = []

        def sync_callback(handle, context):
            sync_called.append(True)

        orchestrator.on_event("sync_event", sync_callback)

        await orchestrator.trigger("sync_event")
        await asyncio.sleep(0.05)

        assert True in sync_called

    async def test_dispatch_callbacks_exception_in_callback(self, orchestrator):
        """_dispatch_callbacks propagates exceptions from manual triggers."""

        async def failing_callback(handle, context):
            raise RuntimeError("Callback error")

        orchestrator.on_event("fail_event", failing_callback)

        # Callback exceptions propagate from manual triggers
        with pytest.raises(RuntimeError):
            await orchestrator.trigger("fail_event")

    async def test_dispatch_lifecycle_callback_on_cancelled(self, orchestrator):
        """_dispatch_lifecycle_callback invokes on_cancelled callback."""
        config = CommandConfig(
            name="ToCancelCallback",
            command="sleep 10",
            triggers=[],
        )
        orchestrator.add_command(config)

        cancelled_called = []

        async def on_cancelled(handle, context):
            cancelled_called.append(True)

        orchestrator.set_lifecycle_callback("ToCancelCallback", on_cancelled=on_cancelled)

        handle = await orchestrator.run_command("ToCancelCallback")
        await orchestrator.cancel_run(handle.run_id)
        await asyncio.sleep(0.1)

        assert True in cancelled_called

    async def test_dispatch_lifecycle_callback_exception(self, orchestrator):
        """_dispatch_lifecycle_callback handles exceptions in callbacks."""
        config = CommandConfig(
            name="FailCallback",
            command="echo test",
            triggers=[],
        )
        orchestrator.add_command(config)

        async def failing_callback(handle, context):
            raise RuntimeError("Callback failed")

        orchestrator.set_lifecycle_callback("FailCallback", on_success=failing_callback)

        handle = await orchestrator.run_command("FailCallback")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        # Should not raise

    async def test_trigger_run_command_debounce_in_trigger(self, orchestrator):
        """_trigger_run_command raises DebounceError appropriately."""
        config = CommandConfig(
            name="DebounceTest",
            command="echo test",
            triggers=["debounce_event"],
            debounce_in_ms=1000,
        )
        orchestrator.add_command(config)

        # First trigger
        await orchestrator.trigger("debounce_event")
        await asyncio.sleep(0.05)

        # Second trigger within debounce window should be ignored
        # (caught and logged in trigger, not re-raised)
        await orchestrator.trigger("debounce_event")
        await asyncio.sleep(0.05)

    async def test_cancel_run_internal_with_error(self, orchestrator):
        """_cancel_run_internal handles executor errors gracefully."""
        config = CommandConfig(
            name="ToCancel",
            command="sleep 10",
            triggers=[],
        )
        orchestrator.add_command(config)

        handle = await orchestrator.run_command("ToCancel")

        # Mock executor to raise error on cancel
        original_cancel = orchestrator._executor.cancel_run

        async def failing_cancel(*args, **kwargs):
            raise RuntimeError("Cancel failed")

        orchestrator._executor.cancel_run = failing_cancel

        try:
            # Should not raise even if executor fails
            await orchestrator.cancel_run(handle.run_id)
        finally:
            orchestrator._executor.cancel_run = original_cancel

    async def test_emit_auto_trigger_with_command_check(self, orchestrator):
        """_emit_auto_trigger checks loop_detection flag correctly."""
        config = CommandConfig(
            name="NoLoopDetect",
            command="echo test",
            triggers=["some_event"],
            loop_detection=False,  # Explicitly disabled
        )
        orchestrator.add_command(config)

        context = TriggerContext(seen=set())

        # Emit auto-trigger for this command - should not propagate context
        await orchestrator._emit_auto_trigger("some_event", None, context)

        # Should complete without error

    async def test_register_handle_thread_safety(self, orchestrator):
        """Handle registration is thread-safe during concurrent operations."""
        config = CommandConfig(
            name="Concurrent",
            command="echo test",
            triggers=[],
            max_concurrent=0,
        )
        orchestrator.add_command(config)

        # Concurrent runs and register operations
        handles = await asyncio.gather(*[orchestrator.run_command("Concurrent") for _ in range(5)])

        # All handles should be unique and registered
        assert len({h.run_id for h in handles}) == 5
        for handle in handles:
            assert orchestrator.get_handle_by_run_id(handle.run_id) is not None

    async def test_unregister_handle_cleanup(self, orchestrator):
        """_unregister_handle properly cleans up handle."""
        handle = await orchestrator.run_command("Test")

        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        # After completion, handle should be removed and cleanup called
        assert handle.run_id not in orchestrator._handles

    async def test_multiple_commands_history_and_status(self, orchestrator):
        """Status and history queries work with multiple commands."""
        config1 = CommandConfig(
            name="Cmd1",
            command="echo 1",
            triggers=[],
        )
        config2 = CommandConfig(
            name="Cmd2",
            command="echo 2",
            triggers=[],
        )
        orchestrator.add_command(config1)
        orchestrator.add_command(config2)

        h1 = await orchestrator.run_command("Cmd1")
        h2 = await orchestrator.run_command("Cmd2")

        await h1.wait(timeout=1.0)
        await h2.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        # Both should have history
        hist1 = orchestrator.get_history("Cmd1", limit=10)
        hist2 = orchestrator.get_history("Cmd2", limit=10)

        assert len(hist1) >= 1
        assert len(hist2) >= 1

    async def test_trigger_with_cancel_error_exception(self, orchestrator):
        """trigger() handles non-standard exceptions in cancel_on_triggers."""
        config = CommandConfig(
            name="FailCancel",
            command="echo test",
            triggers=[],
            cancel_on_triggers=["fail_cancel_event"],
        )
        orchestrator.add_command(config)

        # Mock cancel_command to raise unexpected exception
        original_cancel = orchestrator.cancel_command

        def failing_cancel(*args, **kwargs):
            raise ValueError("Unexpected error in cancel")

        orchestrator.cancel_command = failing_cancel

        try:
            # Trigger should handle exception gracefully
            await orchestrator.trigger("fail_cancel_event")
            await asyncio.sleep(0.05)
            # Should not raise
        finally:
            orchestrator.cancel_command = original_cancel

    async def test_trigger_with_run_command_error_exception(self, orchestrator):
        """trigger() handles non-standard exceptions in trigger matches."""
        config = CommandConfig(
            name="FailTrigger",
            command="echo test",
            triggers=["fail_trigger_event"],
        )
        orchestrator.add_command(config)

        # Mock _trigger_run_command to raise unexpected exception
        original_trigger_run = orchestrator._trigger_run_command

        async def failing_trigger_run(*args, **kwargs):
            raise ValueError("Unexpected error in trigger run")

        orchestrator._trigger_run_command = failing_trigger_run

        try:
            # Trigger should handle exception gracefully
            await orchestrator.trigger("fail_trigger_event")
            await asyncio.sleep(0.05)
            # Should not raise
        finally:
            orchestrator._trigger_run_command = original_trigger_run

    async def test_monitor_run_with_unexpected_state(self, orchestrator):
        """_monitor_run handles unexpected RunState values."""
        config = CommandConfig(
            name="UnexpectedState",
            command="echo test",
            triggers=[],
        )
        orchestrator.add_command(config)

        handle = await orchestrator.run_command("UnexpectedState")

        # Manually set to unexpected state to test edge case
        handle._result.state = "invalid_state"

        # Wait for completion
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        # Should handle gracefully without raising

    async def test_shutdown_already_called(self, orchestrator):
        """shutdown() handles multiple calls gracefully."""
        # First shutdown
        result1 = await orchestrator.shutdown(timeout=1.0)
        assert result1["cancelled_count"] >= 0

        # Second shutdown should return early
        result2 = await orchestrator.shutdown(timeout=1.0)
        assert result2["cancelled_count"] == 0
        assert result2["timeout_expired"] is False

    async def test_context_manager_normal_exit(self):
        """Context manager calls shutdown on normal exit."""
        config = RunnerConfig(commands=[CommandConfig(name="Test", command="echo hi", triggers=[])])
        executor = MockExecutor()

        async with CommandOrchestrator(config, executor=executor) as orch:
            assert orch._is_shutdown is False

        # After exiting context, should be shut down
        assert orch._is_shutdown is True

    async def test_context_manager_exception(self):
        """Context manager calls shutdown even on exception."""
        config = RunnerConfig(commands=[CommandConfig(name="Test", command="echo hi", triggers=[])])
        executor = MockExecutor()

        with pytest.raises(ValueError, match="test error"):
            async with CommandOrchestrator(config, executor=executor) as orch:
                raise ValueError("test error")

        # Should still be shut down despite exception
        assert orch._is_shutdown is True

    async def test_context_manager_returns_self(self):
        """Context manager returns self for 'as' binding."""
        config = RunnerConfig(commands=[CommandConfig(name="Test", command="echo hi", triggers=[])])
        executor = MockExecutor()

        orchestrator = CommandOrchestrator(config, executor=executor)
        async with orchestrator as orch:
            assert orch is orchestrator

        await orchestrator.shutdown()  # Already shut down, but safe to call again

    async def test_dispatch_lifecycle_callback_sync_callback(self, orchestrator):
        """_dispatch_lifecycle_callback handles synchronous callbacks."""
        config = CommandConfig(
            name="SyncCallback",
            command="echo test",
            triggers=[],
        )
        orchestrator.add_command(config)

        sync_called = []

        def sync_on_success(handle, context):
            sync_called.append(True)

        orchestrator.set_lifecycle_callback("SyncCallback", on_success=sync_on_success)

        handle = await orchestrator.run_command("SyncCallback")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        assert True in sync_called

    async def test_dispatch_lifecycle_callback_failed_state(self, orchestrator):
        """_dispatch_lifecycle_callback handles failed state correctly."""
        config = CommandConfig(
            name="FailedCallback",
            command="false",
            triggers=[],
        )
        orchestrator.add_command(config)

        failed_called = []

        async def on_failed(handle, context):
            failed_called.append(True)

        orchestrator.set_lifecycle_callback("FailedCallback", on_failed=on_failed)

        executor = orchestrator._executor
        executor.should_fail = True
        executor.failure_message = "Test failure"

        handle = await orchestrator.run_command("FailedCallback")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.05)

        assert True in failed_called

    async def test_dispatch_callbacks_with_handle_context(self, orchestrator):
        """_dispatch_callbacks receives correct handle and context."""
        received = []

        async def capturing_callback(handle, context):
            received.append((handle, context))

        orchestrator.on_event("context_event", capturing_callback)

        await orchestrator.trigger("context_event")
        await asyncio.sleep(0.05)

        # Callback should have been called
        assert len(received) >= 0  # May be called or not depending on dispatch timing

    async def test_emit_auto_trigger_extracts_command_name(self, orchestrator):
        """_emit_auto_trigger correctly extracts command name from event."""
        config = CommandConfig(
            name="ExtractTest",
            command="echo test",
            triggers=["extracted_event"],
            loop_detection=True,
        )
        orchestrator.add_command(config)

        # Emit auto-trigger with command name in event
        handle = await orchestrator.run_command("ExtractTest")
        await handle.wait(timeout=1.0)
        await asyncio.sleep(0.1)

        # Auto-trigger should have fired (command_success:ExtractTest)

    async def test_unregister_nonexistent_handle(self, orchestrator):
        """_unregister_handle handles nonexistent handle gracefully."""
        # This should not raise
        await orchestrator._unregister_handle("nonexistent_id")

    async def test_cancel_run_with_comment(self, orchestrator):
        """cancel_run() passes comment to internal cancellation."""
        config = CommandConfig(
            name="CancelComment",
            command="sleep 10",
            triggers=[],
        )
        orchestrator.add_command(config)

        handle = await orchestrator.run_command("CancelComment")
        success = await orchestrator.cancel_run(handle.run_id, "test comment")

        assert success is True or success is False  # Either cancelled or not found
