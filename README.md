# cmdorc: Command Orchestrator - Async, Trigger-Driven Shell Command Runner

[![PyPI version](https://badge.fury.io/py/cmdorc.svg)](https://badge.fury.io/py/cmdorc)  
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

**cmdorc** is a lightweight, **async-first** Python library for running shell commands in response to string-based **triggers**. Built for developer tools, TUIs (like [VibeDir](https://github.com/yourusername/vibedir)), CI automation, or any app needing event-driven command orchestration.

Zero external dependencies (pure stdlib + `tomli` for Python <3.11). Predictable. Extensible. No magic.

Inspired by Make/npm scripts - but instead of file changes, you trigger workflows with **events** like `"lint"`, `"tests_passed"`, or `"deploy_ready"`.

## Features

- **Trigger-Based Execution** - Fire any string event → run configured commands
- **Auto-Events** - `command_started:Lint`, `command_success:Lint`, `command_failed:Tests`, etc.
- **Full Async + Concurrency Control** - Non-blocking, cancellable, timeout-aware, with debounce
- **Smart Retrigger Policies** - `cancel_and_restart` or `ignore`
- **Cancellation Triggers** - Auto-cancel commands on certain events
- **Rich State Tracking** - Live runs, history, durations, output capture
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
keep_history = 3
loop_detection = true

[[command]]
name = "Tests"
triggers = ["command_success:Lint", "Tests"]
command = "pytest {{ tests_directory }} -q"
timeout_secs = 180
keep_history = 5
loop_detection = true
```

### 2. Run in Python

```python
import asyncio
from cmdorc import CommandOrchestrator, load_config

async def main():
    config = load_config("cmdorc.toml")
    orchestrator = CommandOrchestrator(config)

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

    # Graceful shutdown
    await orchestrator.shutdown(timeout=30.0, cancel_running=True)

asyncio.run(main())
```

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
handle.state          # RunState: PENDING, RUNNING, SUCCESS, FAILED, CANCELLED
handle.success        # bool or None
handle.output         # str (stdout + stderr)
handle.duration_str   # "1m 23s", "452ms", "1h 5m", "1d 3h"
handle.is_finalized   # bool: True if completed
handle.start_time     # datetime.datetime or None
handle.end_time       # datetime.datetime or None
handle.comment        # str: Cancellation reason or note
```

### RunResult (Accessed via RunHandle._result or history)

Internal data container; use RunHandle for public interaction.

## Configuration

### Load from TOML

```python
orchestrator = CommandOrchestrator(load_config("cmdorc.toml"))
```

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

## Introspection (Great for UIs)

```python
orchestrator.get_active_handles("Tests")  # → List[RunHandle]
orchestrator.get_handle_by_run_id("run-uuid")  # → RunHandle or None
orchestrator.get_trigger_graph()  # → dict[str, list[str]] (triggers → commands)
```

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

### Template Variables

```python
orchestrator = CommandOrchestrator(config, vars={"env": "production", "region": "us-west-2"})
# Now commands can use {{ env }} and {{ region }}
```

### History Retention

```toml
keep_history = 10  # Keep last 10 runs for debugging
```

```python
history = orchestrator.get_history("Tests")
for result in history:
    print(f"{result.run_id}: {result.state.value} in {result.duration_str}")
```

---

**Contributions welcome!**  
See [CONTRIBUTING.md](CONTRIBUTING.md)

**License**: MIT