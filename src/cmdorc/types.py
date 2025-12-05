# cmdorc/types.py
from __future__ import annotations

from dataclasses import dataclass, field

from .run_result import RunResult


@dataclass
class NewRunDecision:
    """
    Decision returned by ConcurrencyPolicy.decide().

    - allow=True  → the requested run may start
    - runs_to_cancel → list of active runs that must be cancelled first
      (only used when on_retrigger="cancel_and_restart" or cancel_on_triggers)
    """

    allow: bool
    runs_to_cancel: list[RunResult] = field(default_factory=list)


@dataclass
class TriggerContext:
    """
    Context passed through the trigger chain to prevent infinite loops.

    Each top-level trigger() call gets a fresh TriggerContext.
    If an event name is already in seen, the engine aborts that branch.
    """

    seen: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class CommandStatus:
    """
    Rich status object returned by CommandRuntime.get_status().

    Used heavily by TUIs, status panels, and orchestrator helpers.

    state values:
      - "never_run" → command has never executed
      - "running"   → at least one active run (active_count > 0)
      - "success" / "failed" / "cancelled" → state of the most recent completed run
    """

    state: str
    """High-level state string."""

    active_count: int = 0
    """Number of currently running instances."""

    last_run: RunResult | None = None
    """Most recent completed RunResult (always available, even if keep_history=0)."""
