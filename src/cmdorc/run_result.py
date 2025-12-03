# cmdorc/run_result.py
from __future__ import annotations

import asyncio
import datetime
import logging
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


@dataclass
class RunResult:
    """
    Represents a single execution of a command.

    Internal mutable object used by CommandRuntime and CommandExecutor.
    Users interact with it via the public RunHandle façade.
    """

    # ------------------------------------------------------------------ #
    # Identification
    # ------------------------------------------------------------------ #
    run_id: str = field(default_factory=lambda: str(__import__("uuid").uuid4()))
    """Unique identifier for this run."""

    command_name: str = field(init=False)
    """Name of the command being executed."""

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
    resolved_vars: dict[str, str] = field(default_factory=dict)
    """Final template variables used after merging globals + command vars + overrides."""

    resolved_env: dict[str, str] = field(default_factory=dict)
    """Final environment dict passed to the subprocess (os.environ + config.env)."""

    resolved_cwd: str | None = None
    """Absolute working directory used for the subprocess."""

    resolved_timeout_secs: int | None = None
    """Effective timeout value applied to this run (after resolution, if any)."""

    # ------------------------------------------------------------------ #
    # Async completion signalling
    # ------------------------------------------------------------------ #
    future: asyncio.Future["RunResult"] = field(default_factory=asyncio.Future)
    """Future resolved when the run finishes (used by RunHandle.wait())."""

    # ------------------------------------------------------------------ #
    # State transitions
    # ------------------------------------------------------------------ #
    def mark_running(self) -> None:
        """Transition to RUNNING and record start time."""
        if self.state is not RunState.PENDING:
            logger.warning(f"Run {self.run_id} marked running from invalid state {self.state}")
        self.state = RunState.RUNNING
        self.start_time = datetime.datetime.now()
        logger.debug(f"Run {self.run_id} ('{self.command_name}') started")

    def mark_success(self) -> None:
        """Mark as successfully completed."""
        self.state = RunState.SUCCESS
        self.success = True
        self._finalize()
        logger.debug(f"Run {self.run_id} ('{self.command_name}') succeeded in {self.duration_str}")

    def mark_failed(self, error: str | Exception) -> None:
        """Mark as failed."""
        self.state = RunState.FAILED
        self.success = False
        self.error = error
        self._finalize()
        msg = str(error) if isinstance(error, Exception) else error
        logger.debug(f"Run {self.run_id} ('{self.command_name}') failed: {msg}")

    def mark_cancelled(self, reason: str | None = None) -> None:
        """Mark as cancelled."""
        self.state = RunState.CANCELLED
        self.success = None
        self.error = reason or "Command was cancelled"
        self._finalize()
        logger.debug(f"Run {self.run_id} ('{self.command_name}') cancelled")

    # ------------------------------------------------------------------ #
    # Finalization
    # ------------------------------------------------------------------ #
    def _finalize(self) -> None:
        """Record end time, compute duration, and signal the future."""
        self.end_time = datetime.datetime.now()
        if self.start_time:
            self.duration = self.end_time - self.start_time
        else:
            self.duration = datetime.timedelta(0)

        # Callers check result.state/success to determine outcome
        if not self.future.done():
            self.future.set_result(self)

    # ------------------------------------------------------------------ #
    # Timing properties
    # ------------------------------------------------------------------ #
    @property
    def duration_secs(self) -> float | None:
        return self.duration.total_seconds() if self.duration else None

    @property
    def duration_ms(self) -> float | None:
        return self.duration.total_seconds() * 1000 if self.duration else None

    @property
    def duration_str(self) -> str:
        """Human-readable duration (e.g. '452ms', '2.4s', '1m 23s', '2h 5m')."""
        secs = self.duration_secs
        if secs is None:
            return "—"
        if secs < 1:
            return f"{secs * 1000:.0f}ms"
        if secs < 60:
            return f"{secs:.1f}s"
        mins, secs = divmod(secs, 60)
        if mins < 60:
            return f"{int(mins)}m {secs:.0f}s"
        hrs, mins = divmod(mins, 60)
        return f"{int(hrs)}h {int(mins)}m"

    @property
    def is_finished(self) -> bool:
        return self.state not in {RunState.PENDING, RunState.RUNNING}

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
            "duration_ms": self.duration_ms,
            "duration_str": self.duration_str,
            "resolved_vars": self.resolved_vars.copy(),
            "resolved_env_keys": list(self.resolved_env.keys()),  # Don't dump full env by default
            "resolved_cwd": self.resolved_cwd,
            "resolved_timeout_secs": self.resolved_timeout_secs,
        }