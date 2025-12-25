# cmdorc/command_orchestrator.py
"""
CommandOrchestrator - Main coordinator for command orchestration.

Responsibilities:
- Public API coordination (single entrypoint for users)
- Policy application via ConcurrencyPolicy
- RunHandle registry management
- Auto-trigger emission (lifecycle events)
- Variable resolution coordination
- Graceful shutdown and lifecycle management

Does NOT:
- Manage subprocesses (CommandExecutor does this)
- Store state (CommandRuntime does this)
- Make concurrency decisions (ConcurrencyPolicy does this)
- Pattern match triggers (TriggerEngine does this)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .command_config import CommandConfig, RunnerConfig
from .command_executor import CommandExecutor
from .command_runtime import CommandRuntime
from .concurrency_policy import ConcurrencyPolicy
from .exceptions import (
    CommandNotFoundError,
    ConcurrencyLimitError,
    DebounceError,
    OrchestratorShutdownError,
    TriggerCycleError,
)
from .local_subprocess_executor import LocalSubprocessExecutor
from .run_handle import RunHandle
from .run_result import ResolvedCommand, RunResult, RunState
from .runtime_vars import prepare_resolved_command
from .trigger_engine import TriggerEngine
from .types import CommandStatus, TriggerContext

logger = logging.getLogger(__name__)


class CommandOrchestrator:
    """
    Public coordinator for command orchestration.

    Single entrypoint for users - coordinates CommandRuntime, TriggerEngine,
    ConcurrencyPolicy, and CommandExecutor to provide async-first,
    trigger-driven command orchestration.
    """

    def __init__(
        self,
        runner_config: RunnerConfig,
        executor: CommandExecutor | None = None,
    ) -> None:
        """
        Initialize orchestrator with configuration.

        Args:
            runner_config: RunnerConfig with commands and global variables
            executor: Optional custom executor (defaults to LocalSubprocessExecutor)

        Raises:
            ValueError: If RunnerConfig is invalid
        """
        # Core components
        self._runtime = CommandRuntime()
        self._trigger_engine = TriggerEngine(self._runtime)
        self._policy = ConcurrencyPolicy()

        # Global variables from RunnerConfig
        self._global_vars = runner_config.vars.copy()

        # Output storage configuration
        self._output_storage = runner_config.output_storage

        # Create executor with output storage config if not provided
        if executor is None:
            from .local_subprocess_executor import LocalSubprocessExecutor

            executor = LocalSubprocessExecutor(output_storage=self._output_storage)

        self._executor = executor

        # Handle registry: run_id -> RunHandle
        self._handles: dict[str, RunHandle] = {}
        self._handles_lock = asyncio.Lock()

        # Orchestrator-level lock for critical sections
        # Prevents races in high-concurrency scenarios
        self._orchestrator_lock = asyncio.Lock()

        # Lifecycle state
        self._is_shutdown = False

        # Register all commands from config
        for config in runner_config.commands:
            self._runtime.register_command(config)

        logger.debug(
            f"Initialized CommandOrchestrator with {len(runner_config.commands)} commands "
            f"(output_storage_enabled={self._output_storage.is_enabled})"
        )

    # ========================================================================
    # Execution: Manual
    # ========================================================================

    async def run_command(
        self,
        name: str,
        vars: dict[str, str] | None = None,
    ) -> RunHandle:
        """
        Execute a command manually.

        Steps:
        1. Check shutdown state
        2. Acquire orchestrator lock for critical section
        3. Verify command registered
        4. Prepare run (merge vars, create ResolvedCommand)
        5. Apply policy (includes debounce check)
        6. Cancel runs if needed (retrigger policy)
        7. Register in runtime
        8. Create and register handle
        9. Release lock
        10. Emit command_started trigger (background)
        11. Start executor
        12. Start monitoring task
        13. Return handle immediately

        Args:
            name: Command name
            vars: Optional call-time variables (override config vars)

        Returns:
            RunHandle for the started run

        Raises:
            OrchestratorShutdownError: If orchestrator is shutting down
            CommandNotFoundError: If command not registered
            DebounceError: If command in debounce window
            ConcurrencyLimitError: If policy denies run
        """
        # Check shutdown state
        if self._is_shutdown:
            raise OrchestratorShutdownError("Orchestrator is shutting down")

        # Acquire orchestrator lock for critical section
        async with self._orchestrator_lock:
            # Verify command registered
            config = self._runtime.get_command(name)
            if config is None:
                raise CommandNotFoundError(f"Command '{name}' not registered")

            # Enforce output file retention policy before starting new run
            self._enforce_output_retention(name)

            # Prepare run (merge vars, create ResolvedCommand + RunResult)
            resolved, result = self._prepare_run(config, vars, trigger_event=None)

            # Apply policy (includes debounce check via last_start_time)
            active_runs = self._runtime.get_active_runs(name)
            last_start_time = self._runtime._last_start.get(name)
            decision = self._policy.decide(config, active_runs, last_start_time)

            if not decision.allow:
                logger.debug(f"Policy denied '{name}': {decision.disallow_reason}")
                if decision.disallow_reason == "debounce":
                    raise DebounceError(name, config.debounce_in_ms, decision.elapsed_ms)
                elif decision.disallow_reason == "concurrency_limit":
                    raise ConcurrencyLimitError(
                        name,
                        len(active_runs),
                        config.max_concurrent,
                        config.on_retrigger,
                    )
                else:
                    # This will be a type error if we ever add a new reason without handling it
                    raise RuntimeError(f"Unknown disallow reason in {decision}")

            # Cancel runs if needed (retrigger policy)
            for run_to_cancel in decision.runs_to_cancel:
                await self._cancel_run_internal(run_to_cancel, "retrigger policy")

            # Register in runtime
            self._runtime.add_live_run(result)

            # Create and register handle
            handle = RunHandle(result)
            self._handles[result.run_id] = handle

        # Release lock before starting executor and emitting triggers

        # Emit command_started trigger (non-blocking background task)
        asyncio.create_task(self._emit_auto_trigger(f"command_started:{name}", handle))

        # Start executor (non-blocking)
        try:
            await self._executor.start_run(result, resolved)
        except Exception as e:
            # If executor.start_run() fails, mark as failed and unregister
            result.mark_failed(str(e))
            self._runtime.mark_run_complete(result)
            await self._unregister_handle(result.run_id)
            raise

        # Start monitoring task
        asyncio.create_task(self._monitor_run(result, handle))

        logger.debug(
            f"Started command '{name}' (run_id={result.run_id})",
            extra={"command_name": name, "run_id": result.run_id},
        )

        return handle

    # ========================================================================
    # Execution: Triggered
    # ========================================================================

    async def trigger(
        self,
        event_name: str,
        context: TriggerContext | None = None,
    ) -> None:
        """
        Fire a trigger event.

        Executes matching commands and invokes callbacks.
        Handles cycle detection and shutdown state automatically.

        Steps:
        1. Check shutdown state
        2. Acquire orchestrator lock for critical section
        3. Create/validate TriggerContext
        4. Check cycle detection
        5. Add event to context.seen (for cycle prevention)
        6. Release lock
        7. Handle cancel_on_triggers matches
        8. Handle triggers matches
        9. Dispatch callbacks

        Args:
            event_name: Event to trigger (e.g., "file_saved", "command_success:Tests")
            context: Optional TriggerContext for cycle prevention

        Raises:
            OrchestratorShutdownError: If orchestrator is shutting down
            TriggerCycleError: If cycle detected (when loop_detection=True)
        """
        # Check shutdown state
        if self._is_shutdown:
            raise OrchestratorShutdownError("Orchestrator is shutting down")

        # Acquire orchestrator lock for critical section (context.seen and context.history)
        async with self._orchestrator_lock:
            # Create or use provided context
            if context is None:
                context = TriggerContext(seen=set(), history=[])

            # Check cycle detection
            if not self._trigger_engine.check_cycle(event_name, context):
                raise TriggerCycleError(event_name, context.history)

            # Add event to context.seen immediately (cycle prevention) and context.history (breadcrumb)
            context.seen.add(event_name)
            context.history.append(event_name)

        # Release lock before executing commands/callbacks

        logger.debug(f"Trigger: {event_name} (chain: {' -> '.join(context.history)})")

        # Handle cancel_on_triggers matches
        cancel_matches = self._trigger_engine.get_matching_commands(
            event_name, "cancel_on_triggers"
        )
        for config in cancel_matches:
            try:
                await self.cancel_command(config.name, f"cancel_on_trigger:{event_name}")
            except Exception as e:
                logger.exception(
                    f"Error cancelling command '{config.name}' for trigger '{event_name}': {e}"
                )
                continue

        # Handle triggers matches (execute matching commands)
        trigger_matches = self._trigger_engine.get_matching_commands(event_name, "triggers")
        for config in trigger_matches:
            try:
                await self._trigger_run_command(config, event_name, context)
            except (DebounceError, ConcurrencyLimitError) as e:
                logger.debug(
                    f"Command '{config.name}' not started from trigger '{event_name}': {e}"
                )
                continue
            except Exception as e:
                logger.exception(
                    f"Error starting command '{config.name}' from trigger '{event_name}': {e}"
                )
                continue

        # Dispatch callbacks
        await self._dispatch_callbacks(event_name, None, context)

    # ========================================================================
    # Execution: Helpers
    # ========================================================================

    def _prepare_run(
        self,
        config: CommandConfig,
        call_time_vars: dict[str, str] | None,
        trigger_event: str | None,
        trigger_chain: list[str] | None = None,
    ) -> tuple[ResolvedCommand, RunResult]:
        """
        Prepare resolved command and result container.

        Handles variable resolution via runtime_vars:
        - Phase 1: Merge variables (global → env → command → call-time)
        - Phase 2: Template substitution ({{ var }} and $VAR_NAME)

        Args:
            config: CommandConfig to prepare
            call_time_vars: Optional call-time variable overrides
            trigger_event: Optional trigger event that started this run
            trigger_chain: Optional full trigger chain leading to this run

        Returns:
            Tuple of (ResolvedCommand, RunResult)
        """
        # Use runtime_vars for variable resolution
        resolved = prepare_resolved_command(
            config=config,
            global_vars=self._global_vars,
            call_time_vars=call_time_vars,
            include_env=True,
        )

        # Create empty result container
        result = RunResult(
            command_name=config.name,
            trigger_event=trigger_event,
            trigger_chain=trigger_chain.copy() if trigger_chain else [],
            resolved_command=resolved,
        )

        return resolved, result

    async def _trigger_run_command(
        self,
        config: CommandConfig,
        event_name: str,
        context: TriggerContext,
    ) -> RunHandle:
        """
        Execute a command from trigger, with debounce/policy checks.

        Similar to run_command but:
        - Propagates TriggerContext to auto-triggers
        - May raise DebounceError or ConcurrencyLimitError

        Args:
            config: CommandConfig to execute
            event_name: Event that triggered this
            context: TriggerContext for cycle prevention

        Returns:
            RunHandle if started successfully

        Raises:
            DebounceError: If command in debounce window
            ConcurrencyLimitError: If policy denies run
        """
        # Enforce output file retention policy before starting new run
        self._enforce_output_retention(config.name)

        # Prepare run with trigger chain
        resolved, result = self._prepare_run(
            config, None, event_name, trigger_chain=context.history.copy()
        )

        # Apply policy (includes debounce check)
        active_runs = self._runtime.get_active_runs(config.name)
        last_start_time = self._runtime._last_start.get(config.name)
        decision = self._policy.decide(config, active_runs, last_start_time)

        if not decision.allow:
            # Policy denied - determine reason
            if config.debounce_in_ms > 0 and last_start_time is not None:
                elapsed_ms = (
                    asyncio.get_event_loop().time() * 1000 - last_start_time.timestamp() * 1000
                )
                raise DebounceError(config.name, config.debounce_in_ms, elapsed_ms)
            else:
                raise ConcurrencyLimitError(
                    f"Command '{config.name}' at limit from trigger '{event_name}'"
                )

        # Cancel runs if needed
        for run_to_cancel in decision.runs_to_cancel:
            await self._cancel_run_internal(run_to_cancel, "retrigger policy")

        # Register
        self._runtime.add_live_run(result)
        handle = RunHandle(result)
        async with self._handles_lock:
            self._handles[result.run_id] = handle

        # Start executor
        try:
            await self._executor.start_run(result, resolved)
        except Exception as e:
            # If executor.start_run() fails, mark as failed and unregister
            result.mark_failed(str(e))
            self._runtime.mark_run_complete(result)
            await self._unregister_handle(result.run_id)
            raise

        # Monitor with context propagation
        asyncio.create_task(self._monitor_run(result, handle, context))

        # Emit command_started (propagate context)
        asyncio.create_task(
            self._emit_auto_trigger(f"command_started:{config.name}", handle, context)
        )

        logger.debug(
            f"Triggered command '{config.name}' from event '{event_name}' (run_id={result.run_id})"
        )

        return handle

    async def _monitor_run(
        self,
        result: RunResult,
        handle: RunHandle,
        context: TriggerContext | None = None,
    ) -> None:
        """
        Monitor run completion and emit lifecycle events.

        This task waits for the run to complete, then:
        - Updates runtime state
        - Emits lifecycle triggers (command_success/failed/cancelled)
        - Dispatches lifecycle callbacks
        - Unregisters handle

        Args:
            result: RunResult to monitor
            handle: RunHandle for queries
            context: Optional TriggerContext for cycle prevention
        """
        try:
            # Wait for completion (event-driven via RunHandle)
            try:
                await handle.wait()
            except Exception as e:
                # Executor failure - mark as failed
                logger.exception(f"Executor error for run {result.run_id}: {e}")
                result.mark_failed(str(e))

            # Update runtime
            try:
                self._runtime.mark_run_complete(result)
            except CommandNotFoundError:
                # Command was removed while running - log but continue
                logger.warning(
                    f"Command '{result.command_name}' was removed while running "
                    f"(run_id={result.run_id})"
                )

            # Determine lifecycle event
            if result.state == RunState.SUCCESS:
                event_name = f"command_success:{result.command_name}"
            elif result.state == RunState.FAILED:
                event_name = f"command_failed:{result.command_name}"
            elif result.state == RunState.CANCELLED:
                event_name = f"command_cancelled:{result.command_name}"
            else:
                logger.warning(f"Unexpected state {result.state} for {result.run_id}")
                return

            # Emit lifecycle trigger (with context if available)
            await self._emit_auto_trigger(event_name, handle, context)

            # Dispatch lifecycle callback
            await self._dispatch_lifecycle_callback(result.command_name, result.state, handle)

            # Unregister handle
            await self._unregister_handle(result.run_id)

            logger.debug(
                f"Completed monitoring for run {result.run_id} "
                f"({result.command_name}, state={result.state})"
            )

        except Exception as e:
            logger.exception(f"Error monitoring run {result.run_id}: {e}")

    async def _emit_auto_trigger(
        self,
        event_name: str,
        handle: RunHandle | None,
        context: TriggerContext | None = None,
    ) -> None:
        """
        Emit automatic lifecycle trigger with cycle prevention.

        Auto-triggers are caught and logged, never raised to caller.

        Args:
            event_name: Event to trigger
            handle: RunHandle for context
            context: Optional TriggerContext for cycle prevention
        """
        try:
            # If no context provided but we have a handle, inherit parent's trigger chain
            if context is None and handle is not None:
                parent_chain = handle._result.trigger_chain
                context = TriggerContext(seen=set(parent_chain), history=parent_chain.copy())

            # Check if we should track in context
            if context is not None:
                # Extract command name from event (e.g., "command_success:Tests" -> "Tests")
                parts = event_name.split(":", 1)
                if len(parts) == 2:
                    command_name = parts[1]
                    if not self._trigger_engine.should_track_in_context(command_name):
                        # loop_detection=False, don't propagate context
                        context = None

            # Trigger (may spawn new runs)
            await self.trigger(event_name, context)

        except TriggerCycleError as e:
            # Expected during cycle prevention
            logger.debug(f"Cycle prevented for {event_name}: {e}")
        except OrchestratorShutdownError:
            # Expected during shutdown - auto-triggers may fire after shutdown begins
            logger.debug(f"Auto-trigger {event_name} skipped (orchestrator shutting down)")
        except Exception as e:
            # Auto-triggers should never crash the orchestrator
            logger.exception(f"Error in auto-trigger {event_name}: {e}")

    async def _dispatch_callbacks(
        self,
        event_name: str,
        handle: RunHandle | None,
        context: Any = None,
    ) -> None:
        """
        Dispatch callbacks for an event.

        Args:
            event_name: Event that occurred
            handle: Optional RunHandle for context
            context: Optional context data
        """
        callbacks = self._trigger_engine.get_matching_callbacks(event_name)

        for callback, _is_wildcard in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(handle, context)
                else:
                    callback(handle, context)
            except Exception as e:
                # Note: For manual triggers, caller can catch. For auto-triggers,
                # exceptions are already caught in _emit_auto_trigger
                logger.exception(f"Error in callback for event '{event_name}': {e}")
                raise

    async def _dispatch_lifecycle_callback(
        self,
        command_name: str,
        state: RunState,
        handle: RunHandle,
    ) -> None:
        """
        Dispatch lifecycle callback based on run state.

        Args:
            command_name: Name of command
            state: Final state of run
            handle: RunHandle for context
        """
        callback_map = {
            RunState.SUCCESS: "on_success",
            RunState.FAILED: "on_failed",
            RunState.CANCELLED: "on_cancelled",
        }

        callback_type = callback_map.get(state)
        if not callback_type:
            return

        callback = self._trigger_engine.get_lifecycle_callback(command_name, callback_type)
        if callback:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(handle, None)
                else:
                    callback(handle, None)
            except Exception as e:
                logger.exception(
                    f"Lifecycle callback {callback_type} for '{command_name}' failed: {e}"
                )

    # ========================================================================
    # Cancellation
    # ========================================================================

    async def cancel_run(
        self,
        run_id: str,
        comment: str | None = None,
    ) -> bool:
        """
        Cancel a specific run by run_id.

        Args:
            run_id: Run ID to cancel
            comment: Optional cancellation reason

        Returns:
            True if run was cancelled, False if not found or already finished
        """
        # Search for run in all commands
        for command_name in self._runtime.list_commands():
            active_runs = self._runtime.get_active_runs(command_name)
            for run in active_runs:
                if run.run_id == run_id:
                    await self._cancel_run_internal(run, comment or "user cancellation")
                    return True

        return False

    async def cancel_command(
        self,
        name: str,
        comment: str | None = None,
    ) -> int:
        """
        Cancel all active runs of a command.

        Args:
            name: Command name
            comment: Optional cancellation reason

        Returns:
            Number of runs cancelled
        """
        self._runtime.verify_registered(name)

        active_runs = self._runtime.get_active_runs(name)
        count = 0

        for run in active_runs:
            await self._cancel_run_internal(run, comment or "cancel_command")
            count += 1

        logger.debug(f"Cancelled {count} run(s) of command '{name}'")
        return count

    async def cancel_all(
        self,
        comment: str | None = None,
    ) -> int:
        """
        Cancel all active runs across all commands.

        Args:
            comment: Optional cancellation reason

        Returns:
            Total number of runs cancelled
        """
        count = 0
        for command_name in self._runtime.list_commands():
            count += await self.cancel_command(command_name, comment or "cancel_all")

        logger.debug(f"Cancelled {count} total run(s)")
        return count

    async def _cancel_run_internal(
        self,
        result: RunResult,
        comment: str,
    ) -> None:
        """
        Internal cancellation helper.

        Calls executor.cancel_run() and lets executor mark result as cancelled.

        Args:
            result: RunResult to cancel
            comment: Cancellation reason
        """
        try:
            await self._executor.cancel_run(result, comment)
        except Exception as e:
            logger.exception(f"Error cancelling run {result.run_id}: {e}")

    # ========================================================================
    # Configuration
    # ========================================================================

    def add_command(self, config: CommandConfig) -> None:
        """
        Add a new command configuration.

        Args:
            config: CommandConfig to add

        Raises:
            ValueError: If command with this name already exists
        """
        self._runtime.register_command(config)
        logger.debug(f"Added command '{config.name}'")

    def remove_command(self, name: str) -> None:
        """
        Remove a command configuration.

        Warning: Active runs will continue but won't be tracked.

        Args:
            name: Command name to remove

        Raises:
            CommandNotFoundError: If command not registered
        """
        self._runtime.remove_command(name)
        logger.debug(f"Removed command '{name}'")

    def update_command(self, config: CommandConfig) -> None:
        """
        Update existing command configuration.

        Active runs continue with old config.

        Args:
            config: New CommandConfig to replace existing

        Raises:
            CommandNotFoundError: If command not registered
        """
        self._runtime.replace_command(config)
        logger.debug(f"Updated command '{config.name}'")

    def reload_all_commands(self, configs: list[CommandConfig]) -> None:
        """
        Replace all commands.

        Clears registry and registers new configs.

        Args:
            configs: List of CommandConfigs to register
        """
        # Clear all commands
        for name in list(self._runtime.list_commands()):
            self._runtime.remove_command(name)

        # Register new configs
        for config in configs:
            self._runtime.register_command(config)

        logger.debug(f"Reloaded {len(configs)} command(s)")

    # ========================================================================
    # Queries
    # ========================================================================

    def list_commands(self) -> list[str]:
        """
        List all registered command names.

        Returns:
            List of command names
        """
        return self._runtime.list_commands()

    def get_status(self, name: str) -> CommandStatus:
        """
        Get rich status for a command.

        Args:
            name: Command name

        Returns:
            CommandStatus with state, active count, and last run

        Raises:
            CommandNotFoundError: If command not registered
        """
        self._runtime.verify_registered(name)
        return self._runtime.get_status(name)

    def get_history(self, name: str, limit: int = 10) -> list[RunResult]:
        """
        Get command execution history.

        Args:
            name: Command name
            limit: Max results to return

        Returns:
            List of RunResults in reverse chronological order

        Raises:
            CommandNotFoundError: If command not registered
        """
        self._runtime.verify_registered(name)
        return self._runtime.get_history(name, limit)

    def preview_command(self, name: str, vars: dict[str, str] | None = None) -> ResolvedCommand:
        """
        Preview what would be executed without actually running the command.

        Resolves all variables and returns the final command that would be executed,
        including the resolved command string, working directory, environment variables,
        timeout, and variable snapshot. Useful for dry-runs, debugging, validation,
        and UI previews.

        Args:
            name: Name of the command to preview
            vars: Optional call-time variable overrides (same as run_command)

        Returns:
            ResolvedCommand with all templates resolved:
                - command: Fully resolved command string
                - cwd: Working directory (or None)
                - env: Merged environment variables
                - timeout_secs: Timeout setting
                - vars: Frozen snapshot of all merged variables

        Raises:
            CommandNotFoundError: If command doesn't exist
            ValueError: If variable resolution fails (missing vars, cycles, etc.)

        Example:
            >>> # Preview before running
            >>> preview = orchestrator.preview_command("Deploy", vars={"env": "staging"})
            >>> print(f"Would run: {preview.command}")
            >>> print(f"In directory: {preview.cwd}")
            >>> print(f"Variables: {preview.vars}")
            >>>
            >>> # Confirm and run
            >>> if user_confirms():
            ...     handle = await orchestrator.run_command("Deploy", vars={"env": "staging"})
        """
        config = self._runtime.get_command(name)
        if not config:
            raise CommandNotFoundError(f"Command '{name}' not found")

        return prepare_resolved_command(
            config=config,
            global_vars=self._global_vars,
            call_time_vars=vars,
            include_env=True,
        )

    # ========================================================================
    # Handle Management
    # ========================================================================

    def get_handle_by_run_id(self, run_id: str) -> RunHandle | None:
        """
        Get handle by run ID.

        Args:
            run_id: Run ID to query

        Returns:
            RunHandle if found, None otherwise
        """
        return self._handles.get(run_id)

    def get_active_handles(self, name: str) -> list[RunHandle]:
        """
        Get all active handles for a command.

        Args:
            name: Command name

        Returns:
            List of active RunHandles for this command
        """
        active_runs = self._runtime.get_active_runs(name)
        active_ids = {r.run_id for r in active_runs}
        return [h for h in self._handles.values() if h.run_id in active_ids]

    def get_all_active_handles(self) -> list[RunHandle]:
        """
        Get all active handles across all commands.

        Returns:
            List of all active RunHandles
        """
        return [h for h in self._handles.values() if not h.is_finalized]

    async def _register_handle(self, handle: RunHandle) -> None:
        """
        Register handle in _handles dict (thread-safe).

        Args:
            handle: RunHandle to register
        """
        async with self._handles_lock:
            self._handles[handle.run_id] = handle

    async def _unregister_handle(self, run_id: str) -> None:
        """
        Remove handle from registry and cleanup.

        Called after run completes.

        Args:
            run_id: Run ID to unregister
        """
        async with self._handles_lock:
            handle = self._handles.pop(run_id, None)
            if handle:
                handle.cleanup()

    # ========================================================================
    # Callbacks
    # ========================================================================

    def on_event(
        self,
        event_pattern: str,
        callback: Callable[[RunHandle | None, Any], Awaitable[None] | None],
    ) -> None:
        """
        Register callback for event pattern.

        Callback will be invoked for all matching events.

        Args:
            event_pattern: Event pattern (supports * wildcards)
            callback: Async or sync callable(handle, context)

        Raises:
            ValueError: If pattern or callback is invalid
        """
        self._trigger_engine.register_callback(event_pattern, callback)
        logger.debug(f"Registered callback for event pattern '{event_pattern}'")

    def off_event(
        self,
        event_pattern: str,
        callback: Callable,
    ) -> None:
        """
        Unregister callback.

        Args:
            event_pattern: Event pattern to unregister
            callback: Callback to remove

        Returns:
            True if callback was found and removed
        """
        success = self._trigger_engine.unregister_callback(event_pattern, callback)
        if success:
            logger.debug(f"Unregistered callback for event pattern '{event_pattern}'")

    def set_lifecycle_callback(
        self,
        name: str,
        on_success: Callable | None = None,
        on_failed: Callable | None = None,
        on_cancelled: Callable | None = None,
    ) -> None:
        """
        Set lifecycle callbacks for a command.

        Callbacks are invoked when a run completes.

        Args:
            name: Command name
            on_success: Callback for successful completion
            on_failed: Callback for failed completion
            on_cancelled: Callback for cancellation
        """
        self._trigger_engine.set_lifecycle_callback(name, on_success, on_failed, on_cancelled)
        logger.debug(f"Set lifecycle callbacks for command '{name}'")

    def _enforce_output_retention(self, command_name: str) -> None:
        """
        Enforce output file retention policy for a command.

        Deletes oldest run directories if count exceeds keep_history setting.
        Called before starting new runs to maintain storage limits.

        Args:
            command_name: Name of command to clean up
        """
        import shutil
        from pathlib import Path

        # Skip if output storage disabled or unlimited
        if not self._output_storage.is_enabled or self._output_storage.keep_history <= 0:
            return

        # Build directory path for this command
        base_dir = Path(self._output_storage.directory)
        command_dir = base_dir / command_name

        if not command_dir.exists():
            return

        # Find all run directories (subdirectories of command_dir)
        try:
            run_dirs = sorted(
                [d for d in command_dir.iterdir() if d.is_dir()],
                key=lambda p: p.stat().st_mtime,  # Sort by modification time
            )
        except OSError as e:
            logger.warning(f"Failed to list run directories for '{command_name}': {e}")
            return

        # Delete oldest if we exceed keep_history
        keep_history = self._output_storage.keep_history
        if len(run_dirs) > keep_history:
            to_delete = run_dirs[:-keep_history]  # Keep the newest N

            for run_dir in to_delete:
                try:
                    shutil.rmtree(run_dir)  # Delete entire directory
                    logger.debug(f"Deleted old run directory: {run_dir}")
                except Exception as e:
                    logger.warning(f"Failed to delete run directory {run_dir}: {e}")

    # ========================================================================
    # Lifecycle: Shutdown & Cleanup
    # ========================================================================

    async def shutdown(
        self,
        timeout: float = 30.0,
        cancel_running: bool = True,
    ) -> dict:
        """
        Gracefully shut down orchestrator.

        Steps:
        1. Set _is_shutdown flag
        2. Optionally cancel all active runs
        3. Wait for completion with timeout using asyncio.gather
        4. Cleanup executor
        5. Cleanup all handles

        Args:
            timeout: Max time to wait for completion (seconds)
            cancel_running: If True, cancel active runs; if False, wait for completion

        Returns:
            Dict with: {cancelled_count, completed_count, timeout_expired}
        """
        if self._is_shutdown:
            logger.warning("Shutdown already called")
            return {"cancelled_count": 0, "completed_count": 0, "timeout_expired": False}

        self._is_shutdown = True
        cancelled_count = 0
        completed_count = 0
        timeout_expired = False

        logger.info("Orchestrator shutdown initiated")

        if cancel_running:
            cancelled_count = await self.cancel_all("orchestrator shutdown")

        # Wait for all active handles with timeout using asyncio.gather
        active_handles = self.get_all_active_handles()
        if active_handles:
            try:
                # Use wait_for with gather to wait for all with timeout
                await asyncio.wait_for(
                    asyncio.gather(
                        *[h.wait() for h in active_handles],
                        return_exceptions=True,
                    ),
                    timeout=timeout,
                )
                completed_count = len(active_handles)
                timeout_expired = False
            except asyncio.TimeoutError:
                timeout_expired = True
                remaining = len(self.get_all_active_handles())
                logger.warning(
                    f"Shutdown timeout after {timeout}s, {remaining} handles still active"
                )
        else:
            timeout_expired = False

        # Cleanup executor
        await self._executor.cleanup()

        # Cleanup all remaining handles
        async with self._handles_lock:
            for handle in list(self._handles.values()):
                handle.cleanup()
            self._handles.clear()

        logger.info(
            f"Orchestrator shutdown complete: "
            f"cancelled={cancelled_count}, completed={completed_count}, "
            f"timeout_expired={timeout_expired}"
        )

        return {
            "cancelled_count": cancelled_count,
            "completed_count": completed_count,
            "timeout_expired": timeout_expired,
        }

    async def cleanup(self) -> None:
        """
        Immediate cleanup without waiting.

        Cancels all runs and cleans up resources.
        """
        await self.shutdown(timeout=0, cancel_running=True)
