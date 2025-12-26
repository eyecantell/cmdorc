# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**cmdorc** is an async-first, trigger-driven Python library for orchestrating shell commands. It's designed for developer tools, TUIs, CI automation, and any application needing event-driven command execution. The library has zero external dependencies (except `tomli` for Python <3.11) and emphasizes predictability, testability, and clean separation of concerns.

## Build, Test, and Development Commands

### Package Management
This project uses **PDM** (Python Dependency Manager):
- `pdm install` - Install dependencies
- `pdm install -d` - Install with dev dependencies
- `pdm add <package>` - Add a new dependency
- `pdm build` - Build distribution packages

### Testing
- `pdm run pytest` - Run all tests with coverage report
- `pdm run pytest tests/test_<module>.py` - Run tests for specific module
- `pdm run pytest -k test_function_name` - Run specific test by name
- `pdm run pytest -v` - Verbose output
- `pdm run pytest --cov=cmdorc --cov-report=html` - Generate HTML coverage report (output in `htmlcov/`)

### Code Quality
- `ruff check .` - Run linter
- `ruff format .` - Format code
- `ruff check --fix .` - Auto-fix linting issues

### Running Examples
Examples can be found in the README.md. To test command execution:
```python
pdm run python -c "import asyncio; from cmdorc import *; asyncio.run(...)"
```

## Architecture Overview

cmdorc follows a **component-based architecture** with strict separation of concerns. The design prioritizes testability through abstract interfaces and pure functions.

### Component Hierarchy

```
CommandOrchestrator (main public API)
├── CommandRuntime (state store)
├── ConcurrencyPolicy (decision logic)
├── TriggerEngine (event routing)
└── CommandExecutor (subprocess management)
```

### Key Design Principles

1. **Separation of Concerns** - Each class has a single, clear responsibility
2. **Immutable Configuration** - `CommandConfig` is frozen; runtime state lives in `CommandRuntime`
3. **Testability First** - Pure functions and mockable interfaces (see `MockExecutor`)
4. **Predictable State** - Explicit state transitions, no hidden mutations
5. **Swappable Backends** - `CommandExecutor` is an ABC for different execution strategies

### Core Components (All Completed ✅)

1. **Configuration System** (`command_config.py`, `load_config.py`, `runtime_vars.py`)
   - `CommandConfig` - Frozen dataclass with validation
   - `RunnerConfig` - Container for commands + global variables
   - `load_config()` - TOML parser (variable templates stored as-is)
   - `runtime_vars.py` - Runtime variable resolution with env var support

2. **State Management** (`command_runtime.py`)
   - Manages command registry, active runs, history, and debounce tracking
   - Comprehensive tests covering all scenarios
   - Uses bounded deques for history retention

3. **Concurrency Policy** (`concurrency_policy.py`)
   - Pure decision logic for `max_concurrent`, `on_retrigger` policies
   - Stateless - takes active runs as input, returns decisions
   - Handles `cancel_and_restart` and `ignore` policies

4. **Executor System** (`command_executor.py`, `local_subprocess_executor.py`, `mock_executor.py`)
   - `CommandExecutor` - Abstract base class
   - `LocalSubprocessExecutor` - Production implementation with timeout, cancellation (SIGTERM → SIGKILL)
   - `MockExecutor` - Test double for unit testing orchestration logic

5. **Data Containers** (`run_result.py`, `types.py`)
   - `RunResult` - Mutable result object with state transitions
   - `ResolvedCommand` - Fully resolved command (no template vars)
   - `RunState` - Enum for PENDING, RUNNING, SUCCESS, FAILED, CANCELLED

6. **TriggerEngine** (`trigger_engine.py`)
   - Pattern matching (exact + wildcards)
   - Callback dispatch and cycle prevention
   - Auto-event handling

7. **RunHandle** (`run_handle.py`)
   - Public facade with async wait support
   - Event-driven completion tracking
   - Clean abstraction over RunResult

8. **CommandOrchestrator** (`command_orchestrator.py`)
   - Main coordinator tying everything together
   - Full lifecycle management
   - Graceful shutdown support

9. **Exception System** (`exceptions.py`)
   - Comprehensive error hierarchy
   - Context-rich error messages

## Configuration System

### Variable Resolution (2 Phases)

Variables are resolved at execution time, not at config load. This enables environment variable overrides and per-run parameterization.

1. **Phase 1: Runtime Merge** - When command executes, merge: global vars → env vars → command vars → call-time vars
   - Global vars: From `[variables]` section in TOML
   - Env vars: From `os.environ`
   - Command vars: From `[command.vars]` section
   - Call-time vars: From `run_command(vars={...})` or `trigger(..., vars={...})`
   - Later sources override earlier ones

2. **Phase 2: Template Substitution** - Create `ResolvedCommand` by substituting `{{ var }}` and `$VAR_NAME` in command strings and env values

**Critical Rule:** Variables frozen per-run. Once a run starts, its variable snapshot is immutable. Orchestrator resolves variables, Executor receives fully resolved data.

**Environment Variable Support:** Use `$HOME` syntax for direct env var references (converted to `{{ HOME }}` internally). Uppercase identifiers only.

### TOML Configuration

```toml
[variables]
base_directory = "."
tests_directory = "{{ base_directory }}/tests"

[[command]]
name = "Tests"
triggers = ["changes_applied", "Tests"]
command = "pytest {{ tests_directory }}"
timeout_secs = 180
max_concurrent = 1
on_retrigger = "cancel_and_restart"  # or "ignore"
cancel_on_triggers = ["prompt_send"]
keep_history = 5
debounce_in_ms = 0
loop_detection = true
```

### cwd Paths
- Relative `cwd` paths in TOML are resolved **relative to the config file location**, not current working directory
- This happens during `load_config()` for predictability

## Trigger System

### Trigger Philosophy
Every string passed to `trigger(event_name)` means: **"Run every command whose `triggers` list contains this exact string."**

No magic. No exceptions. Everything must be explicitly listed in `triggers`.

### Automatic Lifecycle Events

cmdorc emits these events automatically:
- `command_started:<name>` - After concurrency checks, before subprocess
- `command_success:<name>` - Exit code 0
- `command_failed:<name>` - Non-zero exit
- `command_cancelled:<name>` - Command was cancelled

### Cycle Detection
All auto-events propagate a `TriggerContext.seen` set to prevent infinite loops. Commands can opt out via `loop_detection = false` (use with caution).

## State Management Details

### RunResult State Transitions

`RunResult` is mutable but transitions are controlled via methods:
- `mark_running()` - Set state=RUNNING, record start_time
- `mark_success()` - Set state=SUCCESS, success=True
- `mark_failed(error)` - Set state=FAILED, success=False
- `mark_cancelled()` - Set state=CANCELLED, success=None

Once `_finalize()` is called (internally by mark_* methods), the result is immutable.

### Debounce Behavior

Debounce is checked **before** concurrency policy:
- Tracks completion timestamps in `CommandRuntime._last_start`
- Prevents re-runs within `debounce_in_ms` window
- Checked in orchestrator, not in policy logic (policy is stateless)

## Testing Strategy

### Test Organization
- Unit tests for pure logic: `ConcurrencyPolicy`, variable resolution, `RunResult` transitions
- Stateful tests with mocks: `CommandRuntime`, orchestration with `MockExecutor`
- Integration tests: `LocalSubprocessExecutor` with actual subprocesses

### MockExecutor Pattern
Use `MockExecutor` to test orchestration logic without real subprocess overhead:
```python
executor = MockExecutor()
executor._delay = 0.1  # Simulate execution time
executor._should_fail = False  # Control success/failure

# After test:
assert len(executor.started) == 1
assert executor.started[0][1].command == "pytest tests/"
```

### Coverage
- Current: 429 tests with 93% coverage
- Target: High coverage (see `htmlcov/` after running tests)
- Run with: `pytest --cov=cmdorc --cov-report=term-missing`

## Code Style

- **Line length:** 100 characters (enforced by ruff)
- **Target:** Python 3.10+
- **Type hints:** Required for all public APIs
- **Imports:** Sorted automatically by ruff (isort rules)
- **Docstrings:** Use for public APIs and complex logic

### Important Patterns

1. **Frozen dataclasses for configs:** Use `@dataclass(frozen=True)` for immutable configuration
2. **Explicit validation:** Put validation in `__post_init__` methods
3. **No subprocess handles in RunResult:** Executor owns process handles internally
4. **No magic in triggers:** Everything must be explicit in config

## Anti-Patterns to Avoid

- ❌ God objects - Keep orchestrator focused on coordination, not execution
- ❌ Mixing subprocess management with orchestration logic
- ❌ Circular dependencies between components
- ❌ Implicit state changes - All transitions via explicit methods
- ❌ Leaking implementation details through public API

## File Structure

```
src/cmdorc/
├── __init__.py                    # Public API exports
├── command_config.py              # CommandConfig, RunnerConfig, validation
├── command_executor.py            # CommandExecutor ABC
├── command_orchestrator.py        # Main public API (orchestrator)
├── command_runtime.py             # State store (configs, runs, history)
├── concurrency_policy.py          # ConcurrencyPolicy (pure decision logic)
├── exceptions.py                  # Exception hierarchy
├── load_config.py                 # TOML loading (templates stored as-is)
├── local_subprocess_executor.py   # Production subprocess executor
├── mock_executor.py               # Test double for unit testing
├── run_handle.py                  # RunHandle facade
├── run_result.py                  # RunResult, ResolvedCommand, RunState
├── runtime_vars.py                # Runtime variable resolution + merging
├── trigger_engine.py              # Trigger pattern matching and dispatch
└── types.py                       # Type definitions (CommandStatus, etc.)

tests/
├── test_command_executor.py       # Executor system tests
├── test_command_orchestrator.py   # Orchestrator integration tests
├── test_command_runtime.py        # State management tests
├── test_concurrency_policy.py     # Concurrency decision logic tests
├── test_exceptions.py             # Exception hierarchy tests
├── test_load_config.py            # TOML config loading tests
├── test_resolve_variables.py      # Legacy variable resolution tests
├── test_run_handle.py             # RunHandle facade tests
├── test_run_result.py             # RunResult state transition tests
├── test_runtime_vars.py           # Runtime variable resolution tests
├── test_trigger_chain.py          # Trigger chain tracking tests
└── test_trigger_engine.py         # Trigger matching and dispatch tests
```

## Common Development Workflows

### Adding a New Command Configuration Field

1. Add field to `CommandConfig` dataclass in `command_config.py`
2. Add validation in `__post_init__` if needed
3. Update `load_config.py` to parse from TOML
4. Add tests in `test_command_runtime.py` or `test_load_config.py`
5. Update `architecture.md` if it affects design

### Implementing New Executor Backend

1. Subclass `CommandExecutor` ABC
2. Implement `start_run(result, resolved)` and `cancel_run(result)`
3. Optionally implement `supports_feature(feature)` and `cleanup()`
4. Add integration tests similar to `test_command_executor.py`

### Adding New Trigger Pattern Matching

1. Modify `TriggerEngine` (when implemented) pattern matching logic
2. Ensure cycle detection still works
3. Add tests for new pattern types
4. Update `triggers.md` documentation

## Key Files to Reference

- **architecture.md** - Authoritative design document (detailed component contracts)
- **triggers.md** - Trigger system philosophy and examples
- **README.md** - Public API examples and features
- **pyproject.toml** - Dependencies, build config, tool settings

## Current Implementation Status

**All Core Components Completed (Production Ready):**
- Configuration System (CommandConfig, RunnerConfig, load_config)
- State Management (CommandRuntime)
- Concurrency Policy (pure decision logic)
- Executor System (ABC + LocalSubprocessExecutor + MockExecutor)
- Data Containers (RunResult, ResolvedCommand, RunState)
- TriggerEngine (pattern matching, callbacks, cycle prevention)
- RunHandle (public facade with async wait support)
- CommandOrchestrator (main coordinator with full lifecycle management)
- Exception System (comprehensive error hierarchy)
- Variable Resolution (runtime merging and template substitution)

**Statistics:**
- **Test Count:** 429 tests (all passing)
- **Test Files:** 12 test modules
- **Coverage:** 93% overall
- **Python Support:** 3.10+
- **Dependencies:** Zero (except tomli for Python <3.11)
