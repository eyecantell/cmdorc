# Changelog

All notable changes to cmdorc will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
