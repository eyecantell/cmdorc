# src/cmdorc/load_config.py
from __future__ import annotations

import logging
from typing import BinaryIO, TextIO

try:
    import tomllib as tomli  # Python 3.11+
except ImportError:
    import tomli  # <3.11

from pathlib import Path

from .command_config import CommandConfig
from .runner_config import RunnerConfig

logger = logging.getLogger(__name__)


def load_config(path: str | Path | BinaryIO | TextIO) -> RunnerConfig:
    """
    Load and validate a TOML config file into a RunnerConfig.

    - Parses the entire TOML.
    - Validates and creates CommandConfig objects for [[command]] sections.
    - Extracts [variables] as defaults (optional).
    - Performs simple nested resolution for {{ }} in vars (up to 5 levels to prevent loops).

    Raises ValueError on invalid data or missing required fields.
    """
    if hasattr(path, "read"):
        data = tomli.load(path)  # type: ignore
    else:
        with open(path, "rb") as f:
            data = tomli.load(f)

    # Extract and resolve [variables] (global defaults)
    vars_dict: dict[str, str] = data.get("variables", {}).copy()

    # Resolve nested {{ }} variables – detect cycles AND missing vars
    for _ in range(5):  # Max depth to avoid infinite loops
        changed = False
        for key, value in list(vars_dict.items()):
            try:
                new_value = value.format_map(vars_dict)
                if new_value != value:
                    vars_dict[key] = new_value
                    logger.debug(f"Resolved variable '{key}': '{value}' -> '{new_value}'")
                    changed = True
            except KeyError as e:
                raise ValueError(f"Missing variable in [variables].{key}: {e}") from None

        if not changed:
            logger.debug("No more variable changes detected; resolution complete.")
            for key, value in vars_dict.items():
                if "{" in value and "}" in value:
                    raise ValueError(
                        f"Stalled resolution in [variables].{key}: unresolved placeholders remain in '{value}'"
                    )
            break
    else:
        raise ValueError("Infinite loop detected in [variables] resolution")

    # Extract and validate [[command]] array
    command_data = data.get("command", [])
    if not isinstance(command_data, list):
        raise ValueError("[[command]] must be an array of tables")

    commands = []
    for cmd_dict in command_data:
        try:
            cmd = CommandConfig(**cmd_dict)
            commands.append(cmd)
        except TypeError as e:
            raise ValueError(f"Invalid config in [[command]]: {e}") from None

    if not commands:
        raise ValueError("At least one [[command]] is required") from None

    return RunnerConfig(commands=commands, vars=vars_dict)
