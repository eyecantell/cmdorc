# cmdorc/run_result.py
from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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
        if secs < 1:
            return f"{secs * 1000:.0f}ms"
        if secs < 60:
            return f"{secs:.1f}s"
        mins, secs = divmod(secs, 60)
        if mins < 60:
            return f"{int(mins)}m {secs:.0f}s"
        hrs, mins = divmod(mins, 60)
        if hrs < 24:
            return f"{int(hrs)}h {int(mins)}m"

        days, hrs = divmod(hrs, 24)
        return f"{int(days)}d {int(hrs)}h"

    @property
    def is_finalized(self) -> bool:
        """Run is finished (not pending or running / _finalize has been called). Could be success, failed, or cancelled."""
        return self._is_finalized

    # ------------------------------------------------------------------ #
    # Representation & serialization
    # ------------------------------------------------------------------ #
    def __repr__(self) -> str:
        return (
            f"RunResult(id={self.run_id[:8]}, cmd='{self.command_name}', "
            f"state={self.state.value}, dur={self.duration_str}, success={self.success})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "run_id": self.run_id,
            "command_name": self.command_name,
            "trigger_event": self.trigger_event,
            "output": self.output,
            "success": self.success,
            "error": str(self.error) if self.error else None,
            "state": self.state.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_str": self.duration_str,
            "resolved_command": self.resolved_command.to_dict() if self.resolved_command else None,
        }

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
