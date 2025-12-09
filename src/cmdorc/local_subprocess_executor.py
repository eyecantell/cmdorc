# cmdorc/local_subprocess_executor.py
"""
LocalSubprocessExecutor - Default executor using asyncio subprocesses.

Executes commands as local subprocesses with:
- Output capture (stdout + stderr merged)
- Timeout handling
- Graceful cancellation (SIGTERM → SIGKILL)
- Background monitoring tasks
"""

from __future__ import annotations

import asyncio
import logging
import os

from .command_executor import CommandExecutor
from .run_result import ResolvedCommand, RunResult

logger = logging.getLogger(__name__)


class LocalSubprocessExecutor(CommandExecutor):
    """
    Executes commands as local subprocesses using asyncio.

    Features:
    - Non-blocking execution
    - Output capture (stdout + stderr merged)
    - Timeout enforcement
    - Graceful cancellation (SIGTERM, then SIGKILL after grace period)
    - Automatic cleanup on shutdown
    """

    def __init__(self, cancel_grace_period: float = 3.0):
        """
        Initialize the executor.

        Args:
            cancel_grace_period: Seconds to wait for SIGTERM before SIGKILL
        """
        # Active processes: run_id -> subprocess.Process
        self._processes: dict[str, asyncio.subprocess.Process] = {}

        # Monitor tasks: run_id -> asyncio.Task
        self._tasks: dict[str, asyncio.Task] = {}

        # Cancellation grace period
        self._cancel_grace_period = cancel_grace_period

        logger.debug(
            f"Initialized LocalSubprocessExecutor (cancel_grace_period={cancel_grace_period}s)"
        )

    async def start_run(
        self,
        result: RunResult,
        resolved: ResolvedCommand,
    ) -> None:
        """
        Start a subprocess and monitor it in the background.

        Creates a monitoring task that:
        1. Launches the subprocess
        2. Marks result as RUNNING
        3. Waits for completion (with timeout)
        4. Captures output
        5. Marks result as SUCCESS/FAILED
        6. Cleans up internal state
        """
        run_id = result.run_id

        # Create and start monitoring task
        task = asyncio.create_task(
            self._monitor_process(result, resolved), name=f"monitor_{run_id[:8]}"
        )

        self._tasks[run_id] = task

        logger.debug(
            f"Started monitoring task for run {run_id[:8]} (command='{result.command_name}')"
        )

    async def _monitor_process(
        self,
        result: RunResult,
        resolved: ResolvedCommand,
    ) -> None:
        """
        Monitor a subprocess from start to completion.

        This runs in a background task and handles the entire lifecycle.
        """
        run_id = result.run_id
        process = None

        try:
            # Launch subprocess
            logger.debug(f"Launching subprocess for run {run_id[:8]}")

            process = await asyncio.create_subprocess_shell(
                resolved.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                cwd=resolved.cwd,
                env=resolved.env,
                # Start in new process group for better signal handling
                preexec_fn=os.setpgrp if os.name != "nt" else None,
            )

            # Store process reference
            self._processes[run_id] = process

            # Mark as running
            result.mark_running()

            # Wait for completion (with optional timeout)
            if resolved.timeout_secs:
                logger.debug(f"Run {run_id[:8]} has timeout of {resolved.timeout_secs}s")
                try:
                    stdout, _ = await asyncio.wait_for(
                        process.communicate(),
                        timeout=resolved.timeout_secs,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Run {run_id[:8]} timed out after {resolved.timeout_secs}s")
                    # Kill the process
                    await self._kill_process(process)
                    result.mark_failed(f"Command timed out after {resolved.timeout_secs} seconds")
                    return
            else:
                # No timeout
                stdout, _ = await process.communicate()

            # Capture output
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            result.output = output

            # Check return code
            if process.returncode == 0:
                result.mark_success()
                logger.debug(
                    f"Run {run_id[:8]} completed successfully (output={len(output)} bytes)"
                )
            else:
                error_msg = f"Command exited with code {process.returncode}"
                result.mark_failed(error_msg)
                logger.debug(f"Run {run_id[:8]} failed: {error_msg} (output={len(output)} bytes)")

        except asyncio.CancelledError:
            # Task was cancelled (likely by cancel_run)
            logger.debug(f"Monitor task for run {run_id[:8]} was cancelled")
            if process and process.returncode is None:
                await self._kill_process(process)
            # Don't mark as cancelled here - cancel_run() does that
            raise

        except Exception as e:
            # Unexpected error during execution
            logger.exception(f"Unexpected error monitoring run {run_id[:8]}: {e}")
            result.mark_failed(e)

        finally:
            # Clean up internal state
            self._processes.pop(run_id, None)
            self._tasks.pop(run_id, None)
            logger.debug(f"Cleaned up internal state for run {run_id[:8]}")

    async def cancel_run(
        self,
        result: RunResult,
        comment: str | None = None,
    ) -> None:
        """
        Cancel a running subprocess.

        Strategy:
        1. Send SIGTERM (graceful)
        2. Wait for grace period
        3. Send SIGKILL if still running (forceful)
        4. Cancel the monitoring task
        5. Mark result as cancelled
        """
        run_id = result.run_id

        # Check if already finished
        if result.is_finished:
            logger.debug(f"Run {run_id[:8]} already finished, nothing to cancel")
            return

        # Get process and task
        process = self._processes.get(run_id)
        task = self._tasks.get(run_id)

        if not process and not task:
            logger.warning(f"Run {run_id[:8]} not found in active processes/tasks")
            # Mark as cancelled anyway
            result.mark_cancelled(comment or "Command cancelled (not found)")
            return

        logger.info(f"Cancelling run {run_id[:8]}")

        # Try graceful termination first
        if process and process.returncode is None:
            try:
                logger.debug(f"Sending SIGTERM to run {run_id[:8]}")
                process.terminate()  # SIGTERM

                # Wait for grace period
                try:
                    await asyncio.wait_for(process.wait(), timeout=self._cancel_grace_period)
                    logger.debug(f"Run {run_id[:8]} terminated gracefully")
                except asyncio.TimeoutError:
                    # Still running, send SIGKILL
                    logger.warning(f"Run {run_id[:8]} didn't terminate, sending SIGKILL")
                    await self._kill_process(process)

            except ProcessLookupError:
                # Process already died
                logger.debug(f"Process for run {run_id[:8]} already dead")

        # Cancel the monitoring task
        if task and not task.done():
            logger.debug(f"Cancelling monitor task for run {run_id[:8]}")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Mark result as cancelled
        result.mark_cancelled(comment or "Command cancelled")

        # Clean up internal state
        self._processes.pop(run_id, None)
        self._tasks.pop(run_id, None)

    async def _kill_process(self, process: asyncio.subprocess.Process) -> None:
        """
        Forcefully kill a process with SIGKILL.

        Args:
            process: The process to kill
        """
        try:
            process.kill()  # SIGKILL
            await process.wait()  # Ensure it's dead
        except ProcessLookupError:
            # Already dead
            pass

    async def cleanup(self) -> None:
        """
        Clean up all running processes on shutdown.

        Cancels all active runs gracefully.
        """
        if not self._processes and not self._tasks:
            logger.debug("No active processes to clean up")
            return

        logger.info(
            f"Cleaning up {len(self._processes)} active processes "
            f"and {len(self._tasks)} monitor tasks"
        )

        # Cancel all monitoring tasks
        for run_id, task in list(self._tasks.items()):
            if not task.done():
                logger.debug(f"Cancelling monitor task for run {run_id[:8]}")
                task.cancel()

        # Kill all processes
        for run_id, process in list(self._processes.items()):
            if process.returncode is None:
                logger.debug(f"Killing process for run {run_id[:8]}")
                try:
                    await self._kill_process(process)
                except Exception as e:
                    logger.warning(f"Error killing process for run {run_id[:8]}: {e}")

        # Wait for all tasks to finish
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        # Clear state
        self._processes.clear()
        self._tasks.clear()

        logger.info("Cleanup complete")

    def supports_feature(self, feature: str) -> bool:
        """Check if executor supports optional features."""
        supported = {
            "timeout",
            "output_capture",
            "signal_handling",
            "graceful_cancellation",
        }
        return feature in supported

    def __repr__(self) -> str:
        active = len(self._processes)
        return (
            f"LocalSubprocessExecutor("
            f"active_processes={active}, "
            f"cancel_grace_period={self._cancel_grace_period}s)"
        )
