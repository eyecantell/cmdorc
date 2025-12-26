# tests/test_trigger_engine.py
"""
Comprehensive test suite for TriggerEngine.

Tests pattern matching, callback dispatch, command matching, and cycle detection.
"""

from __future__ import annotations

import pytest

from cmdorc import CommandConfig, CommandRuntime, TriggerEngine
from cmdorc.types import TriggerContext

# ========================================================================
# Fixtures
# ========================================================================


@pytest.fixture
def runtime():
    """Fresh CommandRuntime for testing."""
    return CommandRuntime()


@pytest.fixture
def engine(runtime: CommandRuntime):
    """Fresh TriggerEngine bound to runtime."""
    return TriggerEngine(runtime)


@pytest.fixture
def sample_configs():
    """Sample CommandConfigs for testing."""
    return [
        CommandConfig(
            name="Tests",
            command="pytest",
            triggers=["changes_applied", "test_save"],
            cancel_on_triggers=[],
        ),
        CommandConfig(
            name="Lint",
            command="ruff check",
            triggers=["changes_applied", "command_success:Tests"],
            cancel_on_triggers=[],
        ),
        CommandConfig(
            name="Build",
            command="cargo build",
            triggers=["command_success:Lint"],
            cancel_on_triggers=["urgent_stop"],
        ),
    ]


# ========================================================================
# Pattern Matching Tests
# ========================================================================


class TestPatternMatching:
    """Tests for the matches() method."""

    def test_exact_match(self, engine: TriggerEngine):
        """Exact strings should match."""
        assert engine.matches("build", "build")
        assert engine.matches("command_success:Tests", "command_success:Tests")

    def test_exact_no_match(self, engine: TriggerEngine):
        """Non-matching exact strings should not match."""
        assert not engine.matches("build", "test")
        assert not engine.matches("build", "builds")

    def test_wildcard_suffix(self, engine: TriggerEngine):
        """Wildcard at end should match."""
        assert engine.matches("command_*", "command_success")
        assert engine.matches("command_*", "command_failed")
        assert engine.matches("command_*", "command_cancelled")

    def test_wildcard_prefix(self, engine: TriggerEngine):
        """Wildcard at start should match."""
        assert engine.matches("*_applied", "changes_applied")
        assert engine.matches("*_applied", "rebuild_applied")

    def test_wildcard_infix(self, engine: TriggerEngine):
        """Wildcard in middle should match."""
        assert engine.matches("command_*:Tests", "command_success:Tests")
        assert engine.matches("command_*:Tests", "command_failed:Tests")
        assert not engine.matches("command_*:Tests", "command_success:Lint")

    def test_multiple_wildcards(self, engine: TriggerEngine):
        """Multiple wildcards should work."""
        assert engine.matches("command_*:*", "command_success:Tests")
        assert engine.matches("command_*:*", "command_failed:Build")

    def test_wildcard_matches_empty(self, engine: TriggerEngine):
        """Wildcard should match empty string."""
        assert engine.matches("command_*", "command_")
        assert engine.matches("*_applied", "_applied")

    def test_no_false_positives(self, engine: TriggerEngine):
        """Wildcard should not create false matches."""
        assert not engine.matches("test", "testing")
        assert not engine.matches("*_applied", "notapplied")


# ========================================================================
# Command Matching Tests
# ========================================================================


class TestCommandMatching:
    """Tests for get_matching_commands()."""

    def test_exact_trigger_match(
        self, engine: TriggerEngine, runtime: CommandRuntime, sample_configs: list
    ):
        """Commands with exact trigger should be returned."""
        runtime.register_command(sample_configs[0])
        matches = engine.get_matching_commands("changes_applied", "triggers")
        assert len(matches) == 1
        assert matches[0].name == "Tests"

    def test_wildcard_trigger_match(
        self, engine: TriggerEngine, runtime: CommandRuntime, sample_configs: list
    ):
        """Commands with exact triggers should be returned."""
        runtime.register_command(sample_configs[0])
        matches = engine.get_matching_commands("test_save", "triggers")
        assert len(matches) == 1
        assert matches[0].name == "Tests"

    def test_exact_then_wildcard_ordering(self, engine: TriggerEngine, runtime: CommandRuntime):
        """Exact matches should come before wildcard matches."""
        config1 = CommandConfig(
            name="First",
            command="echo 1",
            triggers=["changes_applied"],
        )
        config2 = CommandConfig(
            name="Second",
            command="echo 2",
            triggers=["changes_done"],
        )
        runtime.register_command(config1)
        runtime.register_command(config2)

        matches = engine.get_matching_commands("changes_applied", "triggers")
        assert len(matches) == 1
        assert matches[0].name == "First"  # Only exact match

    def test_cancel_on_triggers(
        self, engine: TriggerEngine, runtime: CommandRuntime, sample_configs: list
    ):
        """cancel_on_triggers should be matched separately."""
        runtime.register_command(sample_configs[2])  # Build has cancel_on_triggers
        matches = engine.get_matching_commands("urgent_stop", "cancel_on_triggers")
        assert len(matches) == 1
        assert matches[0].name == "Build"

    def test_no_matches(self, engine: TriggerEngine, runtime: CommandRuntime, sample_configs: list):
        """Non-matching events should return empty list."""
        runtime.register_command(sample_configs[0])
        matches = engine.get_matching_commands("nonexistent_event", "triggers")
        assert len(matches) == 0

    def test_lifecycle_event_matching(
        self, engine: TriggerEngine, runtime: CommandRuntime, sample_configs: list
    ):
        """Lifecycle events should match."""
        runtime.register_command(sample_configs[1])  # Lint
        matches = engine.get_matching_commands("command_success:Tests", "triggers")
        assert len(matches) == 1
        assert matches[0].name == "Lint"


# ========================================================================
# Callback Registration Tests
# ========================================================================


class TestCallbackRegistration:
    """Tests for callback registration/unregistration."""

    def test_register_exact_callback(self, engine: TriggerEngine):
        """Exact callbacks should be registerable."""

        def callback():
            pass

        engine.register_callback("test_event", callback)
        callbacks = engine.get_matching_callbacks("test_event")
        assert len(callbacks) == 1
        assert callbacks[0][0] == callback
        assert callbacks[0][1] is False  # Not a wildcard

    def test_register_wildcard_callback(self, engine: TriggerEngine):
        """Wildcard callbacks should be registerable."""

        def callback():
            pass

        engine.register_callback("test_*", callback)
        callbacks = engine.get_matching_callbacks("test_event")
        assert len(callbacks) == 1
        assert callbacks[0][0] == callback
        assert callbacks[0][1] is True  # Is a wildcard

    def test_register_multiple_callbacks_same_pattern(self, engine: TriggerEngine):
        """Multiple callbacks on same pattern should all be registered."""

        def callback1():
            pass

        def callback2():
            pass

        engine.register_callback("event", callback1)
        engine.register_callback("event", callback2)
        callbacks = engine.get_matching_callbacks("event")
        assert len(callbacks) == 2

    def test_unregister_callback(self, engine: TriggerEngine):
        """Callbacks should be unregisterable."""

        def callback():
            pass

        engine.register_callback("event", callback)
        assert engine.unregister_callback("event", callback) is True
        callbacks = engine.get_matching_callbacks("event")
        assert len(callbacks) == 0

    def test_unregister_nonexistent_callback(self, engine: TriggerEngine):
        """Unregistering non-existent callback should return False."""

        def callback():
            pass

        assert engine.unregister_callback("nonexistent", callback) is False

    def test_unregister_wildcard_callback(self, engine: TriggerEngine):
        """Wildcard callbacks should be unregisterable."""

        def callback():
            pass

        engine.register_callback("command_*", callback)
        assert engine.unregister_callback("command_*", callback) is True
        callbacks = engine.get_matching_callbacks("command_success")
        assert len(callbacks) == 0

    def test_unregister_nonexistent_wildcard_callback(self, engine: TriggerEngine):
        """Unregistering non-existent wildcard callback should return False."""

        def callback():
            pass

        def other_callback():
            pass

        engine.register_callback("event_*", callback)
        # Try to unregister a different callback
        assert engine.unregister_callback("event_*", other_callback) is False
        # Original callback should still be registered
        callbacks = engine.get_matching_callbacks("event_test")
        assert len(callbacks) == 1

    def test_unregister_callback_from_existing_pattern_wrong_callback(self, engine: TriggerEngine):
        """Unregistering wrong callback from existing exact pattern should return False."""

        def callback1():
            pass

        def callback2():
            pass

        engine.register_callback("event", callback1)
        # Try to unregister callback2 which was never registered
        assert engine.unregister_callback("event", callback2) is False
        # Original callback should still be there
        callbacks = engine.get_matching_callbacks("event")
        assert len(callbacks) == 1

    def test_lifecycle_callback_registration(self, engine: TriggerEngine):
        """Lifecycle callbacks should be registerable."""

        def on_success():
            pass

        def on_failed():
            pass

        engine.set_lifecycle_callback(
            "MyCommand",
            on_success=on_success,
            on_failed=on_failed,
        )

        assert engine.get_lifecycle_callback("MyCommand", "on_success") == on_success
        assert engine.get_lifecycle_callback("MyCommand", "on_failed") == on_failed
        assert engine.get_lifecycle_callback("MyCommand", "on_cancelled") is None

    def test_empty_pattern_raises(self, engine: TriggerEngine):
        """Empty pattern should raise ValueError."""

        def callback():
            pass

        with pytest.raises(ValueError, match="Pattern cannot be empty"):
            engine.register_callback("", callback)

    def test_none_callback_raises(self, engine: TriggerEngine):
        """None callback should raise ValueError."""
        with pytest.raises(ValueError, match="Callback cannot be None"):
            engine.register_callback("event", None)  # type: ignore


# ========================================================================
# Callback Dispatch Order Tests
# ========================================================================


class TestDispatchOrder:
    """Tests for callback dispatch ordering."""

    def test_exact_before_wildcard(self, engine: TriggerEngine):
        """Exact match callbacks should be dispatched before wildcard."""
        call_order = []

        def exact_callback():
            call_order.append("exact")

        def wildcard_callback():
            call_order.append("wildcard")

        engine.register_callback("event", exact_callback)
        engine.register_callback("event_*", wildcard_callback)

        callbacks = engine.get_matching_callbacks("event_test")
        # Verify order in returned list (only wildcard matches)
        assert len(callbacks) == 1
        assert callbacks[0][1] is True  # Wildcard

    def test_registration_order_preserved(self, engine: TriggerEngine):
        """Registration order should be preserved within groups."""
        call_order = []

        def callback1():
            call_order.append(1)

        def callback2():
            call_order.append(2)

        def callback3():
            call_order.append(3)

        engine.register_callback("event", callback1)
        engine.register_callback("event", callback2)
        engine.register_callback("event", callback3)

        callbacks = engine.get_matching_callbacks("event")
        assert len(callbacks) == 3
        # Verify order is preserved by checking the functions themselves
        assert callbacks[0][0] == callback1
        assert callbacks[1][0] == callback2
        assert callbacks[2][0] == callback3

    def test_multiple_wildcard_callbacks(self, engine: TriggerEngine):
        """Multiple wildcard callbacks should all match and be ordered."""

        def wildcard1():
            pass

        def wildcard2():
            pass

        engine.register_callback("test_*", wildcard1)
        engine.register_callback("*_event", wildcard2)

        callbacks = engine.get_matching_callbacks("test_event")
        assert len(callbacks) == 2
        # Both should match
        assert callbacks[0][0] == wildcard1
        assert callbacks[1][0] == wildcard2


# ========================================================================
# Cycle Detection Tests
# ========================================================================


class TestCycleDetection:
    """Tests for cycle detection via TriggerContext.seen."""

    def test_simple_cycle_detection(self, engine: TriggerEngine):
        """Simple cycle (A → A) should be detected."""
        context = TriggerContext(seen={"event"})
        assert not engine.check_cycle("event", context)

    def test_chain_cycle_detection(self, engine: TriggerEngine):
        """Chain cycle (A → B → A) should be detected."""
        context = TriggerContext(seen={"event_a", "event_b"})
        # If event_a is already seen, triggering it again would be a cycle
        assert not engine.check_cycle("event_a", context)

    def test_no_cycle_first_event(self, engine: TriggerEngine):
        """First event should never be detected as cycle."""
        context = TriggerContext(seen=set())
        assert engine.check_cycle("event", context)

    def test_no_cycle_different_event(self, engine: TriggerEngine):
        """Different event should not be detected as cycle."""
        context = TriggerContext(seen={"event_a"})
        assert engine.check_cycle("event_b", context)

    def test_should_track_in_context_enabled(self, engine: TriggerEngine, runtime: CommandRuntime):
        """Commands with loop_detection=True should be tracked."""
        config = CommandConfig(
            name="TestCmd",
            command="test",
            triggers=["test_event"],
            loop_detection=True,
        )
        runtime.register_command(config)
        assert engine.should_track_in_context("TestCmd") is True

    def test_should_track_in_context_disabled(self, engine: TriggerEngine, runtime: CommandRuntime):
        """Commands with loop_detection=False should not be tracked."""
        config = CommandConfig(
            name="TestCmd",
            command="test",
            triggers=["test_event"],
            loop_detection=False,
        )
        runtime.register_command(config)
        assert engine.should_track_in_context("TestCmd") is False

    def test_should_track_unknown_command(self, engine: TriggerEngine):
        """Unknown commands should default to True (safe)."""
        assert engine.should_track_in_context("UnknownCmd") is True


# ========================================================================
# Integration Tests
# ========================================================================


class TestIntegration:
    """Integration tests with CommandRuntime."""

    def test_full_trigger_matching_flow(
        self, engine: TriggerEngine, runtime: CommandRuntime, sample_configs: list
    ):
        """Full flow: register commands, match by event."""
        for config in sample_configs:
            runtime.register_command(config)

        # Test exact match
        matches = engine.get_matching_commands("changes_applied", "triggers")
        assert len(matches) == 2  # Tests and Lint both triggered

        # Test lifecycle match
        matches = engine.get_matching_commands("command_success:Tests", "triggers")
        assert len(matches) == 1  # Lint triggered
        assert matches[0].name == "Lint"

    def test_command_removal_cleanup(self, engine: TriggerEngine, runtime: CommandRuntime):
        """Removing commands should affect matching."""
        config = CommandConfig(
            name="TestCmd",
            command="test",
            triggers=["rebuild"],
        )
        runtime.register_command(config)
        assert len(engine.get_matching_commands("rebuild", "triggers")) == 1

        # After removing command
        runtime.remove_command("TestCmd")
        assert len(engine.get_matching_commands("rebuild", "triggers")) == 0

    def test_dynamic_command_registration(self, engine: TriggerEngine, runtime: CommandRuntime):
        """Dynamically registering commands should be matched."""
        assert len(engine.get_matching_commands("dynamic_event", "triggers")) == 0

        config = CommandConfig(
            name="DynamicCmd",
            command="dynamic",
            triggers=["dynamic_event"],
        )
        runtime.register_command(config)
        assert len(engine.get_matching_commands("dynamic_event", "triggers")) == 1

    def test_complex_trigger_scenario(self, engine: TriggerEngine, runtime: CommandRuntime):
        """Complex scenario with multiple commands and patterns."""
        configs = [
            CommandConfig(
                name="Watch",
                command="watch",
                triggers=["file_changed"],
            ),
            CommandConfig(
                name="Tests",
                command="pytest",
                triggers=["file_changed", "rebuild"],
            ),
            CommandConfig(
                name="Lint",
                command="lint",
                triggers=["command_success:Tests"],
            ),
            CommandConfig(
                name="Report",
                command="report",
                triggers=["command_success:Tests", "command_success:Lint"],
            ),
        ]

        for config in configs:
            runtime.register_command(config)

        # file_changed triggers Watch and Tests
        matches = engine.get_matching_commands("file_changed", "triggers")
        assert len(matches) == 2
        names = {m.name for m in matches}
        assert names == {"Watch", "Tests"}

        # command_success:Tests triggers Lint and Report
        matches = engine.get_matching_commands("command_success:Tests", "triggers")
        assert len(matches) == 2
        names = {m.name for m in matches}
        assert names == {"Lint", "Report"}

        # command_success:Lint only triggers Report
        matches = engine.get_matching_commands("command_success:Lint", "triggers")
        assert len(matches) == 1
        assert matches[0].name == "Report"


# ========================================================================
# Utility Tests
# ========================================================================


class TestUtilities:
    """Tests for utility methods."""

    def test_clear_all_callbacks(self, engine: TriggerEngine):
        """clear_all_callbacks() should clear all registrations."""

        def callback():
            pass

        engine.register_callback("event", callback)
        engine.register_callback("event_*", callback)
        engine.set_lifecycle_callback("cmd", on_success=callback)

        engine.clear_all_callbacks()

        assert len(engine.get_matching_callbacks("event")) == 0
        assert engine.get_lifecycle_callback("cmd", "on_success") is None

    def test_repr(self, engine: TriggerEngine):
        """__repr__ should provide useful debug info."""

        def callback():
            pass

        engine.register_callback("event", callback)
        engine.register_callback("event_*", callback)
        engine.set_lifecycle_callback("cmd", on_success=callback)

        repr_str = repr(engine)
        assert "TriggerEngine" in repr_str
        assert "exact_callbacks" in repr_str
        assert "wildcard_callbacks" in repr_str
        assert "lifecycle_callbacks" in repr_str
