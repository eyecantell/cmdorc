from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .exceptions import ConfigValidationError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Trigger validation
# ─────────────────────────────────────────────────────────────────────────────
def validate_trigger(name: str, *, allow_wildcards: bool = False) -> str:
    """
    Validate a trigger name.

    Args:
        name: The trigger string to validate
        allow_wildcards: If True, allows '*' wildcard character

    Raises:
        ConfigValidationError: If trigger is empty or contains invalid characters

    Allowed characters:
        - Alphanumerics (a-z, A-Z, 0-9)
        - Underscores (_)
        - Hyphens (-)
        - Colons (:) - for lifecycle events like "command_success:Name"
        - Asterisks (*) - only if allow_wildcards=True
    """
    if not name:
        raise ConfigValidationError("Trigger name cannot be empty")

    pattern = r"^[\w\-\:\*]+$"
    if not allow_wildcards:
        pattern = r"^[\w\-\:]+$"

    if not re.match(pattern, name):
        allowed = (
            "alphanumerics, underscores, hyphens, and colons"
            if not allow_wildcards
            else "alphanumerics, underscores, hyphens, colons, and '*' wildcard"
        )
        raise ConfigValidationError(f"Invalid trigger name '{name}': must contain only {allowed}")

    return name.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Output Storage Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Output directory pattern (not configurable - retention logic depends on this structure)
OUTPUT_PATTERN = "{command_name}/{run_id}"


@dataclass(frozen=True)
class OutputStorageConfig:
    """
    Configuration for automatic output file storage.

    When enabled (keep_history != 0), command outputs are automatically saved to disk:
    - metadata.toml: Run metadata (state, duration, trigger chain, resolved command, etc.)
    - output{extension}: Raw command output (stdout + stderr)

    File storage is controlled by keep_history setting:
    - keep_history = 0: Disabled (no files written) [default]
    - keep_history = -1: Unlimited (write all files, never delete)
    - keep_history = N (N > 0): Keep last N runs per command (delete oldest)
    """

    directory: str = ".cmdorc/outputs"
    """
    Base directory for output files. Can be absolute or relative.
    Relative paths are resolved from the config file location.

    Files are organized as: directory/{command_name}/{run_id}/metadata.toml
    This structure is required for retention enforcement to work correctly.

    Default: .cmdorc/outputs
    """

    keep_history: int = 0
    """
    Number of output file sets to keep per command.
    - 0 = Disabled (no files written) [default]
    - -1 = Unlimited (keep all files)
    - N (N > 0) = Keep last N runs (oldest deleted when limit exceeded)
    """

    output_extension: str = ".txt"
    """
    File extension for output files.
    Must start with a dot (e.g., ".txt", ".log", ".json").

    Default: .txt
    """

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.keep_history < -1:
            logger.warning("Invalid output_storage config: keep_history must be >= -1")
            raise ConfigValidationError(
                "output_storage.keep_history must be -1 (unlimited), 0 (disabled), or positive"
            )
        if not self.output_extension.startswith("."):
            raise ConfigValidationError(
                f"output_storage.output_extension must start with a dot, got: {self.output_extension!r}"
            )
        if "/" in self.output_extension or "\\" in self.output_extension:
            raise ConfigValidationError(
                f"output_storage.output_extension cannot contain path separators: {self.output_extension!r}"
            )

    @property
    def is_enabled(self) -> bool:
        """Check if output storage is enabled (keep_history != 0)."""
        return self.keep_history != 0


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

    keep_in_memory: int = 3
    """
    How many completed RunResult objects to keep in memory.

    Controls in-memory history accessible via get_history() API.
    Loaded runs from disk are also limited by this setting.

    Values:
    - 0 = No in-memory history (but latest_result always tracked)
    - N > 0 = Keep last N runs in memory (default: 3)
    - -1 = Unlimited (keep all runs in memory)

    Note: This is separate from OutputStorageConfig.keep_history which controls disk retention.
    """

    vars: dict[str, str] = field(default_factory=dict)
    """Command-specific template vars (overrides globals from RunnerConfig.vars)."""

    cwd: str | Path | None = None
    """Optional working directory for the command (absolute or relative to config file)."""

    env: dict[str, str] = field(default_factory=dict)
    """Environment variables to set for the command (merged with os.environ)."""

    debounce_in_ms: int = 0
    """
    Minimum time interval (in milliseconds) between command runs.

    Prevents rapid retriggering by enforcing a delay. The timing reference depends on debounce_mode.
    Enforced by orchestrator before ConcurrencyPolicy is applied.
    0 = disabled (default).
    """

    debounce_mode: Literal["start", "completion"] = "start"
    """
    Controls how debounce timing is calculated:

    - "start" (default): Prevents starts within debounce_in_ms of the last START time.
      For long-running commands, this allows immediate retriggering after completion.
      Example: 10s command with 1s debounce → can retrigger immediately after it finishes.

    - "completion": Prevents starts within debounce_in_ms of the last COMPLETION time.
      Ensures minimum gap between consecutive runs regardless of duration.
      Example: 10s command with 1s debounce → must wait 1s after completion before retriggering.

    Note: "start" is default for backward compatibility, but "completion" matches most users' expectations.
    """

    loop_detection: bool = True
    """
    If True (default), TriggerEngine will prevent recursive cycles using TriggerContext.seen.
    If False, this command's triggers bypass cycle detection and may produce recursive flows.
    Use with caution.
    """

    def __post_init__(self) -> None:
        if not self.name:
            logger.warning("Invalid config: Command name cannot be empty")
            raise ConfigValidationError("Command name cannot be empty")
        if not self.command.strip():
            logger.warning(f"Invalid config for '{self.name}': Command cannot be empty")
            raise ConfigValidationError(f"Command for '{self.name}' cannot be empty")
        if self.max_concurrent < 0:
            logger.warning(f"Invalid config for '{self.name}': max_concurrent cannot be negative")
            raise ConfigValidationError("max_concurrent cannot be negative")
        if self.timeout_secs is not None and self.timeout_secs <= 0:
            logger.warning(f"Invalid config for '{self.name}': timeout_secs must be positive")
            raise ConfigValidationError("timeout_secs must be positive")
        if self.on_retrigger not in ("cancel_and_restart", "ignore"):
            logger.warning(
                f"Invalid config for '{self.name}': on_retrigger must be 'cancel_and_restart' or 'ignore'"
            )
            raise ConfigValidationError("on_retrigger must be 'cancel_and_restart' or 'ignore'")
        if self.cwd is not None:
            try:
                Path(self.cwd).resolve()
            except OSError as e:
                logger.warning(f"Invalid config for '{self.name}': Invalid cwd: {e}")
                raise ConfigValidationError(f"Invalid cwd for '{self.name}': {e}") from None

        # ────── Validate keep_in_memory ──────
        if self.keep_in_memory < -1:
            logger.warning(
                f"Invalid config for '{self.name}': keep_in_memory must be -1 (unlimited), 0, or positive"
            )
            raise ConfigValidationError(
                "keep_in_memory must be -1 (unlimited), 0 (disabled), or positive"
            )

        # ────── Validate debounce_mode ──────
        if self.debounce_mode not in ("start", "completion"):
            logger.warning(
                f"Invalid config for '{self.name}': debounce_mode must be 'start' or 'completion'"
            )
            raise ConfigValidationError("debounce_mode must be 'start' or 'completion'")

        # ────── Warn about loop_detection=False ──────
        if not self.loop_detection:
            logger.warning(
                f"Command '{self.name}' has loop_detection=False: "
                f"infinite trigger cycles are possible. Use with extreme caution."
            )

        # ────── Validate triggers ──────
        for t in self.triggers:
            validate_trigger(t, allow_wildcards=False)
        for t in self.cancel_on_triggers:
            validate_trigger(t, allow_wildcards=False)


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

    output_storage: OutputStorageConfig = field(default_factory=OutputStorageConfig)
    """
    Output storage configuration for automatic file persistence.
    Default: OutputStorageConfig() (disabled with keep_history=0)
    """

    def __post_init__(self) -> None:
        if not self.commands:
            raise ConfigValidationError("At least one command is required")
