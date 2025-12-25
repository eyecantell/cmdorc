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
@dataclass(frozen=True)
class OutputStorageConfig:
    """
    Configuration for automatic output file storage.

    When enabled (keep_history != 0), command outputs are automatically saved to disk:
    - metadata.toml: Run metadata (state, duration, trigger chain, resolved command, etc.)
    - output.txt: Raw command output (stdout + stderr)

    File storage is controlled by keep_history setting:
    - keep_history = 0: Disabled (no files written) [default]
    - keep_history = -1: Unlimited (write all files, never delete)
    - keep_history = N (N > 0): Keep last N runs per command (delete oldest)
    """

    directory: str = ".cmdorc/outputs"
    """
    Base directory for output files. Can be absolute or relative.
    Relative paths are resolved from the config file location.
    Default: .cmdorc/outputs
    """

    pattern: str = "{command_name}/{run_id}"
    """
    Directory structure pattern for organizing output files.
    Available variables: {command_name}, {run_id}
    Files are stored as: directory/pattern/metadata.toml and directory/pattern/output.txt
    Default: {command_name}/{run_id}
    """

    keep_history: int = 0
    """
    Number of output file sets to keep per command.
    - 0 = Disabled (no files written) [default]
    - -1 = Unlimited (keep all files)
    - N (N > 0) = Keep last N runs (oldest deleted when limit exceeded)
    """

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.keep_history < -1:
            logger.warning("Invalid output_storage config: keep_history must be >= -1")
            raise ConfigValidationError(
                "output_storage.keep_history must be -1 (unlimited), 0 (disabled), or positive"
            )

        if not self.pattern.strip():
            logger.warning("Invalid output_storage config: pattern cannot be empty")
            raise ConfigValidationError("output_storage.pattern cannot be empty")

        # Validate pattern contains only valid placeholders
        valid_placeholders = {"{command_name}", "{run_id}"}
        placeholders = set(re.findall(r"\{[^}]+\}", self.pattern))
        invalid = placeholders - valid_placeholders
        if invalid:
            logger.warning(
                f"Invalid output_storage config: Invalid placeholders {invalid} in pattern"
            )
            raise ConfigValidationError(
                f"Invalid placeholders in output_storage.pattern: {invalid}. "
                f"Valid placeholders: {valid_placeholders}"
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

    debounce_in_ms: int = 0
    """
    Optional: Minimum delay between runs of this command.
    If a run completes at time T, a new run cannot start until T + debounce_in_ms has passed.
    This is enforced by orchestrator before ConcurrencyPolicy is applied.
    0 = disabled (default).
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
