# cmdorc/mock_executor.py
"""
MockExecutor - Test double for CommandExecutor.

Simulates command execution without actually running subprocesses.
Useful for unit testing orchestrator logic without OS dependencies.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple

from .command_executor import CommandExecutor
from .run_result import RunResult, ResolvedCommand

logger = logging.getLogger(__name__)


class MockExecutor(CommandExecutor):
    """
    Mock executor for testing.
    
    Records all calls and simulates execution with configurable behavior.
    """

    def __init__(
        self,
        delay: float = 0.0,
        should_fail: bool = False,
        failure_message: str = "Simulated failure",
        simulated_output: str = "Simulated output",
    ):
        """
        Initialize mock executor.
        
        Args:
            delay: Simulated execution time in seconds
            should_fail: If True, all runs will fail
            failure_message: Error message for failed runs
            simulated_output: Output text for successful runs
        """
        self.delay = delay
        self.should_fail = should_fail
        self.failure_message = failure_message
        self.simulated_output = simulated_output
        
        # Records of calls
        self.started: List[Tuple[RunResult, ResolvedCommand]] = []
        self.cancelled: List[Tuple[RunResult, str | None]] = []
        self.cleaned_up: bool = False
        
        # Active monitoring tasks
        self._tasks: dict[str, asyncio.Task] = {}

    async def start_run(
        self,
        result: RunResult,
        resolved: ResolvedCommand,
    ) -> None:
        """
        Simulate command execution.
        
        Records the call and simulates execution in background task.
        """
        self.started.append((result, resolved))
        
        # Create monitoring task
        task = asyncio.create_task(self._simulate_run(result, resolved))
        self._tasks[result.run_id] = task

    async def _simulate_run(
        self,
        result: RunResult,
        resolved: ResolvedCommand,
    ) -> None:
        """Simulate a command run."""
        try:
            # Mark as running
            result.mark_running()
            
            # Simulate execution time
            if self.delay > 0:
                await asyncio.sleep(self.delay)
            
            # Simulate result
            if self.should_fail:
                result.mark_failed(self.failure_message)
            else:
                result.output = self.simulated_output
                result.mark_success()
        
        except asyncio.CancelledError:
            # Task was cancelled
            if not result.is_finished:
                result.mark_cancelled("Simulated cancellation")
            raise
        
        finally:
            # Clean up
            self._tasks.pop(result.run_id, None)

    async def cancel_run(
        self,
        result: RunResult,
        comment: str | None = None,
    ) -> None:
        """
        Simulate cancellation.
        
        Records the call and cancels the monitoring task.
        """
        self.cancelled.append((result, comment))
        
        # Cancel monitoring task if it exists
        task = self._tasks.get(result.run_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Mark as cancelled if not already finished
        if not result.is_finished:
            result.mark_cancelled(comment or "Mock cancellation")

    async def cleanup(self) -> None:
        """Record cleanup call."""
        self.cleaned_up = True
        
        # Cancel all active tasks
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        
        self._tasks.clear()

    def supports_feature(self, feature: str) -> bool:
        """Mock supports everything."""
        return True

    def reset(self) -> None:
        """Clear all recorded calls (useful between tests)."""
        self.started.clear()
        self.cancelled.clear()
        self.cleaned_up = False

    def __repr__(self) -> str:
        return (
            f"MockExecutor("
            f"started={len(self.started)}, "
            f"cancelled={len(self.cancelled)}, "
            f"delay={self.delay}s, "
            f"should_fail={self.should_fail})"
        )