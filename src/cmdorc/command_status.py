# cmdorc/command_status.py
from __future__ import annotations

from enum import Enum

from .run_result import RunState


class CommandStatus(Enum):
    """
    Effective status of a command in the runner.
    
    This represents the overall state of a command, taking into account:
    - Whether it's currently running
    - The state of its most recent completed run
    - Whether it has ever been run
    """
    
    NEVER_RUN = "never_run"
    IDLE_SUCCESS = "idle_success"      # last run succeeded
    IDLE_FAILED = "idle_failed"        # last run failed
    IDLE_CANCELLED = "idle_cancelled"
    RUNNING = "running"