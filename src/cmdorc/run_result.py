# cmdorc/run_result.py
from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class RunState(Enum):
    """State of a single command execution (RunResult)."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunResult:
    """
    Result of a single command execution.
    
    Contains all information about a command run including:
    - Execution state and timing
    - Output and error information
    - Variables used during execution
    - Async task handle for awaiting completion
    """
    
    run_id: str = field(default_factory=lambda: str(__import__('uuid').uuid4()))
    command_name: str = field(init=False)
    trigger_event: str | None = None

    output: str = ""
    success: bool | None = None
    error: str | Exception | None = None

    state: RunState = RunState.PENDING

    # Timing
    task: asyncio.Task | None = None
    start_time: datetime.datetime | None = None
    end_time: datetime.datetime | None = None
    duration: datetime.timedelta | None = None

    # Variables used for this run (snapshot at start)
    vars: dict[str, str] = field(default_factory=dict)

    future: asyncio.Future = field(default_factory=asyncio.Future)  # for awaiting completion (used in RunHandle.wait())

    def cancel(self) -> None:
        """Cancel the underlying task and mark as cancelled."""
        self.mark_cancelled()
        if self.task and not self.task.done():
            self.task.cancel()
            logger.info(f"Cancelling task for run {self.run_id} ({self.command_name})")
        

    # Timing helpers
    @property
    def duration_ms(self) -> float | None:
        """Exact duration in milliseconds (float) or None if not finished."""
        return self.duration.microseconds() / 1000.0 if self.duration else None

    @property
    def duration_str(self) -> str:
        """Human-readable duration — e.g. '1m 23s', '2.4s', '1h 5m'."""
        secs = self.duration_secs
        if secs is None:
            return "—"

        if secs < 60:
            return f"{secs:.1f}s"

        mins, secs = divmod(secs, 60)
        if mins < 60:
            return f"{int(mins)}m {secs:.0f}s"

        hrs, mins = divmod(mins, 60)
        return f"{int(hrs)}h {int(mins)}m"
    
    def __init__(self, command_name: str) -> None:
        self.command_name = command_name

    # State transition helpers
    def mark_running(self) -> None:
        """Mark this run as started."""
        self.state = RunState.RUNNING
        self.start_time = datetime.datetime.now()
        logger.debug(f"Command '{self.command_name}' ({self.run_id}) started at {self.start_time}")

    def mark_success(self) -> None:
        """Mark this run as successfully completed."""
        self.state = RunState.SUCCESS
        self.success = True
        self._finalize()
        logger.debug(f"Command '{self.command_name}' ({self.run_id}) succeeded at {self.end_time}")

    def mark_failed(self, error: str) -> None:
        """Mark this run as failed with an error message."""
        self.state = RunState.FAILED
        self.success = False
        self.error = error
        self._finalize()
        logger.debug(
            f"Command '{self.command_name}' ({self.run_id}) failed at {self.end_time} with error: {error}"
        )

    def mark_cancelled(self) -> None:
        """Mark this run as cancelled."""
        self.state = RunState.CANCELLED
        self.success = None
        self.error = "Command was cancelled"
        self._finalize()
        logger.debug(f"Command '{self.command_name}' ({self.run_id}) cancelled at {self.end_time}")

    def _finalize(self) -> None:
        self.end_time = datetime.datetime.now()
        if self.start_time:
            self.duration = self.end_time - self.start_time
        else:
            self.duration = datetime.timedelta(0)
        
        if self.state == RunState.SUCCESS:
            self.future.set_result(self)
        else:
            exc = self.error if isinstance(self.error, Exception) else RuntimeError(self.error or "Unknown error")
            self.future.set_exception(exc)

    def __repr__(self) -> str:
        dur = f"{self.duration_secs:.2f}s" if self.duration_secs is not None else "—"

        return (
            f"RunResult(id={self.run_id[:8]}, cmd='{self.command_name}', "
            f"state={self.state}, dur={dur}, success={self.success})"
        )
    
    def to_dict(self) -> dict:
        """Serialize RunResult to a dictionary."""
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
            "duration_ms": self.duration_ms(),
            "vars": self.vars,
        }