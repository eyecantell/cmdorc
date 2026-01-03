# Changelog

All notable changes to cmdorc will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.0]

### Added

- **Logging Configuration Utilities** - Optional helpers for configuring cmdorc logging
  - New `setup_logging()` function for easy log configuration (console + rotating file support)
  - New `disable_logging()` function for temporarily silencing logs (useful for tests)
  - New `get_log_file_path()` helper to locate log files for support
  - Configurable log propagation (default: True, integrates with user's logging)
  - Custom format support via `format_string` parameter
  - File rotation: 10MB files, 5 backups by default
  - Exported from top-level: `from cmdorc import setup_logging`
  - Documentation added to README with comprehensive examples
  - 17 new tests covering all logging functionality
  - Example: `examples/advanced/06_logging_setup.py`

- **NullHandler by Default** - Library best practice for Python packages
  - `cmdorc` logger now has a `NullHandler` attached on import
  - Prevents "No handler found" warnings when logging not configured
  - Users must explicitly call `setup_logging()` to see logs
  - Standard practice for well-behaved Python libraries

- **Enhanced Logging Coverage** - Improved observability throughout the codebase
  - DEBUG: Trigger matching now logged (e.g., "Trigger 'build' matched 3 command(s): ['Test', 'Lint', 'Build']")
  - WARNING: Cycle detection now logged before raising exception
  - Fulfills all logging promises documented in README
  - Helps with debugging trigger workflows and cycle issues

## [0.8.1]

### Fixed

- **History ordering corrected** - `get_history()` now returns results in reverse chronological order (most recent first)
  - Previously had inconsistent documentation: `CommandRuntime` said "most recent last", `CommandOrchestrator` said "reverse chronological"
  - Implementation now matches `CommandOrchestrator` documentation: most recent run is at index 0
  - Improves UX: users can access latest run as `history[0]` instead of `history[-1]`
  - Running commands are stored separately in `_active_runs` and never dropped by history retention limits
  - Updated 5 tests to reflect new ordering

## [0.8.0]

### Added

- **Multi-File Config Support** - Load and merge multiple TOML config files
  - New `load_configs(paths)` function for loading multiple files
  - Variables: Global merge with last-in-wins, warns on override
  - Commands: Accumulated from all files, errors on duplicate names
  - Output storage: Global merge with last-in-wins, warns on override
  - Use cases: team environments, multiple environments (dev/staging/prod), feature separation
  - Backward compatible: `load_config()` now wraps `load_configs([path])`
  - Example: `config = load_configs(["base.toml", "tests.toml", "build.toml"])`

- **Per-Command Output Storage Overrides** - Customize retention and file extension per command
  - New `keep_history` field on `CommandConfig` (overrides global `output_storage.keep_history`)
  - New `output_extension` field on `CommandConfig` (overrides global `output_storage.output_extension`)
  - Values passed through `ResolvedCommand` to executor
  - Validation: `keep_history >= -1`, `output_extension` starts with "."
  - Use cases: keep more test history, use .json for benchmarks, unlimited retention for audits
  - Example: `[[command]]\nname = "Tests"\nkeep_history = 50\noutput_extension = ".log"`

- **Orchestrator Lifecycle Triggers** - New automatic triggers for orchestrator startup and shutdown
  - `orchestrator_started` - Emitted via `startup()` method or context manager entry
  - `orchestrator_shutdown` - Emitted during `shutdown()` before cancelling runs
  - Allows users to configure initialization and cleanup commands
  - Context manager pattern (`async with`) automatically calls `startup()`
  - Both triggers use fresh `TriggerContext` for isolation from other trigger chains
  - Shutdown trigger fires BEFORE active runs are cancelled, giving cleanup commands time to complete
  - New `startup()` method provides explicit async initialization (idempotent)
  - Shutdown return dict includes `shutdown_commands_run` count

## [0.7.0]

### Added

- **Async context manager** - `async with CommandOrchestrator(config) as orch:`
  - Automatic `shutdown()` on exit (normal or exception)
  - Existing usage patterns unchanged (purely additive)

- **`output_write_error` property** - Expose output file write failures through API
  - New `output_write_error` field on `RunResult` and `RunHandle`
  - Captures error message when output files fail to write (previously only logged)
  - Allows users to detect filesystem issues without breaking command execution
  - Returns `None` if write succeeded or wasn't attempted

### Changed

- **`off_event()` now returns bool** - Previously returned `None` despite docstring claiming `bool`
  - Returns `True` if callback was found and removed, `False` otherwise
  - Purely additive change (existing code ignoring return value continues to work)
  - Fixes misleading documentation and provides useful feedback

### Fixed

- **CRITICAL: Type annotation mismatch in RunHandle** - `start_time` and `end_time` properties
  - Corrected type annotations from `float | None` to `datetime.datetime | None`
  - Updated docstrings to accurately describe return type (datetime objects, not Unix timestamps)
  - This was a documentation bug - runtime behavior was always datetime, now annotations match reality
  - Fixes type checker errors and IDE autocomplete

- **CRITICAL: Incorrect timestamp calculation in debounce error handling**
  - Fixed `_trigger_run_command()` mixing incompatible time sources (monotonic loop time vs wall-clock time)
  - Now correctly uses `decision.elapsed_ms` already calculated by `ConcurrencyPolicy`
  - Debounce errors now report accurate elapsed times instead of nonsensical values
  - Also improved error handling to use explicit `decision.disallow_reason` instead of guessing

- **Race condition in handle registration** - `run_command()` wrote to `_handles` dict without lock
  - Moved handle registration outside orchestrator lock and use `_register_handle()` helper
  - Now properly uses `_handles_lock` for thread-safe dictionary access
  - Fixes potential RuntimeError when iterating handles while concurrent writes occur
  - Added documentation to sync read methods explaining GIL-based safety

- **Better encapsulation in history loader** - Removed direct private field access
  - Added `set_latest_result()` method to `CommandRuntime`
  - `history_loader.py` now uses public API instead of mutating `_latest_result` dict directly
  - Improves maintainability and follows encapsulation best practices

- **Improved variable resolution error messages** - Now shows which variables failed
  - Error messages now extract and display unresolved variable names
  - Example: "Remaining unresolved variables in '{{ base }}/{{ subdir }}': ['subdir']"
  - Helps users identify circular dependencies or missing variable definitions
  - Much easier debugging experience for complex variable templates

- **Production-safe error checking in RunHandle** - Replaced assertion with explicit check
  - Changed `assert self._completion_event is not None` to explicit RuntimeError
  - Assertions can be disabled with Python's `-O` flag, making code unreliable in production
  - Now raises clear error message: "Internal error: completion event not initialized"
  - More robust error handling even when optimizations are enabled

- **Code cleanup** - Removed unused `_NO_LOOP` sentinel from run_handle.py
  - Dead code removal for cleaner codebase
  - No functional changes

## [0.6.0]

### Added
- **`format_duration()` public utility** - Human-readable duration formatting
  - New `utils.py` module for general-purpose utilities
  - Converts seconds to strings like "452ms", "2.4s", "1m 23s", "2h 5m", "1d 3h", "2w 3d"
  - Available via `from cmdorc import format_duration`
  - Useful for TUI builders and status displays

### Changed
- **`_format_relative_time()` extracted and renamed** - Now public as `format_duration()`
  - Moved from `run_result.py` to new `utils.py` module
  - Removed `suffix` parameter (callers append context themselves)
  - `duration_str` and `time_ago_str` properties now use `format_duration()` internally

## [0.5.0]

### Added
- **`time_ago_str` property** - Human-readable relative time since completion
  - Available on both `RunResult` and `RunHandle`
  - Returns strings like "5s ago", "2h 0m ago", "1w 3d ago"
  - Returns "-" if run hasn't completed yet
  - Useful for TUI displays and status dashboards

- **`_format_relative_time()` helper** - Internal utility for consistent time formatting
  - Centralizes duration/time-ago formatting logic
  - Supports weeks (previously `duration_str` only went up to days)
  - Used by both `duration_str` and `time_ago_str`

### Removed
- **BREAKING: `keep_history` removed from CommandConfig** - Use `keep_in_memory` instead
  - Deprecated in v0.3.0, now raises `ConfigValidationError` if used
  - Migration: Replace `keep_history = N` with `keep_in_memory = N` in `[[command]]` sections

## [0.4.0]

### Added

- **Configurable output file extension** (`output_extension`) - Customize the output file format
  - New `output_extension` field in `OutputStorageConfig` (default: `.txt`)
  - Supports any extension (e.g., `.log`, `.json`, `.out`)
  - Extension is stored in `metadata.toml` for reliable history loading
  - Configure via TOML: `[output_storage]\noutput_extension = ".log"`
  - 10 new tests for configurable extension feature

### Changed
- **`keep_in_memory` default changed from 1 to 3** - More useful default for debugging
  - Most users benefit from having a few recent runs available
  - Still customizable per-command or globally

## [0.3.1]

### Added
- **`get_trigger_graph()` method** - Returns a mapping of triggers to commands they activate
  - Useful for debugging, visualization, and understanding trigger relationships
  - Returns `dict[str, list[str]]` mapping trigger names to command names
  - 5 new tests for trigger graph functionality

### Changed
- **`CommandRuntime.replace_command()` renamed to `update_command()`** - Consistent naming with `CommandOrchestrator.update_command()`
- **Debounce timing now accessed via public methods** - `get_last_start_time()` and `get_last_completion_time()` replace direct access to private attributes
- **TOML output file ordering improved** - `output_file` and `metadata_file` fields now appear before `[resolved_command]` section to avoid being parsed as nested keys

### Fixed
- **Memory leak in `remove_command()`** - Now properly cleans up `_last_completion` tracking when commands are removed
- **Incorrect `ConcurrencyLimitError` construction** - Now uses proper keyword arguments matching exception signature

### Removed
- **Dead code: `CommandRuntime.check_debounce()` method** - Debounce logic is handled by `ConcurrencyPolicy.decide()`

## [0.3.0]

### Added
- **Startup History Loading** - Persisted command runs are now automatically loaded on startup
  - Loads up to `keep_in_memory` runs from disk for each command
  - Respects memory limits (loads min(keep_in_memory, files_available))
  - Works with unlimited memory (`keep_in_memory = -1`)
  - Only loads for commands with `keep_in_memory > 0`
  - Gracefully handles corrupted/missing files
  - Automatic latest_result update with newest loaded run
  - 20 new comprehensive tests for metadata parsing and history loading

- **Metadata Parser Module** (`metadata_parser.py`) - Reconstructs RunResult from TOML files
  - Parses `metadata.toml` files created by `RunResult.to_toml()`
  - Reads sibling `output.txt` files for command output
  - Handles missing/corrupted files gracefully
  - Validates required fields and state enums
  - Preserves all run metadata (timestamps, trigger chains, resolved commands)

- **History Loader Module** (`history_loader.py`) - Populates CommandRuntime from disk
  - Loads most recent runs based on modification time
  - Ignores run directories for unknown commands (multi-instance safety)
  - Skips directories without metadata.toml
  - Comprehensive logging for visibility

- **Output Storage Feature** - Automatic persistence of command outputs to disk
  - Configure via `[output_storage]` section in TOML with `keep_history` setting
  - `keep_history = 0`: Disabled (no files written) [default]
  - `keep_history = -1`: Unlimited (write all files, never delete)
  - `keep_history = N` (N > 0): Keep last N runs per command (delete oldest)
  - Metadata saved as `metadata.toml` files with full run details (state, duration, trigger chain, resolved command)
  - Command output saved as `output.txt` files (stdout + stderr)
  - Directory-per-run structure: `.cmdorc/outputs/{command_name}/{run_id}/`
  - Configurable directory and pattern via TOML
  - Automatic retention policy enforcement (deletes oldest run directories when limit exceeded)
  - Accessible via `RunHandle.output_file` and `RunHandle.metadata_file` properties
  - Works with successful, failed, and cancelled runs
  - Zero new dependencies (manual TOML generation)
  - No performance impact when disabled (default)

- **Output Capture on Cancellation** - Commands now preserve output when cancelled
  - Cancelled commands capture output before termination (if process exits gracefully within grace period)
  - Works with user cancellation and auto-cancel triggers
  - Best-effort capture with 0.5s timeout after SIGTERM
  - Falls back gracefully if process requires SIGKILL (output not captured)

- **RunHandle.resolved_command property** - Exposes the fully resolved command details
  - Access resolved command string (with all variable substitutions)
  - Access working directory, environment variables, timeout settings
  - Access variable snapshot used for the run
  - Returns `ResolvedCommand | None` (None before command execution begins)
  - Useful for debugging and understanding exactly what was executed
  - 2 new comprehensive tests for `resolved_command` property

- **CommandOrchestrator.preview_command() method** - Preview command resolution without execution
  - Dry-run capability to see what would be executed before running
  - Resolves all variables and returns `ResolvedCommand`
  - Same signature as `run_command()` for consistency (name, vars)
  - Useful for debugging, validation, UI previews, and "what-if" scenarios
  - Raises `CommandNotFoundError` if command doesn't exist
  - Raises `ValueError` if variable resolution fails
  - 8 comprehensive tests covering all scenarios (basic, variables, env, errors, etc.)

- **load_config()** now parses `[output_storage]` section from TOML files

- **Debounce Mode** (`debounce_mode`) - Choose between start-based and completion-based debouncing
  - `"start"` (default): Prevents starts within debounce_in_ms of last START time (backward compatible)
  - `"completion"`: Prevents starts within debounce_in_ms of last COMPLETION time (recommended for most users)
  - Addresses unexpected behavior where long-running commands could retrigger immediately after completion
  - Configurable per-command via `debounce_mode` field in TOML

- **Loop Detection Warnings** - Commands with `loop_detection=False` now emit warnings
  - Warns at config load time: "infinite trigger cycles are possible. Use with extreme caution."
  - Makes dangerous configuration more visible to users

### Changed
- **BREAKING: OutputStorageConfig.pattern is no longer configurable** (v0.3.0)
  - Removed `pattern` field from OutputStorageConfig
  - Files are always stored as `{command_name}/{run_id}/` for retention enforcement
  - Custom patterns caused silent retention failures
  - If pattern is specified in TOML, raises ConfigValidationError with clear message
  - No migration needed (pattern was rarely customized)

- **BREAKING: CommandConfig.keep_history renamed to keep_in_memory** (v0.3.0)
  - Clarifies that this setting controls in-memory history, not disk persistence
  - Backward compatibility provided via deprecation warning in load_config()
  - Old TOML configs using `keep_history` will work but emit warning
  - Support for `keep_history` will be removed in v0.4.0
  - Migration: Simply rename `keep_history` to `keep_in_memory` in `[[command]]` sections

- **CommandConfig.keep_in_memory now supports unlimited (-1)**
  - `keep_in_memory = -1`: Unlimited in-memory history (new)
  - `keep_in_memory = 0`: No history (unchanged)
  - `keep_in_memory = N > 0`: Keep last N runs (unchanged)

- **CommandRuntime.add_to_history() public method added**
  - Used by history loader to populate runtime on startup
  - Respects keep_in_memory limits automatically via deque maxlen

- **CommandOrchestrator.__init__() now loads persisted history**
  - Automatically loads up to `keep_in_memory` runs from disk on startup
  - Only when output_storage is enabled
  - Logs count of loaded runs per command

- **Retention Timing** - Clarified that cleanup happens BEFORE new runs start
  - Updated `_enforce_output_retention()` docstring with explicit timing warning
  - Old data deleted even if subsequent run fails to start (intentional to prevent storage overflow)
  - Prevents exceeding storage limits by making room before execution

- **Completion Time Tracking** - CommandRuntime now tracks both start and completion times
  - `_last_start`: Used for debounce_mode="start"
  - `_last_completion`: Used for debounce_mode="completion"
  - Recorded automatically in `mark_run_complete()`

- **OutputStorageConfig** added to public API exports
- **LocalSubprocessExecutor** now accepts `output_storage` parameter
- **CommandOrchestrator** passes `output_storage` to executor when creating default executor
- **RunResult** now includes `metadata_file` and `output_file` fields (Path | None)
- **RunHandle** exposes `metadata_file` and `output_file` properties
- **load_config()** now parses `[output_storage]` section from TOML files

## [0.2.1] - 2025-12-17

### Fixed
- **Critical PyPI packaging bug**: Version 0.2.0 published to PyPI missing all Python source files from `src/cmdorc/` due to misconfigured `includes` in `pyproject.toml`. Only `CHANGELOG.md` and `py.typed` were included, making the package non-functional. All users should upgrade to 0.2.1 immediately.
- Build configuration now uses PDM's automatic package discovery instead of explicit includes
- **Do not use version 0.2.0** - it is non-functional. This was a packaging error on PyPI, not a code issue.

## [0.2.0] - 2025-12-16
⚠️ **DO NOT USE** - This version on PyPI is broken due to missing source files. Use 0.2.1 instead.

### Added
- **Trigger Chain Tracking (Breadcrumbs)** - Complete visibility into trigger sequence
  - `TriggerContext.history` field for ordered event breadcrumb trail
  - `RunResult.trigger_chain` field capturing full path to each command execution
  - `RunHandle.trigger_chain` property for easy access with copy-on-read protection
  - Enhanced `TriggerCycleError` with detailed cycle point identification
- `examples/advanced/04_trigger_chains.py` - Complete trigger chain example
- 14 new comprehensive tests for breadcrumb functionality
- Documentation updates (README.md, architecture.md) with trigger chain examples

### Changed
- `TriggerContext` now includes both `seen` (for performance) and `history` (for breadcrumbs)
- `RunResult.__repr__()` now shows trigger chain in debug output
- `RunHandle.__repr__()` now shows trigger chain in debug output
- Auto-trigger propagation via `_emit_auto_trigger()` inherits parent chains
- `_prepare_run()` signature updated to accept `trigger_chain` parameter

### Improved
- Better cycle detection error messages with explicit cycle point identification
- Copy-on-return semantics for all public chain access to prevent mutations
- Chain propagation through entire trigger lifecycle (root → nested → auto-triggers)

### Performance
- No performance degradation: `seen` set still O(1) for cycle detection
- `history` list appends are O(1) amortized; chain copying O(n) where n < 10 typically

### Backward Compatibility
- `trigger_event` field retained for backward compatibility
- All existing APIs unchanged; new fields are additive only
- Existing tests all pass (357 total, up from 343)

## [0.1.0] - 2024-12-10

### Added
- Initial release of cmdorc
- Async-first command orchestration with trigger-based execution
- TOML configuration support with template variables
- Lifecycle events (`command_started`, `command_success`, `command_failed`, `command_cancelled`)
- Concurrency policies (`max_concurrent`, `on_retrigger`, `debounce_in_ms`)
- Cycle detection with `TriggerContext` propagation
- `LocalSubprocessExecutor` with timeout and cancellation support
- `MockExecutor` for deterministic testing
- `RunHandle` API with async `wait()` support
- `CommandRuntime` state management with bounded history
- 7 custom exceptions for precise error handling:
  - `CommandNotFoundError`
  - `DebounceError`
  - `ConcurrencyLimitError`
  - `TriggerCycleError`
  - `ConfigValidationError`
  - `ExecutorError`
  - `OrchestratorShutdownError`
- 19+ comprehensive examples (basic, workflows, advanced, file_watching)
- Full type hints with PEP 561 support
- 343 tests with 94% coverage
- Comprehensive documentation (README.md, architecture.md, triggers.md)
