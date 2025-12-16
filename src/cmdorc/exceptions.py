# cmdorc/exceptions.py
"""
Custom exception hierarchy for cmdorc.

All cmdorc-specific exceptions inherit from CmdorcError to enable
catch-all error handling while still providing specific exception types
for different error conditions.
"""

from __future__ import annotations


class CmdorcError(Exception):
    """
    Base exception for all cmdorc errors.

    Catch this to handle any cmdorc-specific error.
    """

    pass


class CommandNotFoundError(CmdorcError):
    """
    Raised when attempting to operate on an unregistered command.

    Example:
        >>> runtime.get_command("NonExistent")
        CommandNotFoundError: Command 'NonExistent' not registered
    """

    pass


class DebounceError(CmdorcError):
    """
    Raised when a command is triggered within its debounce window.

    The debounce window prevents rapid successive executions of the same command.
    This error includes timing information to help diagnose the issue.

    Attributes:
        command_name: Name of the command that was debounced
        debounce_ms: Required debounce period in milliseconds
        elapsed_ms: Time elapsed since last execution in milliseconds
    """

    def __init__(self, command_name: str, debounce_ms: int, elapsed_ms: float):
        """
        Initialize DebounceError with timing context.

        Args:
            command_name: Name of the command
            debounce_ms: Required debounce period in milliseconds
            elapsed_ms: Actual elapsed time in milliseconds
        """
        self.command_name = command_name
        self.debounce_ms = debounce_ms
        self.elapsed_ms = elapsed_ms
        remaining_ms = debounce_ms - elapsed_ms
        super().__init__(
            f"Command '{command_name}' is in debounce window "
            f"(elapsed: {elapsed_ms:.1f}ms, required: {debounce_ms}ms, "
            f"remaining: {remaining_ms:.1f}ms)"
        )


class ConfigValidationError(CmdorcError):
    """
    Raised when CommandConfig validation fails.

    This is raised during CommandConfig.__post_init__ when validation
    constraints are violated (e.g., negative timeout, invalid trigger names).

    Example:
        >>> CommandConfig(name="Test", command="", triggers=[])
        ConfigValidationError: Command for 'Test' cannot be empty
    """

    pass


class ExecutorError(CmdorcError):
    """
    Raised when executor encounters an unrecoverable error.

    This is for executor-level failures that aren't normal command failures
    (those are reflected in RunResult.state=FAILED). Examples include:
    - Inability to create subprocess
    - Corrupted internal state
    - Resource exhaustion
    """

    pass


class TriggerCycleError(CmdorcError):
    """
    Raised when a trigger cycle is detected (when loop_detection=True).

    Trigger cycles occur when event A triggers event B, which triggers event C,
    which triggers event A again, creating an infinite loop.

    Attributes:
        event_name: The event that would create the cycle
        cycle_path: Ordered list of events in the trigger chain
        cycle_point: Index where the cycle begins (where event_name appears in cycle_path)
    """

    def __init__(self, event_name: str, cycle_path: list[str]):
        """
        Initialize TriggerCycleError with cycle information.

        Args:
            event_name: Event that triggered the cycle detection
            cycle_path: Ordered list of events in the trigger chain (breadcrumb trail)
        """
        self.event_name = event_name
        self.cycle_path = cycle_path

        # Find where cycle begins
        try:
            self.cycle_point = cycle_path.index(event_name)
        except ValueError:
            self.cycle_point = None

        # Build detailed error message
        if self.cycle_point is not None:
            pre_cycle = cycle_path[:self.cycle_point]
            cycle = cycle_path[self.cycle_point:]

            msg_parts = []
            if pre_cycle:
                msg_parts.append(f"Trigger chain: {' -> '.join(pre_cycle)}")
            msg_parts.append(f"Cycle: {' -> '.join(cycle)} -> {event_name}")
            message = "\n".join(msg_parts)
        else:
            full_chain = " -> ".join(cycle_path) + f" -> {event_name}"
            message = f"Trigger cycle detected: {full_chain}"

        super().__init__(message)


class ConcurrencyLimitError(CmdorcError):
    """
    Raised when command execution is denied due to concurrency policy.

    This occurs when:
    - max_concurrent limit is reached AND
    - on_retrigger="ignore" (so new run is blocked instead of cancelling old ones)

    The error includes context about the limit and current active runs to aid
    debugging and decision-making about whether to retry.

    Attributes:
        command_name: Name of the command
        active_count: Number of currently active runs
        max_concurrent: Maximum allowed concurrent runs
        policy: The on_retrigger policy in effect
    """

    def __init__(
        self,
        command_name: str,
        active_count: int,
        max_concurrent: int,
        policy: str = "ignore",
    ):
        """
        Initialize ConcurrencyLimitError with context.

        Args:
            command_name: Name of the command
            active_count: Number of currently active runs
            max_concurrent: Maximum allowed concurrent runs
            policy: The on_retrigger policy in effect
        """
        self.command_name = command_name
        self.active_count = active_count
        self.max_concurrent = max_concurrent
        self.policy = policy
        super().__init__(
            f"Command '{command_name}' cannot start: "
            f"{active_count}/{max_concurrent} active, on_retrigger={policy}"
        )


class OrchestratorShutdownError(CmdorcError):
    """
    Raised when an operation is rejected during orchestrator shutdown.

    This occurs when:
    - run_command() is called while shutdown is in progress
    - trigger() is called while shutdown is in progress
    - Any other public method is called after _is_shutdown=True

    This error prevents new operations from starting during graceful shutdown,
    ensuring clean lifecycle management.
    """

    pass
