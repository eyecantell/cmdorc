# cmdorc/command_status.py
from __future__ import annotations

from dataclasses import dataclass

from .run_result import RunResult, RunState


@dataclass(frozen=True)
class CommandStatus:
    """
    Derived status of a command, returned by CommandRuntime.get_status().

    Provides a high-level view for UI/TUI status icons, queries, etc.
    - If active_runs > 0 → state = "running"
    - Else if latest_result → state = latest_result.state.value
    - Else → state = "never_run"
    """

    state: str
    """Overall state: 'never_run', 'running', or a RunState value ('success', 'failed', 'cancelled')."""

    active_count: int = 0
    """Number of currently running instances (from max_concurrent)."""

    last_run: RunResult | None = None
    """The most recent completed RunResult (or None if never run)."""