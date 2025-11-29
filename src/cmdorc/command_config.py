# cmdorc/config.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, List


@dataclass(frozen=True)
class CommandConfig:
    """
    Immutable configuration for a single command.
    Used both when loading from TOML and when passed programmatically.
    """

    name: str
    """Unique name of the command. Used in triggers and UI."""

    command: str
    """Shell command to execute. May contain {{ template_vars }}."""

    triggers: List[str]
    """
    List of exact trigger strings that will cause this command to run.
    Must explicitly include the command's own name if manual/hotkey execution is desired.
    Example: ["changes_applied", "Tests"]
    """

    cancel_on_triggers: List[str] = field(default_factory=list)
    """
    If any of these triggers fire while the command is running, cancel it immediately.
    """

    max_concurrent: int = 1
    """
    Maximum number of concurrent instances allowed.
    1  → normal single-instance behaviour
    0  → unlimited parallelism
    >1 → explicit parallelism (rare)
    """

    timeout_secs: int | None = None
    """
    Optional hard timeout in seconds. Process will be killed if exceeded.
    """

    on_retrigger: Literal["cancel_and_restart", "ignore"] = "cancel_and_restart"
    """
    What to do when a new trigger arrives while the command is already running
    and max_concurrent has been reached.
    """

    keep_history: int = 1
    """
    How many past RunResult objects to keep.
    0 = keep none (only latest via get_result())
    1 = keep only the most recent (default)
    N = keep last N runs
    """

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Command name cannot be empty")
        if not self.command.strip():
            raise ValueError(f"Command for '{self.name}' cannot be empty")
        if self.max_concurrent < 0:
            raise ValueError("max_concurrent cannot be negative")
        if self.timeout_secs is not None and self.timeout_secs <= 0:
            raise ValueError("timeout_secs must be positive")