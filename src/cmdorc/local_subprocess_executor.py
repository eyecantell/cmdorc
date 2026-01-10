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
from pathlib import Path

from .command_config import OutputStorageConfig
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

    def __init__(
        self, cancel_grace_period: float = 3.0, output_storage: OutputStorageConfig | None = None
    ):
        """
        Initialize the executor.

        Args:
            cancel_grace_period: Seconds to wait for SIGTERM before SIGKILL
            output_storage: Optional output storage configuration
        """
        # Active processes: run_id -> subprocess.Process
        self._processes: dict[str, asyncio.subprocess.Process] = {}

        # Monitor tasks: run_id -> asyncio.Task
        self._tasks: dict[str, asyncio.Task] = {}

        # Cancellation grace period
        self._cancel_grace_period = cancel_grace_period

        # Output storage configuration
        self._output_storage = output_storage or OutputStorageConfig()

        logger.debug(
            f"Initialized LocalSubprocessExecutor ("
            f"cancel_grace_period={cancel_grace_period}s, "
            f"output_storage_enabled={self._output_storage.is_enabled})"
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

            # Update latest_run.toml to reflect RUNNING state
            self.update_latest_run(result)

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
                    # Mark as failed FIRST (before killing, which might get cancelled)
                    result.mark_failed(f"Command timed out after {resolved.timeout_secs} seconds")
                    # Kill the process
                    await self._kill_process(process)
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

            # ===== Write output files if enabled =====
            # Check both global and per-command keep_history settings
            effective_keep_history = (
                resolved.keep_history
                if resolved.keep_history is not None
                else self._output_storage.keep_history
            )
            if effective_keep_history != 0:
                self._write_output_files(result)
            # ===== End file writing =====

        except asyncio.CancelledError:
            # Task was cancelled (likely by cancel_run)
            logger.debug(f"Monitor task for run {run_id[:8]} was cancelled")
            if process and process.returncode is None:
                await self._kill_process(process)

            # ===== Write output files even for cancelled runs (if we captured output) =====
            # Check both global and per-command keep_history settings
            effective_keep_history = (
                resolved.keep_history
                if resolved.keep_history is not None
                else self._output_storage.keep_history
            )
            if effective_keep_history != 0 and result.output:
                self._write_output_files(result)
            # ===== End file writing =====

            # Don't mark as cancelled here - cancel_run() does that
            raise

        except Exception as e:
            # Catch-all for unexpected errors during execution (OSError, UnicodeError, etc.)
            # This prevents the monitoring task from crashing while ensuring the run is marked as failed
            # We use broad Exception catching here defensively - the alternative would be to let
            # exceptions crash the task, but that could leave the run in an inconsistent state
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
        if result.is_finalized:
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

                    # ===== Capture output after graceful exit =====
                    if process.stdout:
                        try:
                            output_bytes = await asyncio.wait_for(
                                process.stdout.read(),
                                timeout=0.5,  # Short timeout to read buffered output
                            )
                            if output_bytes:
                                result.output = output_bytes.decode("utf-8", errors="replace")
                                logger.debug(
                                    f"Captured {len(result.output)} bytes of output "
                                    f"before cancellation of run {run_id[:8]}"
                                )
                        except asyncio.TimeoutError:
                            logger.debug(f"No output available to capture for run {run_id[:8]}")
                        except Exception as e:
                            logger.debug(f"Could not capture output for run {run_id[:8]}: {e}")
                    # ===== End output capture =====

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

    def _build_output_path(self, result: RunResult) -> Path:
        """
        Build output directory path using fixed pattern.

        Args:
            result: The RunResult to build path for

        Returns:
            Path to directory for this run (contains metadata.toml and output file)
        """
        from .command_config import OUTPUT_PATTERN

        # Substitute pattern variables to get directory path
        dir_path = OUTPUT_PATTERN.format(command_name=result.command_name, run_id=result.run_id)

        # Build full path
        base_dir = Path(self._output_storage.directory)
        return base_dir / dir_path

    def _write_output_files(self, result: RunResult) -> None:
        """
        Write output and metadata files for a completed run.

        Creates directory structure based on pattern, then writes:
            - metadata.toml: Run metadata (includes output_extension for parser)
            - output{extension}: Command output

        Args:
            result: The RunResult to persist

        Note: Errors are logged but don't fail the run.
        """
        try:
            # Get run directory from pattern
            run_dir = self._build_output_path(result)

            # Create directory
            run_dir.mkdir(parents=True, exist_ok=True)

            # Get effective output extension (command override or global default)
            output_extension = (
                result.resolved_command.output_extension
                if result.resolved_command and result.resolved_command.output_extension is not None
                else self._output_storage.output_extension
            )

            # Write output file with configurable extension
            output_filename = f"output{output_extension}"
            output_path = run_dir / output_filename
            output_path.write_text(result.output or "", encoding="utf-8")

            # Set file paths on result BEFORE to_toml() so they're included in metadata
            metadata_path = run_dir / "metadata.toml"
            result.output_file = output_path
            result.metadata_file = metadata_path

            # Write metadata file (includes output_file name for parser)
            metadata_path.write_text(result.to_toml(), encoding="utf-8")

            # Update latest_run.toml to reflect this run's completion
            # External observers can check this file without traversing run_ids
            self.update_latest_run(result)

            logger.debug(f"Wrote output files to {run_dir}")

        except Exception as e:
            error_msg = f"Failed to write output files: {e}"
            logger.error(f"{error_msg} for run {result.run_id[:8]}")
            result.output_write_error = error_msg
            # Don't re-raise - file writing errors shouldn't fail the run

    def _write_latest_run_toml(self, command_name: str, toml_content: str) -> None:
        """
        Write latest_run.toml atomically to command directory.

        This file always reflects the most recent run's state, making it easy
        for external observers to check command status without traversing runs.

        Uses atomic write (temp file + rename) to prevent partial reads.

        Note: With max_concurrent > 1, concurrent runs race to update this file.
        The last run to write wins. This is safe but non-deterministic.

        Args:
            command_name: Name of the command
            toml_content: TOML content to write
        """
        if not self._output_storage or not self._output_storage.is_enabled:
            return

        # Build command directory path
        command_dir = Path(self._output_storage.directory) / command_name
        command_dir.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file, then rename
        latest_path = command_dir / "latest_run.toml"
        temp_path = latest_path.with_suffix(".toml.tmp")

        try:
            temp_path.write_text(toml_content, encoding="utf-8")
            temp_path.rename(latest_path)  # Atomic on POSIX
            logger.debug(f"Updated {latest_path}")
        except OSError as e:
            logger.error(f"Failed to write latest_run.toml for {command_name}: {e}")
        finally:
            # Clean up temp file if rename failed
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def update_latest_run(self, result: RunResult) -> None:
        """
        Update latest_run.toml with current run state.

        This file always reflects the most recent run's state, making it easy
        for external observers to check command status without traversing runs.

        Can be called at any point in the run lifecycle:
        - PENDING: Run accepted, not yet started
        - RUNNING: Subprocess executing
        - SUCCESS/FAILED/CANCELLED: Run completed

        Note: With max_concurrent > 1, concurrent runs race to update this file.
        The last run to write wins. This is safe but non-deterministic.

        Args:
            result: The RunResult to write to latest_run.toml
        """
        if not self._output_storage or not self._output_storage.is_enabled:
            return

        toml_content = result.to_toml()
        self._write_latest_run_toml(result.command_name, toml_content)

    def __repr__(self) -> str:
        active = len(self._processes)
        return (
            f"LocalSubprocessExecutor("
            f"active_processes={active}, "
            f"cancel_grace_period={self._cancel_grace_period}s)"
        )
