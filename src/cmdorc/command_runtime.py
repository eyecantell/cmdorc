# cmdorc/command_runtime.py
"""
CommandRuntime - Mutable state store for the orchestrator.

Responsibilities:
- Register/remove/update command configurations
- Track active runs (currently executing)
- Track latest_result per command (always present after first run)
- Track bounded history per keep_history setting
- Track completion timestamps for debounce
- Provide status queries

Does NOT:
- Make execution decisions (that's ConcurrencyPolicy)
- Manage subprocesses (that's CommandExecutor)
- Fire triggers (that's TriggerEngine via Orchestrator)
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict, deque

from .command_config import CommandConfig
from .exceptions import CommandNotFoundError
from .run_result import RunResult
from .types import CommandStatus

logger = logging.getLogger(__name__)


class CommandRuntime:
    """
    Central mutable state store for command orchestration.

    All runtime state (configs, active runs, history, timestamps) lives here.
    This class is intentionally dumb - it stores and retrieves, but doesn't
    make decisions about what to run or cancel.
    """

    def __init__(self) -> None:
        # Configuration registry: name -> CommandConfig
        self._configs: dict[str, CommandConfig] = {}

        # Active runs: name -> list of currently running RunResults
        self._active_runs: dict[str, list[RunResult]] = defaultdict(list)

        # Latest result: name -> most recent completed RunResult
        # Always present after first run, even if keep_in_memory=0
        self._latest_result: dict[str, RunResult] = {}

        # History: name -> bounded deque of completed RunResults
        # Size controlled by CommandConfig.keep_in_memory
        self._history: dict[str, deque[RunResult]] = {}

        # Debounce tracking: name -> timestamp of last START
        # Used when debounce_mode="start"
        self._last_start: dict[str, datetime.datetime] = {}

        # Debounce tracking: name -> timestamp of last COMPLETION
        # Used when debounce_mode="completion"
        self._last_completion: dict[str, datetime.datetime] = {}

    # ================================================================
    # Configuration Management
    # ================================================================

    def register_command(self, config: CommandConfig) -> None:
        """
        Register a new command configuration.

        Raises:
            ValueError if command with this name already exists
        """
        if config.name in self._configs:
            raise ValueError(f"Command '{config.name}' already registered")

        self._configs[config.name] = config

        # Initialize history deque with appropriate maxlen
        if config.keep_in_memory > 0:
            # Bounded deque
            self._history[config.name] = deque(maxlen=config.keep_in_memory)
        elif config.keep_in_memory == -1:
            # Unbounded deque (unlimited)
            self._history[config.name] = deque()
        # else: keep_in_memory == 0, no deque created

        logger.debug(f"Registered command '{config.name}' (keep_in_memory={config.keep_in_memory})")

    def remove_command(self, name: str) -> None:
        """
        Remove a command and all its state.

        Raises:
            CommandNotFoundError if command doesn't exist
        """
        if name not in self._configs:
            raise CommandNotFoundError(f"Command '{name}' not found")

        # Clean up all state
        del self._configs[name]
        self._active_runs.pop(name, None)
        self._latest_result.pop(name, None)
        self._history.pop(name, None)
        self._last_start.pop(name, None)
        self._last_completion.pop(name, None)

        logger.debug(f"Removed command '{name}' and all associated state")

    def update_command(self, config: CommandConfig) -> None:
        """
        Update an existing command's configuration.

        Active runs continue with old config.
        History is preserved if keep_history is compatible.

        Raises:
            KeyError if command doesn't exist
        """
        self.verify_registered(config.name)

        old_config = self._configs[config.name]
        self._configs[config.name] = config

        # Adjust history deque if keep_in_memory changed
        if config.keep_in_memory != old_config.keep_in_memory:
            if config.keep_in_memory == 0:
                # Disable history tracking
                self._history.pop(config.name, None)
                logger.debug(f"Disabled history for '{config.name}'")
            elif config.keep_in_memory == -1:
                # Unlimited: convert to unbounded deque
                old_deque = self._history.get(config.name, deque())
                self._history[config.name] = deque(old_deque)  # No maxlen
                logger.debug(
                    f"Adjusted history for '{config.name}': "
                    f"{old_config.keep_in_memory} -> unlimited"
                )
            else:
                # Bounded: create new deque with new maxlen
                old_deque = self._history.get(config.name, deque())
                new_deque = deque(old_deque, maxlen=config.keep_in_memory)

                self._history[config.name] = new_deque
                logger.debug(
                    f"Adjusted history for '{config.name}': "
                    f"{old_config.keep_in_memory} -> {config.keep_in_memory}"
                )

        logger.debug(f"Updated config for '{config.name}'")

    def get_command(self, name: str) -> CommandConfig | None:
        """Get command configuration by name."""
        return self._configs.get(name)

    def is_registered(self, name: str) -> bool:
        """Check if a command is registered."""
        return name in self._configs

    def verify_registered(self, name: str) -> None:
        """Raise CommandNotFoundError if command is not registered."""
        if name not in self._configs:
            raise CommandNotFoundError(f"Command '{name}' not registered")

    def list_commands(self) -> list[str]:
        """Return list of all registered command names."""
        return list(self._configs.keys())

    # ================================================================
    # Active Run Tracking
    # ================================================================

    def add_live_run(self, result: RunResult) -> None:
        """
        Register a run as active (currently executing).

        Should be called when run transitions to RUNNING state.
        Also records start time for debounce tracking.
        """
        name = result.command_name
        if name not in self._configs:
            raise CommandNotFoundError(f"Command '{name}' not registered")

        self._active_runs[name].append(result)

        # Record start time for debounce (prevent rapid successive starts)
        self._last_start[name] = datetime.datetime.now()

        logger.debug(
            f"Added live run {result.run_id[:8]} for '{name}' "
            f"(active_count={len(self._active_runs[name])})"
        )

    def mark_run_complete(self, result: RunResult) -> None:
        """
        Mark a run as complete and move from active to history.

        Should be called when run reaches a terminal state
        (SUCCESS, FAILED, or CANCELLED).

        This method:
        1. Removes from active runs
        2. Updates latest_result
        3. Records completion time for debounce (if debounce_mode="completion")
        4. Appends to history (if keep_in_memory > 0)

        Note: _last_start is set in add_live_run() for debounce_mode="start".

        Raises:
            KeyError if command not registered
        """

        if not isinstance(result, RunResult):
            raise TypeError(f"result parameter must be a RunResult instance. Got: {type(result)}")

        name = result.command_name

        self.verify_registered(name)

        # Remove from active runs
        active = self._active_runs.get(name, [])
        try:
            active.remove(result)
            logger.debug(
                f"Removed run {result.run_id[:8]} from active '{name}' (remaining={len(active)})"
            )
        except ValueError:
            logger.warning(f"Run {result.run_id[:8]} for '{name}' was not in active list")

        # Update latest result (always, even if keep_in_memory=0)
        self._latest_result[name] = result

        # Record completion time for debounce_mode="completion"
        if result.end_time is not None:
            self._last_completion[name] = result.end_time
            logger.debug(f"Recorded completion time for '{name}': {result.end_time.isoformat()}")
        else:
            # Fallback if end_time not set (shouldn't happen for finalized results)
            self._last_completion[name] = datetime.datetime.now()
            logger.debug(f"No end_time for '{name}', using current time for completion tracking")

        # Backfill _last_start if not set (for startup loading)
        if name not in self._last_start:
            if result.start_time is not None:
                logger.debug(
                    f"No last_start set for '{name}', setting it to run start_time "
                    f"({result.start_time.isoformat()})"
                )
                self._last_start[name] = result.start_time
            else:
                logger.debug(
                    f"No last_start set for '{name}' and run start time is None, setting last_start to now"
                )
                self._last_start[name] = datetime.datetime.now()

        # Add to history if tracking is enabled
        config = self._configs[name]
        if config.keep_in_memory != 0:  # Both positive and -1 (unlimited)
            history = self._history.get(name)
            if history is not None:
                history.append(result)
                limit_str = (
                    "unlimited" if config.keep_in_memory == -1 else str(config.keep_in_memory)
                )
                logger.debug(
                    f"Added run {result.run_id[:8]} to '{name}' history "
                    f"(size={len(history)}/{limit_str})"
                )

    def get_active_runs(self, name: str) -> list[RunResult]:
        """
        Get list of currently active runs for a command.

        Returns:
            List of RunResult objects in RUNNING or PENDING state.
            Empty list if no active runs.

        Raises:
            KeyError if command not registered
        """
        self.verify_registered(name)
        return self._active_runs.get(name, []).copy()

    # ================================================================
    # History & Latest Result
    # ================================================================

    def get_latest_result(self, name: str) -> RunResult | None:
        """
        Get the most recent completed run for a command.

        This is always available after first completion, even if keep_history=0.

        Returns:
            Most recent RunResult, or None if never completed
        Raises:
            KeyError if command not registered
        """
        self.verify_registered(name)
        return self._latest_result.get(name)

    def set_latest_result(self, command_name: str, result: RunResult) -> None:
        """
        Set the latest result for a command (used by history loader).

        Args:
            command_name: Command name
            result: RunResult to set as latest

        Raises:
            KeyError: If command not registered
        """
        self.verify_registered(command_name)
        self._latest_result[command_name] = result

    def get_history(self, name: str, limit: int = 10) -> list[RunResult]:
        """
        Get command history (bounded by keep_in_memory setting).

        Args:
            name: Command name
            limit: Maximum number of results to return (default 10). Zero or negative means no limit.

        Returns:
            List of completed RunResults, most recent last.
            Empty list if no history or keep_in_memory=0.
        Raises:
            KeyError if command not registered
        """
        self.verify_registered(name)
        history = self._history.get(name)
        if history is None:
            return []

        # Return up to `limit` most recent runs
        # deque is ordered by completion time (oldest first)
        return list(history)[-limit:] if limit > 0 else list(history)

    def add_to_history(self, command_name: str, result: RunResult) -> None:
        """
        Add a result to command history (used by history loader on startup).

        This method respects the keep_in_memory limit automatically via the deque's maxlen.
        If keep_in_memory=0, the command has no history deque and this is a no-op.

        Args:
            command_name: Name of the command
            result: RunResult to add to history

        Raises:
            CommandNotFoundError: If command not registered
        """
        self.verify_registered(command_name)

        # Only add if history tracking is enabled (deque exists)
        history = self._history.get(command_name)
        if history is not None:
            history.append(result)
            config = self._configs[command_name]
            limit_str = "unlimited" if config.keep_in_memory == -1 else str(config.keep_in_memory)
            logger.debug(
                f"Added loaded run {result.run_id[:8]} to '{command_name}' history "
                f"(size={len(history)}/{limit_str})"
            )

    # ================================================================
    # Status Queries
    # ================================================================

    def get_status(self, name: str) -> CommandStatus:
        """
        Get rich status object for a command.

        State logic:
        - "never_run" if no runs have ever completed
        - "running" if active_count > 0
        - Otherwise: state of most recent completed run

        Raises:
            KeyError if command not registered
        """
        self.verify_registered(name)

        active_count = len(self._active_runs.get(name, []))
        last_run = self._latest_result.get(name)

        # Determine state string
        if active_count > 0:
            state = "running"
        elif last_run is None:
            state = "never_run"
        else:
            state = last_run.state.value

        return CommandStatus(
            state=state,
            active_count=active_count,
            last_run=last_run,
        )

    # ================================================================
    # Debounce Timing Access
    # ================================================================

    def get_last_start_time(self, name: str) -> datetime.datetime | None:
        """
        Get the last start time for a command.

        Used by ConcurrencyPolicy for debounce_mode="start" calculations.

        Args:
            name: Command name

        Returns:
            Last start timestamp, or None if never started
        """
        return self._last_start.get(name)

    def get_last_completion_time(self, name: str) -> datetime.datetime | None:
        """
        Get the last completion time for a command.

        Used by ConcurrencyPolicy for debounce_mode="completion" calculations.

        Args:
            name: Command name

        Returns:
            Last completion timestamp, or None if never completed
        """
        return self._last_completion.get(name)

    # ================================================================
    # Debugging & Introspection
    # ================================================================

    def get_stats(self) -> dict[str, int]:
        """Get runtime statistics for debugging."""
        return {
            "total_commands": len(self._configs),
            "total_active_runs": sum(len(runs) for runs in self._active_runs.values()),
            "commands_with_history": len(self._history),
            "runs_in_history": sum(len(h) for h in self._history.values()),
            "commands_with_completed_runs": len(self._latest_result),
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        info = (
            f"CommandRuntime("
            f"commands={stats['total_commands']}, "
            f"active={stats['total_active_runs']}, "
            f"runs_in_history={stats['runs_in_history']}, "
            f"commands_with_completed_runs={stats['commands_with_completed_runs']})"
        )

        for command in self.list_commands():
            active_runs = self.get_active_runs(command)
            latest_result = self.get_latest_result(command)
            info += f"\n  Command '{command}': active_runs={len(active_runs)}"
            if latest_result:
                info += f", latest_result_id={latest_result.run_id[:8]}, state={latest_result.state.value}"
            else:
                info += ", latest_result=None"
            info += f", history_size={len(self._history.get(command, []))}"
        return info
