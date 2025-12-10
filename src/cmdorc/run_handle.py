"""RunHandle - Public facade for interacting with command runs.

Provides async coordination over a RunResult data container.
RunHandle wraps a RunResult and monitors its completion in a background task,
allowing users to wait for completion asynchronously.

This is a standalone component with no dependencies on CommandOrchestrator.
Cancellation is handled by the orchestrator, not by RunHandle.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from .run_result import RunResult, RunState

logger = logging.getLogger(__name__)


class RunHandle:
    """
    Public facade for interacting with command runs.

    Provides async coordination over a RunResult data container.
    Users should interact with RunHandle; internal components use RunResult.

    RunHandle is responsible for:
    - Providing read-only access to run state via properties
    - Enabling async waiting for completion via wait()
    - Owning the background watcher task that monitors completion

    Cancellation is handled by CommandOrchestrator, not by RunHandle.
    The orchestrator calls executor.cancel_run() directly, and RunHandle
    observes when the result becomes finalized.
    """

    # Internal sentinel to detect if in sync context (no loop)
    _NO_LOOP: Final = object()

    def __init__(self, result: RunResult) -> None:
        """
        Initialize a RunHandle for a RunResult.

        Args:
            result: The RunResult to monitor

        Note:
            The future and completion event are created lazily on first wait()
            if there's no running event loop at init time. This allows RunHandle
            to be created in non-async contexts (e.g., config loading).
        """
        self._result = result

        # These are initialized lazily on first wait()
        self._future: asyncio.Future[RunResult] | None = None
        self._completion_event: asyncio.Event | None = None
        self._watcher_task: asyncio.Task[None] | None = None

        # Try to get loop now — if none, defer all setup
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # Fully defer to wait()

        # If in async context and not finalized, set up event early
        if not result.is_finalized:
            self._setup_completion_event()

    def _setup_completion_event(self) -> None:
        """Set up the Event and register callback on RunResult."""
        if self._completion_event is not None:
            return  # Already set up

        self._completion_event = asyncio.Event()

        # Register callback: when any mark_*() finalizes the result, trigger event
        self._result._set_completion_callback(self._completion_event.set)

        # In case finalization happened between check and now
        if self._result.is_finalized:
            self._completion_event.set()

    async def _watch_completion(self) -> None:
        """
        Background task: wait on the completion event and resolve the future.

        This replaces polling with an efficient event-driven wait.
        The event is set by RunResult when any of:
          mark_success(), mark_failed(), mark_cancelled()
        are called (via _finalize() → callback).
        """
        try:
            # Ensure event exists (in case wait() raced with finalization)
            if self._completion_event is None:
                self._setup_completion_event()

            assert self._completion_event is not None
            await self._completion_event.wait()

            # Resolve future if not already done
            if self._future and not self._future.done():
                self._future.set_result(self._result)
        except asyncio.CancelledError:
            if self._future and not self._future.done():
                self._future.cancel()
            raise

    async def wait(self, timeout: float | None = None) -> RunResult:
        """
        Wait for the run to complete.

        Args:
            timeout: Optional timeout in seconds. If specified and the timeout
                expires before completion, raises asyncio.TimeoutError.

        Returns:
            The completed RunResult

        Raises:
            asyncio.TimeoutError: If timeout expires before completion
        """
        # Lazy initialization: set up future, event, and watcher on first call
        if self._future is None:
            loop = asyncio.get_running_loop()
            self._future = loop.create_future()

            if self._result.is_finalized:
                # Already done — resolve immediately
                self._future.set_result(self._result)
            else:
                # Set up event + watcher
                if self._completion_event is None:
                    self._setup_completion_event()
                self._watcher_task = loop.create_task(self._watch_completion())

        if timeout is not None:
            return await asyncio.wait_for(self._future, timeout)
        return await self._future

    # ========================================================================
    # Properties - Read-Only Access to RunResult
    # ========================================================================

    @property
    def command_name(self) -> str:
        """Name of the command being run."""
        return self._result.command_name

    @property
    def run_id(self) -> str:
        """Unique identifier for this run."""
        return self._result.run_id

    @property
    def state(self) -> RunState:
        """Current state of the run (PENDING, RUNNING, SUCCESS, FAILED, CANCELLED)."""
        return self._result.state

    @property
    def success(self) -> bool | None:
        """
        Whether the run was successful.

        Returns:
            True if successful (exit code 0), False if failed, None if not yet finished
        """
        return self._result.success

    @property
    def output(self) -> str:
        """Standard output from the command."""
        return self._result.output

    @property
    def error(self) -> str | Exception | None:
        """
        Error information if the run failed.

        Can be:
        - str: Error message from the command or system
        - Exception: Python exception that occurred
        - None: If not yet finished or no error
        """
        return self._result.error

    @property
    def duration_str(self) -> str:
        """Human-readable duration of the run (e.g., "1m 23s")."""
        return self._result.duration_str

    @property
    def is_finalized(self) -> bool:
        """Whether the run has finished (success, failed, or cancelled)."""
        return self._result.is_finalized

    @property
    def start_time(self) -> float | None:
        """Unix timestamp when run started, or None if not yet started."""
        return self._result.start_time

    @property
    def end_time(self) -> float | None:
        """Unix timestamp when run ended, or None if not yet finished."""
        return self._result.end_time

    @property
    def comment(self) -> str | None:
        """Optional comment (e.g., cancellation reason)."""
        return self._result.comment

    # ========================================================================
    # Internal Access (Advanced Usage)
    # ========================================================================

    @property
    def _result(self) -> RunResult:
        """Direct access to underlying RunResult (internal use only)."""
        return self.__result

    @_result.setter
    def _result(self, value: RunResult) -> None:
        """Internal setter for RunResult."""
        self.__result = value

    # ========================================================================
    # Representation
    # ========================================================================

    def __repr__(self) -> str:
        """Return a helpful debug representation of the handle."""
        return (
            f"RunHandle(command_name={self.command_name!r}, "
            f"run_id={self.run_id!r}, state={self.state.name})"
        )

    # ========================================================================
    # Cleanup
    # ========================================================================
    def cleanup(self) -> None:
        """Cancel the watcher task if active."""
        if self._watcher_task and not self._watcher_task.done():
            logger.debug(f"Cleanup cancelling watcher task for RunHandle {self}")
            self._watcher_task.cancel()
