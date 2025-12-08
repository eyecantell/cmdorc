# cmdorc/command_executor.py
"""
CommandExecutor - Abstract interface for command execution backends.

The executor owns the lifecycle of subprocesses/tasks:
- Starting runs
- Monitoring execution
- Capturing output
- Handling timeouts
- Cancelling runs
- Cleanup on shutdown

The executor receives fully resolved commands (ResolvedCommand) and
updates RunResult objects as execution progresses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging

from .run_result import RunResult, ResolvedCommand

logger = logging.getLogger(__name__)


class CommandExecutor(ABC):
    """
    Abstract base class for command execution backends.
    
    Implementations might include:
    - LocalSubprocessExecutor (default)
    - SSHExecutor (remote execution)
    - DockerExecutor (containerized execution)
    - K8sExecutor (kubernetes jobs)
    - MockExecutor (testing)
    """

    @abstractmethod
    async def start_run(
        self,
        result: RunResult,
        resolved: ResolvedCommand,
    ) -> None:
        """
        Start execution and take ownership of the RunResult.
        
        This method should:
        1. Call result.mark_running() when execution starts
        2. Launch the subprocess/task/job
        3. Monitor execution asynchronously
        4. Capture output into result.output
        5. Call result.mark_success/failed/cancelled() on completion
        6. Handle timeouts from resolved.timeout_secs
        
        Args:
            result: Empty RunResult container to populate
            resolved: Fully resolved command settings (no templates)
        
        Returns:
            None - this method returns immediately after starting.
            The executor continues monitoring in the background.
            
        Note:
            This method should NOT block waiting for completion.
            Create a background task/thread to monitor the process.
        """
        ...

    @abstractmethod
    async def cancel_run(
        self,
        result: RunResult,
        comment: str | None = None,
    ) -> None:
        """
        Cancel a running execution.
        
        This method should:
        1. Send termination signal to the process (SIGTERM, then SIGKILL)
        2. Wait for cleanup
        3. Call result.mark_cancelled(comment)
        
        Must be idempotent - safe to call multiple times.
        Should be a no-op if the run is already finished.
        
        Args:
            result: The RunResult to cancel
            comment: Optional reason for cancellation
            
        Returns:
            None - cancellation may be asynchronous but this should
            wait until the process is actually stopped.
        """
        ...

    def supports_feature(self, feature: str) -> bool:
        """
        Check if executor supports optional features.
        
        Features might include:
        - "streaming_output": Real-time output capture
        - "signal_handling": Custom signal support
        - "resource_limits": CPU/memory constraints
        - "pause_resume": Pausing execution
        
        Args:
            feature: Feature name to check
            
        Returns:
            True if feature is supported
        """
        return False

    async def cleanup(self) -> None:
        """
        Clean up any resources on shutdown.
        
        Called by orchestrator during graceful shutdown.
        Should cancel any running processes and release resources.
        
        Default implementation does nothing.
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"