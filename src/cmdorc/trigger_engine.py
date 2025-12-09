# cmdorc/trigger_engine.py
"""
TriggerEngine - Event routing and callback dispatch system.

Responsibilities:
- Match event names against patterns (exact + wildcards)
- Maintain callback registry
- Return matching commands for trigger types
- Enforce dispatch ordering
- Support cycle detection via TriggerContext

Does NOT:
- Execute commands
- Manage state
- Apply concurrency policies
- Own TriggerContext lifecycle (orchestrator does)
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Literal

    from .command_config import CommandConfig
    from .command_runtime import CommandRuntime
    from .types import TriggerContext


class TriggerEngine:
    """Event routing and callback dispatch engine.

    Pure pattern-matching engine that knows nothing about command execution.
    All pattern matching, callback dispatch, and cycle detection happens here.
    """

    def __init__(self, runtime: CommandRuntime) -> None:
        """Initialize the trigger engine.

        Args:
            runtime: CommandRuntime instance for querying registered commands
        """
        self._runtime = runtime

        # Callback registries
        self._exact_callbacks: dict[str, list[Callable]] = defaultdict(list)
        self._wildcard_callbacks: list[tuple[str, Callable]] = []
        self._lifecycle_callbacks: dict[str, dict[str, Callable]] = {}

    # ========================================================================
    # Pattern Matching
    # ========================================================================

    def matches(self, pattern: str, event_name: str) -> bool:
        """Check if pattern matches event name.

        Supports:
        - Exact: "build" matches "build"
        - Wildcard: "command_*" matches "command_success", "command_failed"
        - Lifecycle: "command_success:*" matches "command_success:Tests"

        Args:
            pattern: The pattern to match against (may contain * wildcards)
            event_name: The event name to match

        Returns:
            True if pattern matches event_name
        """
        # Exact match
        if pattern == event_name:
            return True

        # Wildcard match (convert to regex)
        if "*" not in pattern:
            return False

        # Convert wildcard pattern to regex
        # Escape special regex chars except *, then convert * to .*
        regex_pattern = re.escape(pattern).replace(r"\*", ".*")
        return re.fullmatch(regex_pattern, event_name) is not None

    # ========================================================================
    # Command Matching
    # ========================================================================

    def get_matching_commands(
        self,
        event_name: str,
        trigger_type: Literal["triggers", "cancel_on_triggers"],
    ) -> list[CommandConfig]:
        """Return commands that match this event for the given trigger type.

        Returns exact matches first, then wildcard matches, to ensure
        predictable execution order.

        Args:
            event_name: Event to match against
            trigger_type: "triggers" or "cancel_on_triggers"

        Returns:
            List of CommandConfig objects that match (exact first, then wildcards)
        """
        exact_matches = []
        wildcard_matches = []

        for command_name in self._runtime.list_commands():
            cmd_config = self._runtime.get_command(command_name)
            if not cmd_config:
                continue

            # Get the trigger list for this trigger type
            trigger_list = getattr(cmd_config, trigger_type, [])

            # Check for match
            for trigger in trigger_list:
                if trigger == event_name:
                    exact_matches.append(cmd_config)
                    break
                elif self.matches(trigger, event_name):
                    wildcard_matches.append(cmd_config)
                    break

        return exact_matches + wildcard_matches

    # ========================================================================
    # Callback Matching
    # ========================================================================

    def get_matching_callbacks(self, event_name: str) -> list[tuple[Callable, bool]]:
        """Return callbacks that match this event.

        Returns in dispatch order:
        1. Exact match callbacks (in registration order)
        2. Wildcard match callbacks (in registration order)

        Args:
            event_name: Event to match against

        Returns:
            List of (callback, is_wildcard) tuples in dispatch order
        """
        result = []

        # Exact matches (in registration order)
        for callback in self._exact_callbacks.get(event_name, []):
            result.append((callback, False))

        # Wildcard matches (in registration order)
        for pattern, callback in self._wildcard_callbacks:
            if self.matches(pattern, event_name):
                result.append((callback, True))

        return result

    # ========================================================================
    # Callback Registration
    # ========================================================================

    def register_callback(self, pattern: str, callback: Callable) -> None:
        """Register a callback for events matching pattern.

        Args:
            pattern: Event pattern (may contain * for wildcards)
            callback: Async or sync callable to invoke

        Raises:
            ValueError: If pattern is empty or callback is None
        """
        if not pattern:
            raise ValueError("Pattern cannot be empty")
        if callback is None:
            raise ValueError("Callback cannot be None")

        if "*" in pattern:
            self._wildcard_callbacks.append((pattern, callback))
        else:
            self._exact_callbacks[pattern].append(callback)

    def unregister_callback(self, pattern: str, callback: Callable) -> bool:
        """Remove a callback.

        Args:
            pattern: Event pattern to unregister
            callback: The callback to remove

        Returns:
            True if callback was found and removed, False otherwise
        """
        if "*" in pattern:
            # Wildcard callback
            original_length = len(self._wildcard_callbacks)
            self._wildcard_callbacks = [
                (p, c) for p, c in self._wildcard_callbacks if not (p == pattern and c == callback)
            ]
            return len(self._wildcard_callbacks) < original_length
        else:
            # Exact callback
            if pattern in self._exact_callbacks:
                try:
                    self._exact_callbacks[pattern].remove(callback)
                    return True
                except ValueError:
                    return False
        return False

    def set_lifecycle_callback(
        self,
        command_name: str,
        on_success: Callable | None = None,
        on_failed: Callable | None = None,
        on_cancelled: Callable | None = None,
    ) -> None:
        """Register lifecycle callbacks for a command.

        Lifecycle callbacks are called when a command's run completes.

        Args:
            command_name: Name of the command
            on_success: Callback for successful completion
            on_failed: Callback for failed completion
            on_cancelled: Callback for cancellation
        """
        if command_name not in self._lifecycle_callbacks:
            self._lifecycle_callbacks[command_name] = {}

        if on_success is not None:
            self._lifecycle_callbacks[command_name]["on_success"] = on_success
        if on_failed is not None:
            self._lifecycle_callbacks[command_name]["on_failed"] = on_failed
        if on_cancelled is not None:
            self._lifecycle_callbacks[command_name]["on_cancelled"] = on_cancelled

    def get_lifecycle_callback(
        self, command_name: str, callback_type: Literal["on_success", "on_failed", "on_cancelled"]
    ) -> Callable | None:
        """Get a lifecycle callback for a command.

        Args:
            command_name: Name of the command
            callback_type: Type of callback to retrieve

        Returns:
            The callback if registered, None otherwise
        """
        if command_name not in self._lifecycle_callbacks:
            return None
        return self._lifecycle_callbacks[command_name].get(callback_type)

    # ========================================================================
    # Cycle Detection
    # ========================================================================

    def check_cycle(self, event_name: str, context: TriggerContext) -> bool:
        """Check if event would create a cycle.

        Args:
            event_name: Event to check
            context: TriggerContext with seen set

        Returns:
            True if safe to proceed, False if cycle detected
        """
        return event_name not in context.seen

    def should_track_in_context(self, command_name: str) -> bool:
        """Check if command's triggers should be added to context.seen.

        Returns False if command has loop_detection=False (user is opting out).

        Args:
            command_name: Name of the command

        Returns:
            True if event should be tracked (loop_detection enabled)
        """
        config = self._runtime.get_command(command_name)
        if not config:
            return True  # Default to True for unknown commands
        return config.loop_detection

    # ========================================================================
    # Utilities
    # ========================================================================

    def clear_all_callbacks(self) -> None:
        """Clear all registered callbacks.

        Useful for resetting state between tests or reinitializing.
        """
        self._exact_callbacks.clear()
        self._wildcard_callbacks.clear()
        self._lifecycle_callbacks.clear()

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        exact_count = sum(len(v) for v in self._exact_callbacks.values())
        wildcard_count = len(self._wildcard_callbacks)
        lifecycle_count = sum(len(v) for v in self._lifecycle_callbacks.values())
        return (
            f"TriggerEngine("
            f"exact_callbacks={exact_count}, "
            f"wildcard_callbacks={wildcard_count}, "
            f"lifecycle_callbacks={lifecycle_count})"
        )
