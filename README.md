# cmdorc: Command Orchestrator — Async, Trigger-Driven Shell Command Runner

[![PyPI version](https://badge.fury.io/py/cmdorc.svg)](https://badge.fury.io/py/cmdorc)  
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)

**cmdorc** is a lightweight, **async-first** Python library for running shell commands in response to string-based **triggers**. Built for developer tools, TUIs (like [VibeDir](https://github.com/yourusername/vibedir)), CI automation, or any app needing event-driven command orchestration.

Zero external dependencies (pure stdlib + `tomli` for Python <3.11). Predictable. Extensible. No magic.

Inspired by Make/npm scripts — but instead of file changes, you trigger workflows with **events** like `"lint"`, `"tests_passed"`, or `"deploy_ready"`.

## Features

- **Trigger-Based Execution** — Fire any string event → run configured commands
- **Auto-Events** — `command_started:Lint`, `command_success:Lint`, `command_failed:Tests`, etc.
- **Full Async + Concurrency Control** — Non-blocking, cancellable, timeout-aware
- **Smart Retrigger Policies** — `cancel_and_restart` or `ignore`
- **Cancellation Triggers** — Auto-cancel commands on certain events
- **Rich State Tracking** — Live runs, history, durations, output capture
- **Template Variables** — `{{ base_directory }}`, nested resolution, runtime overrides
- **TOML Config + Validation** — Clear, declarative setup with validation
- **Cycle Detection** — Prevents infinite trigger loops with clear warnings
- **Frontend-Friendly** — Perfect for TUIs (Textual, Bubble Tea), status icons (Pending/Running/Success/Failure/Cancelled), logs
- **Minimal dependencies**: Only `tomli` for Python <3.11 (stdlib `tomllib` for 3.11+)
- **Deterministic, Safe Template Resolution** with nested `{{var}}` support and cycle protection

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
timeout_secs = 300
keep_history = 3

[[command]]
name = "Tests"
triggers = ["command_success:Lint", "Tests"]
command = "pytest {{ tests_directory }} -q"
timeout_secs = 180
keep_history = 5
```

### 2. Run in Python

```python
import asyncio
from cmdorc import CommandRunner, load_config

async def main():
    config = load_config("cmdorc.toml")
    runner = CommandRunner(config)

    # Trigger a workflow
    await runner.trigger("changes_applied")  # → Lint → (if success) Tests

    # Preferred way — just works, no config gymnastics
    result = await runner.run_command("Tests")
    print(f"Tests: {result.state.value} ({result.duration_str})")

    # Fire-and-forget (e.g. from a UI button)
    runner.run_command_async("Lint")

    # Pass temporary variables for this run only
    await runner.run_command("Deploy", env="production", region="us-east-1")

    # Wait for completion
    await runner.wait_for_not_running("Tests", timeout=30)

    # Get result
    result = runner.get_result("Tests")
    print(f"Tests: {result.state.value} in {result.duration_str}")
    if result.output:
        print(result.output)

    # Cancel running command
    runner.cancel_command("Lint")

    # Or cancel everything
    runner.cancel_all()

asyncio.run(main())
```

## Core Concepts

### Triggers & Auto-Events

- Any string can be a trigger: `"build"`, `"deploy"`, `"hotkey:f5"`
- Special auto-triggers (emitted automatically):
  - `command_started:MyCommand` — Command begins execution
  - `command_success:MyCommand` — Command exits with code 0
  - `command_failed:MyCommand` — Command exits non-zero
  - `command_finished:MyCommand` — Command completes (success or failure, not cancelled)
  - `command_cancelled:MyCommand` — Command was cancelled

### Lifecycle Example

```python
await runner.trigger("build")

# If "build" triggers a command named "Compile":
# 1. command_started:Compile    ← can trigger other commands
# 2. ... subprocess runs ...
# 3. command_success:Compile    ← triggers on success
#    command_finished:Compile   ← always fires after success/failure
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
```

## API Highlights

```python
runner.trigger("build")                    # Fire event
runner.cancel_command("Tests")             # Cancel specific
runner.get_status("Lint")                  # → CommandStatus.IDLE, etc.
runner.get_result("Lint")                  # → RunResult (latest)
runner.get_history("Lint")                 # → List[RunResult]
runner.wait_for_not_running("Tests", timeout=10)  # Async wait
runner.set_vars({"env": "prod"})           # Runtime template vars
```

### RunResult

```python
result.state          # Enum: RUNNING, SUCCESS, FAILED, CANCELLED
result.success        # bool or None
result.output         # str (stdout + stderr)
result.duration_str   # "1m 23s", "452ms", "1h 5m"
result.trigger_event  # What triggered this run
result.run_id         # Unique identifier for this execution
```

## Configuration

### Load from TOML

```python
runner = CommandRunner(load_config("cmdorc.toml"))
```

### Or Pass Programmatically

```python
from cmdorc import CommandConfig, CommandRunner

commands = [
    CommandConfig(
        name="Format",
        command="black .",
        triggers=["Format", "changes_applied"]
    )
]

runner = CommandRunner(commands, base_directory="/my/project")
runner.add_var("env", "dev")
```

## Introspection (Great for UIs)

```python
runner.get_commands_by_trigger("changes_applied")  # → [CommandConfig, ...]
runner.has_any_handler("deploy")                   # → True if anything reacts
runner.validate_templates()                        # Find unresolved {{ vars }}
```

## Roadmap

| Version | Features |
|-------|---------|
| **v0.1** (current) | Core async runner, triggers, cancellation, TOML, history, cycle detection, `command_started` |
| **v0.2** | Persistent results (`result_file`), structured logging, configurable max_nested_depth |

## Why cmdorc?

You're building a TUI, VSCode extension, or LLM agent that says:  
> "When the user saves → run formatter → then tests → show results live"

`cmdorc` is the **battle-tested backend** that handles:
- Async execution
- Cancellation on navigation
- State for your UI
- Safety (no cycles, no deadlocks)

**Separate concerns**: Let your UI be beautiful. Let `cmdorc` handle the boring parts: async, cancellation, state, safety.

## Advanced Features

### Lifecycle Hooks with Callbacks

```python
runner.on_trigger("command_started:Tests", lambda _: ui.show_spinner())
runner.on_trigger("command_finished:Tests", lambda _: ui.hide_spinner())
```

### Template Variables

```python
runner.set_vars({"env": "production", "region": "us-west-2"})
# Now commands can use {{ env }} and {{ region }}
```

### History Retention

```toml
keep_history = 10  # Keep last 10 runs for debugging
```

```python
history = runner.get_history("Tests")
for run in history:
    print(f"{run.run_id}: {run.state} in {run.duration_str}")
```

---

**Contributions welcome!**  
See [CONTRIBUTING.md](CONTRIBUTING.md)

**License**: MIT