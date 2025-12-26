"""Tests for cmdorc.exceptions module.

Verifies that all custom exception classes:
- Inherit correctly from CmdorcError
- Have proper error messages
- Preserve error context attributes
- Work correctly in exception handling scenarios
"""

from __future__ import annotations

import pytest

from cmdorc.exceptions import (
    CmdorcError,
    CommandNotFoundError,
    ConfigValidationError,
    DebounceError,
    ExecutorError,
    TriggerCycleError,
)


class TestCmdorcErrorBase:
    """Tests for base CmdorcError class."""

    def test_cmdorc_error_is_exception(self):
        """CmdorcError should inherit from Exception."""
        assert issubclass(CmdorcError, Exception)

    def test_cmdorc_error_can_be_raised(self):
        """CmdorcError can be raised and caught."""
        with pytest.raises(CmdorcError):
            raise CmdorcError("Test error")

    def test_cmdorc_error_message(self):
        """CmdorcError preserves custom message."""
        msg = "Something went wrong"
        error = CmdorcError(msg)
        assert str(error) == msg

    def test_catch_cmdorc_error_catches_subclasses(self):
        """Catching CmdorcError should catch all cmdorc exceptions."""
        with pytest.raises(CmdorcError):
            raise CommandNotFoundError("Test")

        with pytest.raises(CmdorcError):
            raise ConfigValidationError("Test")

        with pytest.raises(CmdorcError):
            raise ExecutorError("Test")


class TestCommandNotFoundError:
    """Tests for CommandNotFoundError."""

    def test_inheritance(self):
        """CommandNotFoundError should inherit from CmdorcError."""
        assert issubclass(CommandNotFoundError, CmdorcError)

    def test_basic_raise(self):
        """Should raise and be catchable."""
        with pytest.raises(CommandNotFoundError):
            raise CommandNotFoundError("Test")

    def test_error_message(self):
        """Error message should be preserved."""
        error = CommandNotFoundError("MyCommand")
        assert "MyCommand" in str(error)

    def test_use_case_unregistered_command(self):
        """Typical usage: accessing non-existent command."""
        registry = {"cmd1": None, "cmd2": None}
        cmd_name = "nonexistent"

        if cmd_name not in registry:
            with pytest.raises(CommandNotFoundError):
                raise CommandNotFoundError(f"Command '{cmd_name}' not registered")


class TestConfigValidationError:
    """Tests for ConfigValidationError."""

    def test_inheritance(self):
        """ConfigValidationError should inherit from CmdorcError."""
        assert issubclass(ConfigValidationError, CmdorcError)

    def test_basic_raise(self):
        """Should raise and be catchable."""
        with pytest.raises(ConfigValidationError):
            raise ConfigValidationError("Invalid config")

    def test_error_message(self):
        """Error message should be preserved."""
        msg = "Command for 'Test' cannot be empty"
        error = ConfigValidationError(msg)
        assert str(error) == msg

    def test_multiple_validation_errors(self):
        """Should be able to raise multiple different validation errors."""
        errors = [
            ConfigValidationError("timeout cannot be negative"),
            ConfigValidationError("command cannot be empty"),
            ConfigValidationError("unknown trigger name"),
        ]
        assert len(errors) == 3
        assert all(isinstance(e, CmdorcError) for e in errors)


class TestDebounceError:
    """Tests for DebounceError."""

    def test_inheritance(self):
        """DebounceError should inherit from CmdorcError."""
        assert issubclass(DebounceError, CmdorcError)

    def test_initialization(self):
        """DebounceError should store timing context."""
        error = DebounceError("TestCmd", 500, 200.5)
        assert error.command_name == "TestCmd"
        assert error.debounce_ms == 500
        assert error.elapsed_ms == 200.5

    def test_error_message_format(self):
        """Error message should include all timing information."""
        error = DebounceError("TestCmd", 500, 200.5)
        msg = str(error)
        assert "TestCmd" in msg
        assert "500" in msg
        assert "200.5" in msg
        assert "remaining" in msg.lower()

    def test_remaining_time_calculation(self):
        """Error message should correctly calculate remaining time."""
        error = DebounceError("TestCmd", 1000, 300.0)
        msg = str(error)
        # remaining should be 1000 - 300 = 700
        assert "700.0" in msg

    def test_debounce_scenarios(self):
        """Test various debounce timing scenarios."""
        # Just within debounce window
        error1 = DebounceError("cmd", 1000, 900.0)
        assert "100.0" in str(error1)

        # Recently executed
        error2 = DebounceError("cmd", 1000, 10.0)
        assert "990.0" in str(error2)

        # Just barely over threshold (no debounce)
        error3 = DebounceError("cmd", 1000, 1000.0)
        assert "0.0" in str(error3)

    def test_zero_elapsed_time(self):
        """Should handle zero elapsed time."""
        error = DebounceError("cmd", 100, 0.0)
        msg = str(error)
        assert "0.0" in msg
        assert "100.0" in msg

    def test_catch_specific_error(self):
        """Should be catchable as DebounceError specifically."""
        with pytest.raises(DebounceError) as exc_info:
            raise DebounceError("cmd", 1000, 500.0)

        error = exc_info.value
        assert error.command_name == "cmd"
        assert error.debounce_ms == 1000
        assert error.elapsed_ms == 500.0


class TestExecutorError:
    """Tests for ExecutorError."""

    def test_inheritance(self):
        """ExecutorError should inherit from CmdorcError."""
        assert issubclass(ExecutorError, CmdorcError)

    def test_basic_raise(self):
        """Should raise and be catchable."""
        with pytest.raises(ExecutorError):
            raise ExecutorError("Executor failed")

    def test_error_message(self):
        """Error message should be preserved."""
        msg = "Failed to create subprocess"
        error = ExecutorError(msg)
        assert str(error) == msg

    def test_executor_failure_scenarios(self):
        """Test typical executor failure messages."""
        scenarios = [
            "Failed to create subprocess",
            "Executor internal state corrupted",
            "Resource exhaustion: too many open processes",
            "Permission denied creating subprocess",
        ]

        for scenario in scenarios:
            with pytest.raises(ExecutorError) as exc_info:
                raise ExecutorError(scenario)
            assert scenario in str(exc_info.value)


class TestTriggerCycleError:
    """Tests for TriggerCycleError."""

    def test_inheritance(self):
        """TriggerCycleError should inherit from CmdorcError."""
        assert issubclass(TriggerCycleError, CmdorcError)

    def test_initialization(self):
        """TriggerCycleError should store cycle information."""
        cycle_path = ["event_a", "event_b", "event_c"]
        error = TriggerCycleError("event_a", cycle_path)
        assert error.event_name == "event_a"
        assert error.cycle_path == cycle_path

    def test_error_message_format(self):
        """Error message should display cycle chain."""
        cycle_path = ["cmd_start", "cmd_success", "cmd_restart"]
        error = TriggerCycleError("cmd_start", cycle_path)
        msg = str(error)
        assert "cycle" in msg.lower()
        assert "cmd_start" in msg
        assert "cmd_success" in msg
        assert "cmd_restart" in msg
        assert "->" in msg

    def test_simple_two_event_cycle(self):
        """Should handle simple two-event cycle (A -> B -> A)."""
        error = TriggerCycleError("event_a", ["event_b"])
        msg = str(error)
        # Should show: event_b -> event_a
        assert "event_b" in msg
        assert "event_a" in msg

    def test_complex_cycle_chain(self):
        """Should handle complex multi-event cycles."""
        cycle_path = ["start", "success", "restart", "running"]
        error = TriggerCycleError("start", cycle_path)
        msg = str(error)
        # Should show chain ending with arrow back to start
        assert "start" in msg
        assert "success" in msg
        assert "restart" in msg
        assert "running" in msg

    def test_single_event_cycle_self_trigger(self):
        """Should handle self-trigger (event triggers itself)."""
        error = TriggerCycleError("event_a", [])
        # Empty path means self-trigger
        assert error.command_name if hasattr(error, "command_name") else True
        assert error.event_name == "event_a"

    def test_catch_specific_error(self):
        """Should be catchable as TriggerCycleError specifically."""
        with pytest.raises(TriggerCycleError) as exc_info:
            raise TriggerCycleError("event_start", ["event_b", "event_c"])

        error = exc_info.value
        assert error.event_name == "event_start"
        assert error.cycle_path == ["event_b", "event_c"]

    def test_cycle_with_pre_cycle_path(self):
        """Test cycle detection where event_name appears mid-path (has pre_cycle)."""
        # Path: a -> b -> c -> b (cycle starts at 'b', index 1)
        cycle_path = ["a", "b", "c"]
        error = TriggerCycleError("b", cycle_path)

        assert error.cycle_point == 1
        msg = str(error)
        # Should have "Trigger chain: a" and "Cycle: b -> c -> b"
        assert "a" in msg
        assert "b" in msg
        assert "c" in msg

    def test_cycle_without_pre_cycle_path(self):
        """Test cycle where event_name is at start of path (no pre_cycle)."""
        # Path: a -> b -> a (cycle starts at 'a', index 0)
        cycle_path = ["a", "b"]
        error = TriggerCycleError("a", cycle_path)

        assert error.cycle_point == 0
        msg = str(error)
        # No pre_cycle, just the cycle part
        assert "a" in msg
        assert "b" in msg


class TestExceptionHierarchy:
    """Tests for exception class hierarchy and relationships."""

    def test_all_cmdorc_exceptions_are_exceptions(self):
        """All custom exceptions should inherit from Exception."""
        exceptions = [
            CommandNotFoundError,
            ConfigValidationError,
            DebounceError,
            ExecutorError,
            TriggerCycleError,
        ]
        assert all(issubclass(exc, Exception) for exc in exceptions)

    def test_all_cmdorc_exceptions_inherit_from_cmdorc_error(self):
        """All custom exceptions should inherit from CmdorcError."""
        exceptions = [
            CommandNotFoundError,
            ConfigValidationError,
            DebounceError,
            ExecutorError,
            TriggerCycleError,
        ]
        assert all(issubclass(exc, CmdorcError) for exc in exceptions)

    def test_catch_all_with_base_class(self):
        """Should be able to catch all with CmdorcError."""
        exceptions_to_raise = [
            CommandNotFoundError("not found"),
            ConfigValidationError("invalid"),
            DebounceError("cmd", 100, 50),
            ExecutorError("failed"),
            TriggerCycleError("evt", ["a", "b"]),
        ]

        for exc in exceptions_to_raise:
            with pytest.raises(CmdorcError):
                raise exc

    def test_distinguish_specific_exceptions(self):
        """Should be able to distinguish between exception types."""
        try:
            raise DebounceError("cmd", 100, 50)
        except CommandNotFoundError:
            pytest.fail("Should not catch as CommandNotFoundError")
        except DebounceError:
            pass  # Expected

        try:
            raise TriggerCycleError("evt", [])
        except ExecutorError:
            pytest.fail("Should not catch as ExecutorError")
        except TriggerCycleError:
            pass  # Expected


class TestExceptionUsagePatterns:
    """Tests for realistic exception usage patterns."""

    def test_pattern_runtime_command_lookup(self):
        """Pattern: checking command existence in runtime."""
        commands = {"test": None, "build": None}

        def get_command(name: str):
            if name not in commands:
                raise CommandNotFoundError(f"Command '{name}' not registered")
            return commands[name]

        assert get_command("test") is None

        with pytest.raises(CommandNotFoundError):
            get_command("unknown")

    def test_pattern_config_validation(self):
        """Pattern: validating configuration."""

        def validate_command_config(name: str, command: str, timeout: int):
            if not command:
                raise ConfigValidationError(f"Command for '{name}' cannot be empty")
            if timeout < 0:
                raise ConfigValidationError(f"Command '{name}' timeout cannot be negative")

        validate_command_config("test", "pytest", 30)

        with pytest.raises(ConfigValidationError):
            validate_command_config("test", "", 30)

        with pytest.raises(ConfigValidationError):
            validate_command_config("test", "pytest", -1)

    def test_pattern_debounce_check(self):
        """Pattern: checking debounce windows."""
        last_run_ms = 1000.0
        now_ms = 1450.0
        debounce_ms = 500

        elapsed = now_ms - last_run_ms
        if elapsed < debounce_ms:
            with pytest.raises(DebounceError):
                raise DebounceError("cmd", debounce_ms, elapsed)

    def test_pattern_trigger_cycle_detection(self):
        """Pattern: detecting trigger cycles."""
        seen_events = {"event_a", "event_b"}
        new_event = "event_a"

        if new_event in seen_events:
            cycle_path = list(seen_events - {new_event})
            with pytest.raises(TriggerCycleError):
                raise TriggerCycleError(new_event, cycle_path)

    def test_pattern_executor_error_handling(self):
        """Pattern: executor failures."""

        def simulate_executor():
            raise ExecutorError("Failed to create subprocess: ENOMEM")

        with pytest.raises(ExecutorError) as exc_info:
            simulate_executor()

        assert "ENOMEM" in str(exc_info.value)

    def test_pattern_graceful_degradation(self):
        """Pattern: catching and handling errors gracefully."""
        errors_encountered = []

        try:
            raise CommandNotFoundError("missing_cmd")
        except CommandNotFoundError as e:
            errors_encountered.append(e)

        try:
            raise ConfigValidationError("bad_timeout")
        except ConfigValidationError as e:
            errors_encountered.append(e)

        assert len(errors_encountered) == 2
        assert all(isinstance(e, CmdorcError) for e in errors_encountered)
