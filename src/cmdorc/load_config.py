# cmdorc/load_config.py
import tomli
from typing import Dict
from .runner_config import RunnerConfig
from .command_config import CommandConfig


def load_config(path: str) -> RunnerConfig:
    """
    Load and validate a TOML config file into a RunnerConfig.
    
    - Parses the entire TOML.
    - Validates and creates CommandConfig objects for [[command]] sections.
    - Extracts [variables] as defaults (optional).
    - Performs simple nested resolution for {{ }} in vars (up to 5 levels to prevent loops).
    
    Raises ValueError on invalid data or missing required fields.
    """
    with open(path, "rb") as f:
        data = tomli.load(f)
    
    # Extract and resolve [variables] (global defaults)
    vars_dict: Dict[str, str] = data.get("variables", {})
    
    # Simple recursive resolution for nested {{ }}
    for _ in range(5):  # Max depth to avoid infinite loops
        changed = False
        for key, value in list(vars_dict.items()):
            try:
                new_value = value.format_map(vars_dict)
                if new_value != value:
                    vars_dict[key] = new_value
                    changed = True
            except KeyError as e:
                raise ValueError(f"Missing variable in [variables].{key}: {e}")
        if not changed:
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
            raise ValueError(f"Invalid config in [[command]]: {e}")
    
    if not commands:
        raise ValueError("At least one [[command]] is required")
    
    return RunnerConfig(commands=commands, vars=vars_dict)