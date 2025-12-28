from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO, TextIO

try:
    import tomllib as tomli  # Python 3.11+
except ImportError:
    import tomli  # <3.11

from .command_config import CommandConfig, OutputStorageConfig, RunnerConfig
from .exceptions import ConfigValidationError

logger = logging.getLogger(__name__)


# =====================================================================
#   Main loader
# =====================================================================
def load_config(path: str | Path | BinaryIO | TextIO) -> RunnerConfig:
    """
    Load and validate a TOML config file into a RunnerConfig.
    Resolves relative `cwd` paths relative to the config file location.
    """
    config_path: Path | None = None
    if not hasattr(path, "read"):
        config_path = Path(path).resolve()
        with open(config_path, "rb") as f:
            data = tomli.load(f)
    else:
        data = tomli.load(path)  # type: ignore

    # Resolve base directory for relative paths
    base_dir = config_path.parent if config_path else Path.cwd()

    # ────── Load [variables] as templates ──────
    # Variables are stored as templates and resolved at runtime (Phase 2/3 in orchestrator)
    vars_dict: dict[str, str] = data.get("variables", {}).copy()
    logger.debug(f"Loaded {len(vars_dict)} variables as templates (resolution deferred to runtime)")

    # ────── Parse [output_storage] section ──────
    output_storage_dict = data.get("output_storage", {}).copy()

    # Check for removed pattern field
    if "pattern" in output_storage_dict:
        raise ConfigValidationError(
            "output_storage.pattern is no longer configurable (removed in v0.3.0). "
            "Files are always stored as {command_name}/{run_id}/ for retention enforcement."
        )

    # Resolve relative directory path relative to config file location
    if "directory" in output_storage_dict and output_storage_dict["directory"] is not None:
        dir_path = Path(output_storage_dict["directory"])
        if not dir_path.is_absolute():
            output_storage_dict["directory"] = str(base_dir / dir_path)

    try:
        output_storage = OutputStorageConfig(**output_storage_dict)
        logger.debug(
            f"Loaded output_storage config (enabled={output_storage.is_enabled}, "
            f"keep_history={output_storage.keep_history})"
        )
    except TypeError as e:
        raise ConfigValidationError(f"Invalid config in [output_storage]: {e}") from None

    # ────── Parse and fix commands ──────
    command_data = data.get("command", [])
    if not isinstance(command_data, list):
        raise ConfigValidationError("[[command]] must be an array of tables")

    commands = []
    for cmd_dict in command_data:
        # keep_history was deprecated in v0.3.0 and removed in v0.5.0
        if "keep_history" in cmd_dict:
            raise ConfigValidationError(
                f"Command '{cmd_dict.get('name', '<unknown>')}': "
                f"'keep_history' was removed in v0.5.0. Use 'keep_in_memory' instead."
            )

        # Resolve relative cwd
        if "cwd" in cmd_dict and cmd_dict["cwd"] is not None:
            cwd_path = Path(cmd_dict["cwd"])
            if not cwd_path.is_absolute():
                cmd_dict["cwd"] = str(base_dir / cwd_path)

        try:
            cmd = CommandConfig(**cmd_dict)
            commands.append(cmd)
        except TypeError as e:
            raise ConfigValidationError(f"Invalid config in [[command]]: {e}") from None

    if not commands:
        raise ConfigValidationError("At least one [[command]] is required")

    return RunnerConfig(commands=commands, vars=vars_dict, output_storage=output_storage)
