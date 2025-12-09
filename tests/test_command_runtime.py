# tests/test_command_runtime.py
"""
Comprehensive test suite for CommandRuntime.

Tests all state management operations:
- Config registration/removal/replacement
- Active run tracking
- History management
- Debounce tracking
- Status queries
"""

import logging
import time

import pytest

from cmdorc import CommandConfig, CommandRuntime, RunResult, CommandNotFoundError

logging.getLogger("cmdorc").setLevel(logging.DEBUG)

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture
def runtime():
    """Fresh CommandRuntime instance."""
    return CommandRuntime()


@pytest.fixture
def simple_config():
    """Simple command config with defaults."""
    return CommandConfig(
        name=simple_config.name,
        command="echo hello",
        triggers=["test_trigger"],
    )


@pytest.fixture
def config_with_history():
    """Command with history tracking."""
    return CommandConfig(
        name=config_with_history.name,
        command="echo history",
        triggers=["trigger"],
        keep_history=5,
    )


@pytest.fixture
def config_no_history():
    """Command with history disabled."""
    return CommandConfig(
        name=config_no_history.name,
        command="echo no_history",
        triggers=["trigger"],
        keep_history=0,
    )


@pytest.fixture
def sample_run(simple_config):
    """Sample RunResult for testing."""
    return RunResult(
        command_name=simple_config.name,
        run_id="test-run-123",
        trigger_event="test_trigger",
    )


# ================================================================
# Configuration Management Tests
# ================================================================


def test_register_command(runtime, simple_config):
    """Test basic command registration."""
    runtime.register_command(simple_config)

    assert simple_config.name in runtime.list_commands()
    assert runtime.get_command(simple_config.name) == simple_config


def test_is_registered(runtime, simple_config):
    """Test is_registered method."""
    assert not runtime.is_registered(simple_config.name)

    runtime.register_command(simple_config)
    assert runtime.is_registered(simple_config.name)


def test_register_duplicate_raises(runtime, simple_config):
    """Test that registering duplicate command raises ValueError."""
    runtime.register_command(simple_config)

    with pytest.raises(ValueError, match="already registered"):
        runtime.register_command(simple_config)


def test_remove_command(runtime, simple_config):
    """Test command removal."""
    runtime.register_command(simple_config)
    runtime.remove_command(simple_config.name)

    assert simple_config.name not in runtime.list_commands()
    assert runtime.get_command(simple_config.name) is None


def test_remove_nonexistent_raises(runtime):
    """Test that removing non-existent command raises CommandNotFoundError."""
    with pytest.raises(CommandNotFoundError, match="not found"):
        runtime.remove_command("nonexistent")


def test_replace_command(runtime):
    """Test command configuration replacement."""
    config1 = CommandConfig(
        name="replace_test",
        command="echo v1",
        triggers=["trigger1"],
        keep_history=1,
    )
    config2 = CommandConfig(
        name="replace_test",
        command="echo v2",
        triggers=["trigger2"],
        keep_history=3,
    )

    runtime.register_command(config1)
    runtime.replace_command(config2)

    retrieved = runtime.get_command("replace_test")
    assert retrieved.command == "echo v2"
    assert retrieved.triggers == ["trigger2"]
    assert retrieved.keep_history == 3


def test_replace_nonexistent_raises(runtime, simple_config):
    """Test that replacing non-existent command raises KeyError."""
    with pytest.raises(CommandNotFoundError, match="not registered"):
        runtime.replace_command(simple_config)


def test_list_commands(runtime):
    """Test listing all registered commands."""
    configs = [
        CommandConfig(name="cmd1", command="echo 1", triggers=["t1"]),
        CommandConfig(name="cmd2", command="echo 2", triggers=["t2"]),
        CommandConfig(name="cmd3", command="echo 3", triggers=["t3"]),
    ]

    for config in configs:
        runtime.register_command(config)

    names = runtime.list_commands()
    assert len(names) == 3
    assert names == ["cmd1", "cmd2", "cmd3"]


# ================================================================
# Active Run Tracking Tests
# ================================================================


def test_add_live_run(runtime, simple_config, sample_run):
    """Test adding a run to active tracking."""
    runtime.register_command(simple_config)
    runtime.add_live_run(sample_run)

    active = runtime.get_active_runs(simple_config.name)
    assert len(active) == 1
    assert active[0] is sample_run


def test_add_live_run_unregistered_raises(runtime, sample_run):
    """Test that adding run for unregistered command raises KeyError."""
    with pytest.raises(CommandNotFoundError, match="not registered"):
        runtime.add_live_run(sample_run)


def test_multiple_active_runs(runtime, simple_config):
    """Test tracking multiple concurrent runs."""
    runtime.register_command(simple_config)

    runs = [RunResult(command_name=simple_config.name, run_id=f"run-{i}") for i in range(3)]

    for run in runs:
        runtime.add_live_run(run)

    active = runtime.get_active_runs(simple_config.name)
    assert len(active) == 3
    assert {r.run_id for r in active} == {r.run_id for r in runs}


def test_get_active_runs_empty(runtime, simple_config):
    """Test getting active runs when none exist."""
    runtime.register_command(simple_config)

    active = runtime.get_active_runs(simple_config.name)
    assert active == []


def test_get_active_runs_nonexistent_command(runtime):
    """Test getting active runs for non-existent command returns empty list."""
    with pytest.raises(CommandNotFoundError, match="not registered"):
        runtime.get_active_runs("nonexistent")


# ================================================================
# Run Completion Tests
# ================================================================


def test_mark_run_complete_basic(runtime, simple_config):
    """Test marking a run as complete."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")
    runtime.add_live_run(run)

    run.mark_success()
    runtime.mark_run_complete(run)

    # Should be removed from active
    assert len(runtime.get_active_runs(simple_config.name)) == 0

    # Should be in latest_result
    assert runtime.get_latest_result(simple_config.name) is run


def test_mark_run_complete_bad_type_raises(runtime):
    """Test passing a result that is not a RunResult raises TypeError."""

    with pytest.raises(TypeError, match="must be a RunResult instance"):
        runtime.mark_run_complete("string-instead-of-runresult")


def test_mark_run_complete_updates_latest(runtime, simple_config):
    """Test that mark_run_complete updates latest_result."""
    runtime.register_command(simple_config)

    run1 = RunResult(command_name=simple_config.name, run_id="run-1")
    run1.mark_success()
    runtime.mark_run_complete(run1)

    run2 = RunResult(command_name=simple_config.name, run_id="run-2")
    run2.mark_success()
    runtime.mark_run_complete(run2)

    latest = runtime.get_latest_result(simple_config.name)
    assert latest is run2


def test_mark_run_complete_updates_last_start(runtime, simple_config):
    """Test that mark_run_complete without an add_live_run call updates last_start."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")
    run.mark_running()  # set the start_time on the run
    runtime.mark_run_complete(run)

    last_start = runtime._last_start.get(simple_config.name)
    assert last_start == run.start_time


def test_mark_run_complete_adds_to_history(runtime, config_with_history):
    """Test that completed runs are added to history."""
    runtime.register_command(config_with_history)

    runs = []
    for i in range(3):
        run = RunResult(command_name=config_with_history.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)
        runs.append(run)

    history = runtime.get_history(config_with_history.name)
    assert len(history) == 3
    assert history == runs


def test_mark_run_complete_respects_maxlen(runtime, config_with_history):
    """Test that history respects keep_history limit."""
    runtime.register_command(config_with_history)

    # Create more runs than history limit (5)
    runs = []
    for i in range(8):
        run = RunResult(command_name=config_with_history.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)
        runs.append(run)

    history = runtime.get_history(config_with_history.name)
    assert len(history) == 5
    # Should contain last 5 runs
    assert history == runs[-5:]


def test_mark_run_complete_no_history(runtime, config_no_history):
    """Test that runs aren't added to history when keep_history=0."""
    runtime.register_command(config_no_history)

    run = RunResult(command_name=config_no_history.name, run_id="run-1")
    run.mark_success()
    runtime.mark_run_complete(run)

    # History should be empty
    history = runtime.get_history(config_no_history.name)
    assert history == []

    # But latest_result should still be set
    assert runtime.get_latest_result(config_no_history.name) is run


def test_mark_run_complete_not_in_active(runtime, simple_config):
    """Test marking complete for run not in active list (logs warning but doesn't fail)."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")
    run.mark_success()

    # Don't add to active, just mark complete
    runtime.mark_run_complete(run)

    # Should still update latest_result
    assert runtime.get_latest_result(simple_config.name) is run


def test_mark_run_complete_unregistered_command(runtime):
    """Test marking complete for unregistered command (logs warning, doesn't crash)."""
    run = RunResult(command_name="nonexistent", run_id="run-1")
    run.mark_success()

    with pytest.raises(CommandNotFoundError, match="not registered"):
        runtime.mark_run_complete(run)


# ================================================================
# History Tests
# ================================================================


def test_get_history_empty(runtime, simple_config):
    """Test getting history when none exists."""
    runtime.register_command(simple_config)

    history = runtime.get_history(simple_config.name)
    assert history == []


def test_get_history_with_limit(runtime, config_with_history):
    """Test getting history with custom limit."""
    runtime.register_command(config_with_history)

    # Add 5 runs
    for i in range(5):
        run = RunResult(command_name=config_with_history.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)

    # Request only last 2
    history = runtime.get_history(config_with_history.name, limit=2)
    assert len(history) == 2
    # Check that runs returned are the most recent ones
    assert history[0].run_id == "run-3"
    assert history[1].run_id == "run-4"


def test_get_history_limit_larger_than_available(runtime, config_with_history):
    """Test that limit larger than available returns all runs."""
    runtime.register_command(config_with_history)

    # Add 2 runs
    for i in range(2):
        run = RunResult(command_name=config_with_history.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)

    # Request 10
    history = runtime.get_history(config_with_history.name, limit=10)
    assert len(history) == 2


def test_get_history_nonexistent_command(runtime):
    """Test getting history for non-existent command returns empty list."""
    with pytest.raises(CommandNotFoundError, match="not registered"):
        runtime.get_history("nonexistent")


def test_get_latest_result_none(runtime, simple_config):
    """Test getting latest result when none exists."""
    runtime.register_command(simple_config)

    latest = runtime.get_latest_result(simple_config.name)
    assert latest is None


# ================================================================
# Status Query Tests
# ================================================================


def test_get_status_never_run(runtime, simple_config):
    """Test status for command that has never run."""
    runtime.register_command(simple_config)

    status = runtime.get_status(simple_config.name)
    assert status.state == "never_run"
    assert status.active_count == 0
    assert status.last_run is None


def test_get_status_running(runtime, simple_config):
    """Test status for command with active runs."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")
    runtime.add_live_run(run)

    status = runtime.get_status(simple_config.name)
    assert status.state == "running"
    assert status.active_count == 1
    assert status.last_run is None  # No completed runs yet


def test_get_status_success(runtime, simple_config):
    """Test status for successfully completed command."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")
    run.mark_success()
    runtime.mark_run_complete(run)

    status = runtime.get_status(simple_config.name)
    assert status.state == "success"
    assert status.active_count == 0
    assert status.last_run is run


def test_get_status_failed(runtime, simple_config):
    """Test status for failed command."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")
    run.mark_failed("Test error")
    runtime.mark_run_complete(run)

    status = runtime.get_status(simple_config.name)
    assert status.state == "failed"
    assert status.active_count == 0
    assert status.last_run is run


def test_get_status_running_with_history(runtime, simple_config):
    """Test that status shows 'running' even if there's completed history."""
    runtime.register_command(simple_config)

    # Complete one run
    run1 = RunResult(command_name=simple_config.name, run_id="run-1")
    run1.mark_success()
    runtime.mark_run_complete(run1)

    # Start another
    run2 = RunResult(command_name=simple_config.name, run_id="run-2")
    runtime.add_live_run(run2)

    status = runtime.get_status(simple_config.name)
    assert status.state == "running"
    assert status.active_count == 1
    assert status.last_run is run1


def test_get_status_nonexistent_raises(runtime):
    """Test that getting status for non-existent command raises KeyError."""
    with pytest.raises(CommandNotFoundError, match="not registered"):
        runtime.get_status("nonexistent")


# ================================================================
# Debounce Tests
# ================================================================


def test_check_debounce_never_run(runtime, simple_config):
    """Test debounce check for command that has never run."""
    runtime.register_command(simple_config)

    # Should allow (no previous completion)
    assert runtime.check_debounce(simple_config.name, 1000) is True


def test_check_debounce_allowed(runtime, simple_config):
    """Test debounce allows run after sufficient time."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")

    # Record completion
    runtime.mark_run_complete(run)

    # Wait longer than debounce period
    time.sleep(0.01)  # 10ms

    # Should allow (9ms < 10ms elapsed)
    assert runtime.check_debounce(simple_config.name, 5) is True


def test_check_debounce_blocked(runtime, simple_config):
    """Test debounce blocks run within window."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")

    # Record completion
    runtime.mark_run_complete(run)

    # Check immediately (should block)
    assert runtime.check_debounce(simple_config.name, 1000) is False


def test_check_debounce_boundary(runtime, simple_config):
    """Test debounce behavior at exact boundary."""
    runtime.register_command(simple_config)

    run = RunResult(command_name=simple_config.name, run_id="run-1")

    # Record completion
    runtime.mark_run_complete(run)

    # Wait exactly the debounce period
    time.sleep(0.05)  # 50ms

    # Should allow at >= boundary
    assert runtime.check_debounce(simple_config.name, 50) is True


# ================================================================
# Config Replacement with History Tests
# ================================================================


def test_replace_command_history_disabled(runtime, simple_config):
    """Test replacing config that disables history."""
    config1 = CommandConfig(
        name=simple_config.name,
        command="echo v1",
        triggers=["t"],
        keep_history=3,
    )
    config2 = CommandConfig(
        name=simple_config.name,
        command="echo v2",
        triggers=["t"],
        keep_history=0,
    )

    runtime.register_command(config1)

    # Add some history
    for i in range(2):
        run = RunResult(command_name=simple_config.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)

    # Replace with history disabled
    runtime.replace_command(config2)

    # History should be empty now
    assert runtime.get_history(simple_config.name) == []


def test_replace_command_history_reduced(runtime):
    """Test replacing config with smaller history limit."""
    config1 = CommandConfig(
        name=simple_config.name,
        command="echo v1",
        triggers=["t"],
        keep_history=5,
    )
    config2 = CommandConfig(
        name=simple_config.name,
        command="echo v2",
        triggers=["t"],
        keep_history=2,
    )

    runtime.register_command(config1)

    # Add 4 runs
    runs = []
    for i in range(4):
        run = RunResult(command_name=simple_config.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)
        runs.append(run)

    # Replace with smaller limit
    runtime.replace_command(config2)

    # Should keep only last 2
    history = runtime.get_history(simple_config.name)
    assert len(history) == 2
    assert history == runs[-2:]


def test_replace_command_history_increased(runtime, simple_config):
    """Test replacing config with larger history limit."""
    config1 = CommandConfig(
        name=simple_config.name,
        command="echo v1",
        triggers=["t"],
        keep_history=2,
    )
    config2 = CommandConfig(
        name=simple_config.name,
        command="echo v2",
        triggers=["t"],
        keep_history=5,
    )

    runtime.register_command(config1)

    # Add 2 runs (at limit)
    runs = []
    for i in range(2):
        run = RunResult(command_name=simple_config.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)
        runs.append(run)

    # Replace with larger limit
    runtime.replace_command(config2)

    # History should still have 2 runs
    history = runtime.get_history(simple_config.name)
    assert len(history) == 2
    assert history == runs

    # But now we can add more
    for i in range(2, 5):
        run = RunResult(command_name=simple_config.name, run_id=f"run-{i}")
        run.mark_success()
        runtime.mark_run_complete(run)
        runs.append(run)

    history = runtime.get_history(simple_config.name)
    assert len(history) == 5


# ================================================================
# Stats & Introspection Tests
# ================================================================


def test_get_stats_empty(runtime):
    """Test stats for empty runtime."""
    stats = runtime.get_stats()
    assert stats["total_commands"] == 0
    assert stats["total_active_runs"] == 0
    assert stats["commands_with_history"] == 0
    assert stats["commands_with_completed_runs"] == 0


def test_get_stats_populated(runtime):
    """Test stats for runtime with data."""
    # Register 3 commands
    for i in range(3):
        config = CommandConfig(
            name=f"cmd{i}",
            command=f"echo {i}",
            triggers=["t"],
            keep_history=1,
        )
        runtime.register_command(config)

    # Add active runs for cmd0
    for i in range(2):
        run = RunResult(command_name="cmd0", run_id=f"run-{i}")
        runtime.add_live_run(run)

    # Complete runs for cmd1 and cmd2
    for name in ["cmd1", "cmd2"]:
        run = RunResult(command_name=name, run_id="completed")
        run.mark_success()
        runtime.mark_run_complete(run)

    stats = runtime.get_stats()
    assert stats["total_commands"] == 3
    assert stats["total_active_runs"] == 2
    assert stats["commands_with_history"] == 3  # All have keep_history=1
    assert stats["commands_with_completed_runs"] == 2


def test_repr(runtime, simple_config):
    """Test string representation."""
    runtime.register_command(simple_config)

    repr_str = repr(runtime)
    assert "CommandRuntime" in repr_str
    assert "commands=1" in repr_str
    assert "active=0" in repr_str
    assert "commands_with_completed_runs=0" in repr_str
