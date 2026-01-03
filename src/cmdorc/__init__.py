__version__ = "0.9.0"

import logging

from .command_config import CommandConfig, OutputStorageConfig, RunnerConfig
from .command_executor import CommandExecutor
from .command_orchestrator import CommandOrchestrator
from .command_runtime import CommandRuntime
from .concurrency_policy import ConcurrencyPolicy
from .exceptions import (
    CmdorcError,
    CommandNotFoundError,
    ConcurrencyLimitError,
    ConfigValidationError,
    DebounceError,
    ExecutorError,
    OrchestratorShutdownError,
    TriggerCycleError,
)
from .load_config import load_config, load_configs
from .local_subprocess_executor import LocalSubprocessExecutor
from .logging_config import disable_logging, get_log_file_path, setup_logging
from .mock_executor import MockExecutor
from .run_handle import RunHandle
from .run_result import ResolvedCommand, RunResult, RunState
from .trigger_engine import TriggerEngine
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
    "CommandRuntime",
    "CommandStatus",
    "ConcurrencyPolicy",
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
    "TriggerEngine",
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
]
