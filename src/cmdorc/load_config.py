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
def resolve_double_brace_vars(value: str, vars_dict: dict[str, str], *, max_depth: int = 10) -> str:
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

    # ────── Resolve [variables] ──────
    vars_dict: dict[str, str] = data.get("variables", {}).copy()

    for _ in range(max_nested_depth):
        changed = False
        for key, value in list(vars_dict.items()):
            if not isinstance(value, str):
                continue
            new_value = resolve_double_brace_vars(value, vars_dict, max_depth=max_nested_depth)
            if new_value != value:
                vars_dict[key] = new_value
                logger.debug(f"Resolved variable '{key}': '{value}' -> '{new_value}'")
                changed = True
        if not changed:
            break
    else:
        raise ValueError("Infinite loop detected while resolving [variables]")

    # ────── Parse and fix commands ──────
    command_data = data.get("command", [])
    if not isinstance(command_data, list):
        raise ValueError("[[command]] must be an array of tables")

    commands = []
    for cmd_dict in command_data:
        # Resolve relative cwd
        if "cwd" in cmd_dict and cmd_dict["cwd"] is not None:
            cwd_path = Path(cmd_dict["cwd"])
            if not cwd_path.is_absolute():
                cmd_dict["cwd"] = str(base_dir / cwd_path)

        try:
            cmd = CommandConfig(**cmd_dict)
            commands.append(cmd)
        except TypeError as e:
            raise ValueError(f"Invalid config in [[command]]: {e}") from None

    if not commands:
        raise ValueError("At least one [[command]] is required")

    return RunnerConfig(commands=commands, vars=vars_dict)
