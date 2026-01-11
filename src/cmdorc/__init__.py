__version__ = "0.10.0"

import logging

from .command_config import CommandConfig, OutputStorageConfig, RunnerConfig
from .command_executor import CommandExecutor
from .command_orchestrator import CommandOrchestrator
from .command_runtime import CommandRuntime  # noqa: F401 - accessible but not in __all__
from .concurrency_policy import ConcurrencyPolicy  # noqa: F401 - accessible but not in __all__
from .exceptions import (
    CmdorcError,
    CommandNotFoundError,
    ConcurrencyLimitError,
    ConfigValidationError,
    DebounceError,
    ExecutorError,
    OrchestratorShutdownError,
    TriggerCycleError,
    VariableResolutionError,
)
from .load_config import load_config, load_configs
from .local_subprocess_executor import LocalSubprocessExecutor
from .logging_config import disable_logging, get_log_file_path, setup_logging
from .mock_executor import MockExecutor
from .run_handle import RunHandle
from .run_result import ResolvedCommand, RunResult, RunState
from .trigger_engine import TriggerEngine  # noqa: F401 - accessible but not in __all__
from .types import CommandStatus, NewRunDecision, TriggerContext
from .utils import format_duration

# Library best practice: add NullHandler to prevent "No handler found" warnings
logging.getLogger("cmdorc").addHandler(logging.NullHandler())

__all__ = [
    # Version
    "__version__",
    # Core Components
    "CommandConfig",
    "CommandOrchestrator",
    "CommandStatus",
    "load_config",
    "load_configs",
    "NewRunDecision",
    "OutputStorageConfig",
    "ResolvedCommand",
    "RunnerConfig",
    "RunHandle",
    "RunResult",
    "RunState",
    "TriggerContext",
    # Utilities
    "format_duration",
    # Logging utilities
    "disable_logging",
    "get_log_file_path",
    "setup_logging",
    # Executors
    "CommandExecutor",
    "LocalSubprocessExecutor",
    "MockExecutor",
    # Exceptions
    "CmdorcError",
    "CommandNotFoundError",
    "ConcurrencyLimitError",
    "ConfigValidationError",
    "DebounceError",
    "ExecutorError",
    "OrchestratorShutdownError",
    "TriggerCycleError",
    "VariableResolutionError",
]
