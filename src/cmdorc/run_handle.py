"""RunHandle - Public facade for interacting with command runs.

Provides async coordination over a RunResult data container.
RunHandle wraps a RunResult and monitors its completion in a background task,
allowing users to wait for completion asynchronously.

This is a standalone component with no dependencies on CommandOrchestrator.
Cancellation is handled by the orchestrator, not by RunHandle.
"""

from __future__ import annotations

import asyncio

from .run_result import RunResult, RunState


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

    def __init__(self, result: RunResult) -> None:
        """
        Initialize a RunHandle for a RunResult.

        Args:
            result: The RunResult to monitor

        Note:
            The watcher task is created lazily on first wait() call if there's
            no running event loop at init time. This allows RunHandle to be
            created in non-async contexts.
        """
        self._result = result
        self._future: asyncio.Future[RunResult] | None = None
        self._watcher_task: asyncio.Task[None] | None = None

        # If result is already finished, we can set it up immediately
        # Otherwise we'll initialize the future on first wait()
        if result.is_finalized:
            self._future = asyncio.Future()
            self._future.set_result(result)

    async def _watch_completion(self) -> None:
        """
        Background task that monitors result completion.

        Polls result.is_finalized every 0.05 seconds and completes the future
        when the run finishes. Handles cancellation gracefully.
        """
        try:
            # Poll with 0.05s interval (balance responsiveness vs CPU)
            while not self._result.is_finalized:
                await asyncio.sleep(0.05)

            # Complete the future
            if not self._future.done():
                self._future.set_result(self._result)
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            if not self._future.done():
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
        # Initialize future and watcher on first wait() if not yet done
        if self._future is None:
            self._future = asyncio.Future()
            if not self._result.is_finalized:
                self._watcher_task = asyncio.create_task(self._watch_completion())
            else:
                self._future.set_result(self._result)

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
