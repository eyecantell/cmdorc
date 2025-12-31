from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, BinaryIO, TextIO

try:
    import tomllib as tomli  # Python 3.11+
except ImportError:
    import tomli  # <3.11

from .command_config import CommandConfig, OutputStorageConfig, RunnerConfig
from .exceptions import ConfigValidationError

logger = logging.getLogger(__name__)


# =====================================================================
#   Helper function
# =====================================================================
def _read_toml(path: str | Path | BinaryIO | TextIO) -> tuple[Path | None, dict]:
    """
    Read TOML file and return (config_path, data).

    Args:
        path: File path or file-like object

    Returns:
        Tuple of (config_path, parsed_data)
        config_path is None for file-like objects
    """
    config_path: Path | None = None
    if not hasattr(path, "read"):
        config_path = Path(path).resolve()
        with open(config_path, "rb") as f:
            data = tomli.load(f)
    else:
        data = tomli.load(path)  # type: ignore
    return config_path, data


# =====================================================================
#   Main loaders
# =====================================================================
def load_configs(paths: list[str | Path | BinaryIO | TextIO]) -> RunnerConfig:
    """
    Load and merge multiple TOML config files into a single RunnerConfig.

    Merge rules:
    - variables: dict merge, last-in-wins, WARN on override
    - commands: accumulate, ERROR on duplicate names
    - output_storage: merge fields, last-in-wins, WARN on override

    Args:
        paths: Config files in priority order (later overrides earlier)

    Returns:
        Merged RunnerConfig

    Raises:
        ConfigValidationError: On duplicate command names or validation errors
        FileNotFoundError: If a config file doesn't exist
    """
    if not paths:
        raise ConfigValidationError("At least one config file path is required")

    # Parse all files
    configs = []
    for path in paths:
        config_path, data = _read_toml(path)
        configs.append((config_path, data))

    # Merge variables with warnings
    merged_vars: dict[str, str] = {}
    for config_path, data in configs:
        file_name = config_path.name if config_path else "<stream>"
        for key, value in data.get("variables", {}).items():
            if key in merged_vars and merged_vars[key] != value:
                logger.warning(
                    f"Variable '{key}' overridden by {file_name} "
                    f"(was: {merged_vars[key]!r}, now: {value!r})"
                )
            merged_vars[key] = value

    # Merge output_storage with warnings
    merged_output: dict[str, Any] = {}
    for config_path, data in configs:
        file_name = config_path.name if config_path else "<stream>"
        for key, value in data.get("output_storage", {}).items():
            if key in merged_output and merged_output[key] != value:
                logger.warning(
                    f"output_storage.{key} overridden by {file_name} "
                    f"(was: {merged_output[key]!r}, now: {value!r})"
                )
            merged_output[key] = value

    # Check for removed pattern field
    if "pattern" in merged_output:
        raise ConfigValidationError(
            "output_storage.pattern is no longer configurable (removed in v0.3.0). "
            "Files are always stored as {command_name}/{run_id}/ for retention enforcement."
        )

    # Resolve relative output_storage directory (use first config's base dir)
    first_base_dir = configs[0][0].parent if configs[0][0] else Path.cwd()
    if "directory" in merged_output and merged_output["directory"] is not None:
        dir_path = Path(merged_output["directory"])
        if not dir_path.is_absolute():
            merged_output["directory"] = str(first_base_dir / dir_path)

    # Accumulate commands, error on duplicates
    all_commands = []
    seen_names: dict[str, str] = {}  # name -> source_file
    for config_path, data in configs:
        base_dir = config_path.parent if config_path else Path.cwd()
        file_name = config_path.name if config_path else "<stream>"

        for cmd_dict in data.get("command", []):
            name = cmd_dict.get("name", "<unknown>")

            # Check for duplicate command names
            if name in seen_names:
                raise ConfigValidationError(
                    f"Duplicate command name '{name}'\n"
                    f"  - First defined in: {seen_names[name]}\n"
                    f"  - Also defined in: {file_name}\n"
                    f"Please use unique command names across all config files."
                )
            seen_names[name] = file_name

            # Check for deprecated keep_history field
            if "keep_history" in cmd_dict:
                raise ConfigValidationError(
                    f"Command '{name}': "
                    f"'keep_history' was removed in v0.5.0. Use 'keep_in_memory' instead."
                )

            # Resolve relative cwd paths
            if "cwd" in cmd_dict and cmd_dict["cwd"] is not None:
                cwd_path = Path(cmd_dict["cwd"])
                if not cwd_path.is_absolute():
                    cmd_dict["cwd"] = str(base_dir / cwd_path)

            try:
                cmd = CommandConfig(**cmd_dict)
                all_commands.append(cmd)
            except TypeError as e:
                raise ConfigValidationError(f"Invalid config in [[command]]: {e}") from None

    if not all_commands:
        raise ConfigValidationError("At least one [[command]] is required across all config files")

    # Build OutputStorageConfig from merged values
    try:
        output_storage = (
            OutputStorageConfig(**merged_output) if merged_output else OutputStorageConfig()
        )
    except TypeError as e:
        raise ConfigValidationError(f"Invalid config in [output_storage]: {e}") from None

    logger.debug(
        f"Loaded {len(paths)} config files: "
        f"{len(all_commands)} commands, {len(merged_vars)} variables"
    )

    return RunnerConfig(commands=all_commands, vars=merged_vars, output_storage=output_storage)


def load_config(path: str | Path | BinaryIO | TextIO) -> RunnerConfig:
    """
    Load and validate a single TOML config file into a RunnerConfig.

    This is a convenience wrapper around load_configs() for single-file configs.
    Resolves relative `cwd` paths relative to the config file location.

    Args:
        path: Path to config file or file-like object

    Returns:
        RunnerConfig with parsed configuration

    Raises:
        ConfigValidationError: On validation errors
        FileNotFoundError: If config file doesn't exist
    """
    return load_configs([path])
