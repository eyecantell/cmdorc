# cmdorc/runner_config.py
from dataclasses import dataclass, field
from typing import Dict, List

from .command_config import CommandConfig


@dataclass(frozen=True)
class RunnerConfig:
    """
    Top-level configuration object returned by load_config().
    Contains everything needed to instantiate a CommandRunner.
    """

    commands: List[CommandConfig]

    vars: Dict[str, str] = field(default_factory=dict)
    """
    Global template variables.
    Example: {"base_directory": "/home/me/project", "tests_directory": "{{ base_directory }}/tests"}
    These act as defaults and can be overridden at runtime via CommandRunner.add_var()/set_vars().
    """

    def __post_init__(self) -> None:
        if not self.commands:
            raise ValueError("At least one command is required")
