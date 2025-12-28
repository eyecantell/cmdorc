# cmdorc/run_result.py
from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .utils import format_duration

logger = logging.getLogger(__name__)


class RunState(Enum):
    """Possible states of a command execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ResolvedCommand:
    """Snapshot of resolved command settings at execution time."""

    command: str
    cwd: str | None
    env: dict[str, str]
    timeout_secs: int | None
    vars: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "command": self.command,
            "cwd": self.cwd,
            "env": self.env.copy(),
            "timeout_secs": self.timeout_secs,
            "vars": self.vars.copy(),
        }


@dataclass
class RunResult:
    """
    Represents a single execution of a command.

    Pure data container used by CommandRuntime and CommandExecutor.
    Users interact with it via the public RunHandle façade.

    Note: This is mutable to allow state transitions during execution,
    but should be treated as immutable once is_finalized=True.
    """

    # ------------------------------------------------------------------ #
    # Identification
    # ------------------------------------------------------------------ #
    command_name: str
    """Name of the command being executed."""

    run_id: str = field(default_factory=lambda: str(__import__("uuid").uuid4()))
    """Unique identifier for this run."""

    trigger_event: str | None = None
    """Event that triggered this run (e.g. "file_saved", "Tests")."""

    trigger_chain: list[str] = field(default_factory=list)
    """Ordered list of trigger events leading to this run.

    Examples:
      - [] = manually started via run_command()
      - ["user_saves"] = triggered directly by user_saves event
      - ["user_saves", "command_success:Lint"] = chained trigger

    The last element matches trigger_event (if trigger_event is not None).
    Immutable after finalization (treat as read-only).
    """

    # ------------------------------------------------------------------ #
    # Execution output & result
    # ------------------------------------------------------------------ #
    output: str = ""
    """Captured stdout + stderr."""

    success: bool | None = None
    """True = success, False = failed, None = cancelled/pending."""

    error: str | Exception | None = None
    """Error message or exception if failed."""

    state: RunState = RunState.PENDING

    # ------------------------------------------------------------------ #
    # Timing
    # ------------------------------------------------------------------ #
    start_time: datetime.datetime | None = None
    end_time: datetime.datetime | None = None
    duration: datetime.timedelta | None = None

    # ------------------------------------------------------------------ #
    # Resolved configuration snapshots (set by CommandExecutor.start_run)
    # ------------------------------------------------------------------ #
    resolved_command: ResolvedCommand | None = None
    """Command settings after variable resolution."""

    # ------------------------------------------------------------------ #
    # Output file paths (set by CommandExecutor if output_storage enabled)
    # ------------------------------------------------------------------ #
    metadata_file: Path | None = None
    """Path to metadata TOML file (if output_storage enabled)."""

    output_file: Path | None = None
    """Path to output text file (if output_storage enabled)."""

    # ------------------------------------------------------------------ #
    # Comment
    # ------------------------------------------------------------------ #
    comment: str = ""
    """Comment or note about this run (for logging/debugging)."""

    # ------------------------------------------------------------------ #
    # Internal callback for run finalization
    # ------------------------------------------------------------------ #
    _completion_callback: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    _is_finalized: bool = field(init=False, default=False)
    """Internal flag set by _finalize()."""

    # ------------------------------------------------------------------ #
    # State transitions
    # ------------------------------------------------------------------ #
    def mark_running(self, comment: str = None) -> None:
        """Transition to RUNNING and record start time."""
        self.state = RunState.RUNNING
        self.start_time = datetime.datetime.now()
        if comment is not None:
            self.comment = comment
        logger.debug(f"Run {self.run_id[:8]} ('{self.command_name}') started")

    def mark_success(self, comment: str = None) -> None:
        """Mark as successfully completed."""
        self.state = RunState.SUCCESS
        self.success = True
        self._finalize()
        if comment is not None:
            self.comment = comment
        logger.debug(
            f"Run {self.run_id[:8]} ('{self.command_name}') succeeded in {self.duration_str}"
        )

    def mark_failed(self, error: str | Exception, comment: str = None) -> None:
        """Mark as failed."""
        self.state = RunState.FAILED
        self.success = False
        self.error = error
        self._finalize()
        if comment is not None:
            self.comment = comment
        msg = str(error) if isinstance(error, Exception) else error
        logger.debug(f"Run {self.run_id[:8]} ('{self.command_name}') failed: {msg}")

    def mark_cancelled(self, comment: str = None) -> None:
        """Mark as cancelled."""
        self.state = RunState.CANCELLED
        self.success = None
        self._finalize()
        if comment is not None:
            self.comment = comment
        logger.debug(f"Run {self.run_id[:8]} ('{self.command_name}') cancelled")

    # ------------------------------------------------------------------ #
    # Finalization
    # ------------------------------------------------------------------ #
    def _finalize(self) -> None:
        """Record end time and compute duration."""
        self._is_finalized = True

        self.end_time = datetime.datetime.now()
        if self.start_time:
            self.duration = self.end_time - self.start_time
        else:
            self.duration = datetime.timedelta(0)

        if self._completion_callback:
            self._completion_callback()

    # ------------------------------------------------------------------ #
    # Timing properties
    # ------------------------------------------------------------------ #
    @property
    def duration_secs(self) -> float | None:
        return self.duration.total_seconds() if self.duration else None

    @property
    def duration_str(self) -> str:
        """Human-readable duration (e.g. '452ms', '2.4s', '1m 23s', '2h 5m', '1d 3h')."""
        secs = self.duration_secs
        if secs is None:
            return "-"
        return format_duration(secs)

    @property
    def time_ago_str(self) -> str:
        """Human-readable relative time since completion (e.g., '5s ago', '2d ago', '8w ago')."""
        if self.end_time is None:
            return "-"
        secs = (datetime.datetime.now() - self.end_time).total_seconds()
        return format_duration(secs) + " ago"

    @property
    def is_finalized(self) -> bool:
        """Run is finished (not pending or running / _finalize has been called). Could be success, failed, or cancelled."""
        return self._is_finalized

    # ------------------------------------------------------------------ #
    # Representation & serialization
    # ------------------------------------------------------------------ #
    def __repr__(self) -> str:
        chain_display = "->".join(self.trigger_chain) if self.trigger_chain else "manual"
        return (
            f"RunResult(id={self.run_id[:8]}, cmd='{self.command_name}', "
            f"state={self.state.value}, dur={self.duration_str}, success={self.success}, "
            f"chain={chain_display})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "run_id": self.run_id,
            "command_name": self.command_name,
            "trigger_event": self.trigger_event,
            "trigger_chain": self.trigger_chain.copy(),
            "output": self.output,
            "success": self.success,
            "error": str(self.error) if self.error else None,
            "state": self.state.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_str": self.duration_str,
            "resolved_command": self.resolved_command.to_dict() if self.resolved_command else None,
        }

    def to_toml(self) -> str:
        """
        Serialize RunResult to TOML format for metadata file.

        Returns:
            TOML string with all metadata fields

        Example output:
            command_name = "Tests"
            run_id = "123e4567-e89b-12d3-a456-426614174000"
            state = "SUCCESS"
            duration_str = "2.3s"
            start_time = "2025-12-25T10:30:00"
            end_time = "2025-12-25T10:30:02"
            success = true
            trigger_chain = ["file_changed", "command_success:Lint"]

            [resolved_command]
            command = "pytest tests/"
            cwd = "/home/user/project"
            timeout_secs = 300

            [resolved_command.vars]
            test_dir = "tests"
        """

        def escape_toml_string(s: str) -> str:
            """Escape special characters for TOML string values."""
            return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

        lines = [
            f'command_name = "{escape_toml_string(self.command_name)}"',
            f'run_id = "{self.run_id}"',
            f'state = "{self.state.value}"',
            f'duration_str = "{self.duration_str}"',
        ]

        # Add optional fields
        if self.start_time:
            lines.append(f'start_time = "{self.start_time.isoformat()}"')
        if self.end_time:
            lines.append(f'end_time = "{self.end_time.isoformat()}"')
        if self.success is not None:
            lines.append(f"success = {str(self.success).lower()}")
        if self.comment:
            lines.append(f'comment = "{escape_toml_string(self.comment)}"')
        if self.error:
            error_str = str(self.error)
            lines.append(f'error = "{escape_toml_string(error_str)}"')
        if self.trigger_event:
            lines.append(f'trigger_event = "{escape_toml_string(self.trigger_event)}"')

        # Add trigger chain
        if self.trigger_chain:
            chain_items = ", ".join(f'"{escape_toml_string(t)}"' for t in self.trigger_chain)
            lines.append(f"trigger_chain = [{chain_items}]")

        # Add file paths if present (BEFORE [resolved_command] section so they stay at top level)
        if self.output_file:
            lines.append(f'output_file = "{self.output_file.name}"')
        if self.metadata_file:
            lines.append(f'metadata_file = "{self.metadata_file.name}"')

        # Add resolved command section (must come AFTER top-level fields)
        if self.resolved_command:
            lines.append("")
            lines.append("[resolved_command]")
            lines.append(f'command = "{escape_toml_string(self.resolved_command.command)}"')
            if self.resolved_command.cwd:
                lines.append(f'cwd = "{escape_toml_string(self.resolved_command.cwd)}"')
            if self.resolved_command.timeout_secs is not None:
                lines.append(f"timeout_secs = {self.resolved_command.timeout_secs}")

            # Add vars subsection if present
            if self.resolved_command.vars:
                lines.append("")
                lines.append("[resolved_command.vars]")
                for key, value in sorted(self.resolved_command.vars.items()):
                    lines.append(f'{key} = "{escape_toml_string(value)}"')

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ #
    # Internal callback for run finalization
    # ------------------------------------------------------------------ #

    def _set_completion_callback(self, callback: Callable[[], None]) -> None:
        """Internal: register a callback to be called once on finalization."""
        if self._completion_callback is not None:
            if self._completion_callback == callback:
                return  # Idempotent for same callback
            raise ValueError(
                f"Completion callback can only be set once. Old callback exists as {self._completion_callback}, cannot set new one as {callback}."
            )

        self._completion_callback = callback
