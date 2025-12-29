# cmdorc: Command Orchestrator - Async, Trigger-Driven Shell Command Runner

[![PyPI version](https://badge.fury.io/py/cmdorc.svg)](https://badge.fury.io/py/cmdorc)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-439%20passing-brightgreen)](https://github.com/eyecantell/cmdorc/tree/main/tests)
[![Coverage](https://img.shields.io/badge/coverage-94%25-brightgreen)](https://github.com/eyecantell/cmdorc)
[![Downloads](https://pepy.tech/badge/cmdorc)](https://pepy.tech/project/cmdorc)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Typing: PEP 561](https://img.shields.io/badge/typing-PEP%20561-blue)](https://peps.python.org/pep-0561/)

**cmdorc** is a lightweight, **async-first** Python library for running shell commands in response to string-based **triggers**. Built for developer tools, TUIs (like [VibeDir](https://github.com/yourusername/vibedir)), CI automation, or any app needing event-driven command orchestration.

Zero external dependencies (pure stdlib + `tomli` for Python <3.11). Predictable. Extensible. No magic.

Inspired by Make/npm scripts - but instead of file changes, you trigger workflows with **events** like `"lint"`, `"tests_passed"`, or `"deploy_ready"`.

## Features

- **Trigger-Based Execution** - Fire any string event → run configured commands
- **Auto-Events** - `command_started:Lint`, `command_success:Lint`, `command_failed:Tests`, etc.
- **Full Async + Concurrency Control** - Non-blocking, cancellable, timeout-aware, with debounce
- **Async Context Manager** - `async with CommandOrchestrator(config) as orch:` for automatic cleanup
- **Smart Retrigger Policies** - `cancel_and_restart` or `ignore`
- **Cancellation Triggers** - Auto-cancel commands on certain events
- **Rich State Tracking** - Live runs, history, durations, output capture
- **Output Storage** - Automatic persistence of outputs to disk with retention policies
- **Template Variables** - `{{ base_directory }}`, nested resolution, runtime overrides
- **TOML Config + Validation** - Clear, declarative setup with validation
- **Cycle Detection** - Prevents infinite trigger loops with clear warnings
- **Frontend-Friendly** - Perfect for TUIs (Textual, Bubble Tea), status icons (Pending/Running/Success/Failure/Cancelled), logs
- **Minimal dependencies**: Only `tomli` for Python <3.11 (stdlib `tomllib` for 3.11+)
- **Deterministic, Safe Template Resolution** with nested `{{var}}` support and cycle protection

See [architecture.md](architecture.md) for detailed design and component responsibilities.

## Installation

```bash
pip install cmdorc
```

Requires Python 3.10+

**Want to learn by example?** Check out the [examples/](examples/) directory for runnable demonstrations of all features - from basic usage to advanced patterns.

## Quick Start

### 1. Create `cmdorc.toml`

```toml
[variables]
base_directory = "."
tests_directory = "{{ base_directory }}/tests"

[[command]]
name = "Lint"
triggers = ["changes_applied"]
command = "ruff check {{ base_directory }}"
cancel_on_triggers = ["prompt_send", "exit"]
max_concurrent = 1
on_retrigger = "cancel_and_restart"
debounce_in_ms = 500  # Wait 500ms after last trigger before running
timeout_secs = 300
keep_in_memory = 3
loop_detection = true

[[command]]
name = "Tests"
triggers = ["command_success:Lint", "Tests"]
command = "pytest {{ tests_directory }} -q"
timeout_secs = 180
keep_in_memory = 5
loop_detection = true
```

### 2. Run in Python

```python
import asyncio
from cmdorc import CommandOrchestrator, load_config

async def main():
    config = load_config("cmdorc.toml")

    # Recommended: Use async context manager for automatic cleanup
    async with CommandOrchestrator(config) as orchestrator:
        # Trigger a workflow
        await orchestrator.trigger("changes_applied")  # → Lint → (if success) Tests

        # Run a command and get handle for waiting
        handle = await orchestrator.run_command("Tests")
        result = await handle.wait()  # Blocks until complete (with optional timeout)
        print(f"Tests: {result.state.value} ({result.duration_str})")

        # Fire-and-forget (no await on handle.wait())
        handle = await orchestrator.run_command("Lint")  # Starts async
        # ... do other work ...
        await handle.wait()  # Wait later if needed

        # Pass runtime variables for this run only
        await orchestrator.run_command("Deploy", vars={"env": "production", "region": "us-east-1"})

        # Get status and history
        status = orchestrator.get_status("Tests")  # CommandStatus with active runs, etc.
        history = orchestrator.get_history("Tests", limit=5)  # List[RunResult]

        # Cancel running command
        await orchestrator.cancel_command("Lint", comment="User cancelled")

        # Or cancel everything
        await orchestrator.cancel_all()

    # shutdown() called automatically on exit (normal or exception)

asyncio.run(main())
```

**See it in action:** Run `examples/basic/01_hello_world.py` or `examples/basic/02_simple_workflow.py` to see a working example immediately.

## Core Concepts

### Triggers & Auto-Events

- Any string can be a trigger: `"build"`, `"deploy"`, `"hotkey:f5"`
- Special auto-triggers (emitted automatically):
  - `command_started:MyCommand` - Command begins execution
  - `command_success:MyCommand` - Command exits with code 0
  - `command_failed:MyCommand` - Command exits non-zero
  - `command_cancelled:MyCommand` - Command was cancelled

### Lifecycle Example

```python
await orchestrator.trigger("build")

# If "build" triggers a command named "Compile":
# 1. command_started:Compile    ← can trigger other commands
# 2. ... subprocess runs ...
# 3. command_success:Compile    ← triggers on success
```

**Example:** See `examples/basic/02_simple_workflow.py` for a working workflow that chains Lint → Test using lifecycle triggers.

### Cancellation

Use `cancel_on_triggers` to auto-cancel long-running tasks:

```toml
cancel_on_triggers = ["user_escape", "window_close"]
```

### Concurrency & Retrigger Policy

```toml
max_concurrent = 1
on_retrigger = "cancel_and_restart"  # default
# or "ignore" to skip if already running
debounce_in_ms = 500  # Throttle rapid triggers
```

### Trigger Chains (Breadcrumbs)

Every run tracks the sequence of triggers that led to its execution:

```python
# Manual run
handle = await orchestrator.run_command("Tests")
print(handle.trigger_chain)  # []

# Triggered run
await orchestrator.trigger("user_saves")  # → Lint → Tests
handle = orchestrator.get_active_handles("Tests")[0]
print(handle.trigger_chain)
# ["user_saves", "command_started:Lint", "command_success:Lint"]
```

**Use cases:**
- **Debugging:** "Why did this command run?"
- **UI Display:** Show breadcrumb trail in status bar or logs
- **Cycle Errors:** See the full path that caused a cycle

**Access via:**
- `RunHandle.trigger_chain` - Live runs
- `RunResult.trigger_chain` - Historical runs (via `get_history()`)

See `examples/advanced/04_trigger_chains.py` for a complete example.

## API Highlights

```python
await orchestrator.trigger("build")                    # Fire event
await orchestrator.cancel_command("Tests")             # Cancel specific
orchestrator.get_status("Lint")                        # → CommandStatus (IDLE, RUNNING, etc.)
orchestrator.get_history("Lint", limit=10)             # → List[RunResult]
orchestrator.list_commands()                           # → List[str] of command names
```

### RunHandle (Returned from run_command)

```python
handle = await orchestrator.run_command("Tests")
result = await handle.wait(timeout=30)  # Await completion (event-driven, no polling)

# Properties (read-only)
handle.state            # RunState: PENDING, RUNNING, SUCCESS, FAILED, CANCELLED
handle.success          # bool or None
handle.output           # str (stdout + stderr)
handle.duration_str     # "1m 23s", "452ms", "1h 5m", "1d 3h"
handle.is_finalized     # bool: True if completed
handle.start_time       # datetime.datetime or None: When run started
handle.end_time         # datetime.datetime or None: When run ended
handle.comment          # str: Cancellation reason or note
handle.resolved_command # ResolvedCommand | None: Fully resolved command details
                        #   (command string, cwd, env vars, timeout, variable snapshot)
handle.metadata_file    # Path | None: Path to metadata.toml (if output_storage enabled)
handle.output_file      # Path | None: Path to output file (if output_storage enabled)
```

### RunResult (Accessed via RunHandle._result or history)

Internal data container; use RunHandle for public interaction.

## Configuration

### Load from TOML

```python
orchestrator = CommandOrchestrator(load_config("cmdorc.toml"))
```

**Example:** See `examples/basic/03_toml_config/` for a complete TOML-based workflow setup.

### Or Pass Programmatically

```python
from cmdorc import CommandConfig, CommandOrchestrator

commands = [
    CommandConfig(
        name="Format",
        command="black .",
        triggers=["Format", "changes_applied"]
    )
]

orchestrator = CommandOrchestrator(commands)
```

**Example:** See `examples/basic/01_hello_world.py` or `examples/basic/02_simple_workflow.py` for programmatic configuration patterns.

### Async Context Manager

Use `async with` for automatic cleanup - `shutdown()` is called automatically on exit (normal or exception):

```python
async with CommandOrchestrator(config) as orchestrator:
    await orchestrator.trigger("build")
    # ... orchestrator is fully functional here ...

# shutdown() called automatically - all running commands cancelled, resources cleaned up
```

This is the **recommended pattern** for most use cases. Benefits:
- No need to remember `await orchestrator.shutdown()`
- Cleanup happens even if exceptions occur
- Existing usage without `async with` still works (purely additive)

For long-lived applications (TUIs, servers), you can still use manual lifecycle:

```python
orchestrator = CommandOrchestrator(config)
try:
    # ... long-running application ...
finally:
    await orchestrator.shutdown(timeout=30.0, cancel_running=True)
```

### Output Storage

Automatically persist command outputs to disk with configurable retention:

```toml
[output_storage]
directory = ".cmdorc/outputs"           # Where to store files (default: .cmdorc/outputs)
keep_history = 10                       # Keep last 10 runs per command
output_extension = ".log"               # Custom extension (default: .txt)

# Files are always organized as: {command_name}/{run_id}/
# This structure is required for retention enforcement.

# Options for keep_history:
# keep_history = 0    # Disabled (no files written) [default]
# keep_history = -1   # Unlimited (keep all files, never delete)
# keep_history = N    # Keep last N runs (oldest deleted automatically)
```

**File Structure:**
```
.cmdorc/outputs/
  Tests/
    run-123e4567/           # Each run gets its own directory
      metadata.toml         # Run metadata (state, duration, trigger chain, resolved command)
      output.log            # Command output (uses configured extension)
    run-456f8901/
      metadata.toml
      output.log
```

**Access via RunHandle:**
```python
handle = await orchestrator.run_command("Tests")
await handle.wait()

# Access output files
if handle.output_file:
    print(f"Output saved to: {handle.output_file}")
    with open(handle.output_file) as f:
        print(f.read())

if handle.metadata_file:
    print(f"Metadata saved to: {handle.metadata_file}")
```

**Features:**
- ✅ Works with successful, failed, and cancelled runs
- ✅ Automatic retention policy enforcement (deletes oldest when limit exceeded)
- ✅ Zero new dependencies (manual TOML generation)
- ✅ No performance impact when disabled (default)
- ✅ Cancelled commands preserve output if process exits gracefully


### Memory vs. Disk History

cmdorc separates **in-memory history** (for API queries) from **disk persistence** (for long-term storage):

**In-Memory History** (`CommandConfig.keep_in_memory`):
- Controls how many runs are kept in RAM
- Affects `get_history()` API results  
- Faster access, limited by memory
- Loaded from disk on startup (if output_storage enabled)

**Disk History** (`OutputStorageConfig.keep_history`):
- Controls how many run directories are kept on disk
- Enables metrics analysis and auditing
- Survives restarts

**Configuration Examples:**

```toml
# Pattern 1: Small memory cache, large disk archive
[output_storage]
keep_history = 100  # Keep 100 runs on disk

[[command]]
name = "Tests"
keep_in_memory = 3  # Only 3 in RAM for UI queries
# → On startup: Loads 3 most recent from disk

# Pattern 2: No persistence, memory only  
[output_storage]
keep_history = 0  # Disabled (no files written)

[[command]]
name = "Lint"
keep_in_memory = 10  # Keep 10 in RAM only

# Pattern 3: Audit trail (unlimited disk, limited memory)
[output_storage]
keep_history = -1  # Never delete files

[[command]]
name = "Deploy"
keep_in_memory = 5  # Only 5 recent in RAM
# → On startup: Loads 5 most recent from disk

# Pattern 4: Large memory for dashboard
[output_storage]
keep_history = 50

[[command]]
name = "Benchmark"
keep_in_memory = -1  # Unlimited memory
# → On startup: Loads all 50 runs from disk
```

**Startup Loading:**
- Automatically loads up to `keep_in_memory` runs on initialization
- Only when `output_storage` is enabled
- Loads most recent runs (sorted by modification time)
- Gracefully handles corrupted/missing files
- Updates `latest_result` with newest loaded run

**Example:**
```python
# First run: create and execute commands
config = load_config("cmdorc.toml")
orch1 = CommandOrchestrator(config)
# ... run commands, outputs written to disk ...

# Later (after restart): history auto-loaded
orch2 = CommandOrchestrator(config)
history = orch2.get_history("Tests")  # Already populated!
print(f"Loaded {len(history)} runs from disk")
```

## Introspection (Great for UIs)

```python
orchestrator.get_active_handles("Tests")  # → List[RunHandle]
orchestrator.get_handle_by_run_id("run-uuid")  # → RunHandle or None
orchestrator.get_trigger_graph()  # → dict[str, list[str]] (triggers → commands)
```

### Preview Commands (Dry-Run)

Preview what would be executed without actually running:

```python
# Preview with variable overrides
preview = orchestrator.preview_command("Deploy", vars={"env": "staging", "region": "us-east-1"})

print(f"Would run: {preview.command}")
# Output: "kubectl apply -f deploy.yaml --env=staging --region=us-east-1"

print(f"Working directory: {preview.cwd}")
# Output: "/home/user/project"

print(f"Environment: {preview.env}")
# Output: {...merged system env + config env...}

print(f"Timeout: {preview.timeout_secs}s")
# Output: 300

print(f"Variables used: {preview.vars}")
# Output: {"env": "staging", "region": "us-east-1", "base_dir": "/home/user/project"}

# Confirm before running
if user_confirms():
    handle = await orchestrator.run_command("Deploy", vars={"env": "staging", "region": "us-east-1"})
```

Use cases:
- **Dry-runs** - See exactly what will execute before running
- **Debugging** - Troubleshoot variable resolution issues
- **Validation** - Verify configuration changes
- **UI previews** - Show users what will happen before they confirm

## Why cmdorc?

You're building a TUI, VSCode extension, or LLM agent that says:  
> "When the user saves → run formatter → then tests → show results live"

`cmdorc` is the **battle-tested backend** that handles:
- Async execution
- Cancellation on navigation
- State for your UI
- Safety (no cycles, no deadlocks)

**Separate concerns**: Let your UI be beautiful. Let `cmdorc` handle the boring parts: async, cancellation, state, safety.

See [architecture.md](architecture.md) for detailed component design.

## Advanced Features

### Lifecycle Hooks with Callbacks

```python
orchestrator.on_event("command_started:Tests", lambda handle, context: ui.show_spinner())
orchestrator.on_event("command_success:Tests", lambda handle, context: ui.hide_spinner())
```

**Example:** See `examples/advanced/01_callbacks_and_hooks.py` for patterns including exact event matching, wildcard patterns, and lifecycle callbacks.

### Template Variables

```python
orchestrator = CommandOrchestrator(config, vars={"env": "production", "region": "us-west-2"})
# Now commands can use {{ env }} and {{ region }}
```

**Example:** See `examples/basic/04_runtime_variables.py` for variable resolution and templating patterns.

### Concurrency & Retrigger Policies

Control how commands behave when triggered multiple times:
- `max_concurrent` - Limit parallel executions (0 = unlimited)
- `on_retrigger` - `cancel_and_restart` or `ignore`
- `debounce_in_ms` - Delay re-runs by milliseconds
- `debounce_mode` - `"start"` or `"completion"` (controls debounce timing)

**Debounce Modes:**
- `"start"` (default): Prevents starts within debounce_in_ms of last START time
  Good for: Preventing rapid button mashing, duplicate triggers
- `"completion"`: Prevents starts within debounce_in_ms of last COMPLETION time
  Good for: Ensuring minimum gap between consecutive runs of long-running commands

**Example:** See `examples/advanced/03_concurrency_policies.py` for demonstrations of all concurrency control patterns.

### Error Handling & Exceptions

Handle failures gracefully with cmdorc-specific exceptions:
- `CommandNotFoundError` - Command not in registry
- `ConcurrencyLimitError` - Too many concurrent runs
- `DebounceError` - Triggered too soon after last run

**Example:** See `examples/advanced/02_error_handling.py` for comprehensive error handling patterns and recovery strategies.

### History Retention

```toml
keep_in_memory = 10  # Keep last 10 runs for debugging
```

```python
history = orchestrator.get_history("Tests")
for result in history:
    print(f"{result.run_id}: {result.state.value} in {result.duration_str}")
```

**Example:** See `examples/basic/05_status_and_history.py` for status tracking and history introspection patterns.

## Testing & Quality

cmdorc maintains high quality standards:
- **424 tests** with 93% code coverage
- Full async/await testing with `pytest-asyncio`
- Type hints throughout with PEP 561 compliance
- Linted with ruff for consistent style

Run tests locally:
```bash
pdm run pytest                          # Run all tests
pdm run pytest --cov=cmdorc            # With coverage
ruff check . && ruff format .           # Lint and format
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development setup
- Running tests locally
- Code style guidelines
- Pull request process

## License

MIT License - See [LICENSE](LICENSE) for details

## Todo
- Move TriggerChain utilities from textual-cmdorc to here.
- Add optional metrics (see [telemetry](telemetry.md))
---

**Made with ❤️ for async Python developers**