from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import BinaryIO, TextIO

try:
    import tomllib as tomli  # Python 3.11+
except ImportError:
    import tomli  # <3.11

from .command_config import CommandConfig, RunnerConfig

logger = logging.getLogger(__name__)

# Regex for {{ variable_name }}
VAR_PATTERN = re.compile(r"\{\{\s*([\w_]+)\s*\}\}")


# =====================================================================
#   Variable Resolution
# =====================================================================
def resolve_double_brace_vars(value: str, vars_dict: dict[str, str], *, max_depth: int = 5) -> str:
    """
    Resolve {{ var }} occurrences using vars_dict.
    Only replaces double-braced variables, not single-brace placeholders.
    Supports nested resolution with a maximum depth to avoid infinite loops.

    Raises:
        ValueError if a variable is missing, or if nested resolution never stabilizes.
    """

    for _ in range(max_depth):
        changed = False

        def repl(match: re.Match) -> str:
            nonlocal changed
            var_name = match.group(1)

            if var_name not in vars_dict:
                raise ValueError(f"Missing variable: '{var_name}'")

            changed = True
            return vars_dict[var_name]

        new_value = VAR_PATTERN.sub(repl, value)

        if not changed:
            return new_value  # fully resolved

        value = new_value

    # If still unresolved, we hit a cycle or unresolvable nested structure
    if VAR_PATTERN.search(value):
        raise ValueError(
            f"Unresolved nested variables remain in '{value}' after {max_depth} passes"
        )

    return value


# =====================================================================
#   Main loader
# =====================================================================
def load_config(path: str | Path | BinaryIO | TextIO, max_nested_depth: int = 10) -> RunnerConfig:
    """
    Load and validate a TOML config file into a RunnerConfig.

    - Parses the entire TOML.
    - Validates and creates CommandConfig objects for [[command]] sections.
    - Extracts [variables] as defaults (optional).
    - Resolves nested {{ }} variables safely (up to max depth).
    """

    # --------------------------------------------------------------
    # Read TOML
    # --------------------------------------------------------------
    if hasattr(path, "read"):
        data = tomli.load(path)  # type: ignore
    else:
        with open(path, "rb") as f:
            data = tomli.load(f)

    # --------------------------------------------------------------
    # Resolve [variables]
    # --------------------------------------------------------------
    vars_dict: dict[str, str] = data.get("variables", {}).copy()

    # Nested resolution across variables:
    # For example: b = "{{ a }}" and c = "{{ b }}"
    for _ in range(max_nested_depth):
        changed = False

        for key, value in list(vars_dict.items()):
            new_value = resolve_double_brace_vars(value, vars_dict, max_depth=max_nested_depth)
            if new_value != value:
                vars_dict[key] = new_value
                logger.debug(f"Resolved variable '{key}': '{value}' -> '{new_value}'")
                changed = True

        if not changed:
            logger.debug("Variable resolution stabilized.")
            break
    else:
        raise ValueError("Infinite loop detected while resolving [variables]")

    # --------------------------------------------------------------
    # Parse commands
    # --------------------------------------------------------------
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
        raise ValueError("At least one [[command]] is required")

    # --------------------------------------------------------------
    # Return final config
    # --------------------------------------------------------------
    return RunnerConfig(commands=commands, vars=vars_dict)
