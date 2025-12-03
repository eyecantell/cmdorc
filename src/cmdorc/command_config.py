from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import logging

logger = logging.getLogger(__name__)

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

    triggers: list[str]
    """
    List of exact trigger strings that will cause this command to run.
    Must explicitly include the command's own name if manual/hotkey execution is desired.
    Example: ["changes_applied", "Tests"]
    """

    cancel_on_triggers: list[str] = field(default_factory=list)
    """
    If any of these triggers fire while the command is running, cancel it immediately.
    """

    max_concurrent: int = 1
    """
    Maximum number of concurrent instances allowed.
    0  → unlimited parallelism
    1  → normal single-instance behaviour (default)
    >1 → explicit parallelism
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
    0 = no history (but latest_result is always tracked separately)
    1 = keep only the most recent (default)
    N = keep last N runs
    """

    vars: dict[str, str] = field(default_factory=dict)
    """Command-specific template vars (overrides globals from RunnerConfig.vars)."""

    cwd: str | Path | None = None
    """Optional working directory for the command (absolute or relative to config file)."""

    env: dict[str, str] = field(default_factory=dict)
    """Environment variables to set for the command (merged with os.environ)."""

    def __post_init__(self) -> None:
        if not self.name:
            logger.warning(f"Invalid config: Command name cannot be empty")
            raise ValueError("Command name cannot be empty")
        if not self.command.strip():
            logger.warning(f"Invalid config for '{self.name}': Command cannot be empty")
            raise ValueError(f"Command for '{self.name}' cannot be empty")
        if self.max_concurrent < 0:
            logger.warning(f"Invalid config for '{self.name}': max_concurrent cannot be negative")
            raise ValueError("max_concurrent cannot be negative")
        if self.timeout_secs is not None and self.timeout_secs <= 0:
            logger.warning(f"Invalid config for '{self.name}': timeout_secs must be positive")
            raise ValueError("timeout_secs must be positive")
        if self.on_retrigger not in ("cancel_and_restart", "ignore"):
            logger.warning(f"Invalid config for '{self.name}': on_retrigger must be 'cancel_and_restart' or 'ignore'")
            raise ValueError("on_retrigger must be 'cancel_and_restart' or 'ignore'")
        if self.cwd is not None:
            try:
                Path(self.cwd).resolve()
            except OSError as e:
                logger.warning(f"Invalid config for '{self.name}': Invalid cwd: {e}")
                raise ValueError(f"Invalid cwd for '{self.name}': {e}")
            


@dataclass(frozen=True)
class RunnerConfig:
    """
    Top-level configuration object returned by load_config().
    Contains everything needed to instantiate a CommandRunner.
    """

    commands: list[CommandConfig]

    vars: dict[str, str] = field(default_factory=dict)
    """
    Global template variables.
    Example: {"base_directory": "/home/me/project", "tests_directory": "{{ base_directory }}/tests"}
    These act as defaults and can be overridden at runtime via CommandRunner.add_var()/set_vars().
    """

    def __post_init__(self) -> None:
        if not self.commands:
            raise ValueError("At least one command is required")