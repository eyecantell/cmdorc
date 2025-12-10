# Changelog

All notable changes to cmdorc will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
