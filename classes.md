# cmdorc Architecture Overview

This document describes the finalized class architecture for **cmdorc**, including
responsibilities, method expectations, boundaries, and lifecycle rules.

---

## Table of Contents

1. Design Goals
2. Public API Surface
3. Core Components
4. Configuration Components
5. Execution Flow Overview
6. Trigger Cycle Prevention
7. Callback & Event System
8. Expected Methods by Class (Complete + Return Types)

---

## 1. Design Goals

* **Separation of concerns**: Each class has one clear responsibility.
* **Predictable lifecycle**: Orchestrator → policy → runtime → executor flow.
* **Maintainability**: Small, testable components.
* **Extensibility**: Easy to add new triggers, policies, executors, or callbacks.
* **Flat structure**: All implementation lives directly under `cmdorc/`.
* **Powerful yet simple event system**: Generic callbacks on any trigger (auto or custom).

---

## 2. Public API Surface

### `CommandOrchestrator` — The user-facing entry point

```python
orchestrator = CommandOrchestrator(config)

handle = await orchestrator.run_command("build", vars={"target": "prod"})
await orchestrator.trigger("file_saved", context={"path": "main.py"})

orchestrator.on_event("command_success:build", on_build_done)
orchestrator.set_lifecycle_callback("test", on_success=show_results)
```

**Public methods:**

* `run_command(name: str, vars: dict[str, str] | None = None) -> RunHandle`
* `trigger(event_name: str, context: Any | None = None) -> None`
* `add_command(config: CommandConfig) -> None`
* `remove_command(name: str) -> None`
* `update_command(config: CommandConfig) -> None`
* `reload_all_commands(configs: list[CommandConfig]) -> None`
* `list_commands() -> list[str]`
* `get_status(name: str) -> CommandStatus`  # NEW: convenience query

**Callback registration:**

* `on_event(event_name: str, callback: Callable[[RunHandle | None, Any | None], Any]) -> None`
* `off_event(event_name: str, callback: Callable[[RunHandle | None, Any | None], Any]) -> None`
* `set_lifecycle_callback(
    command_name: str | None = None,
    on_started: Callable[[RunHandle], Any] | None = None,
    on_success: Callable[[RunHandle], Any] | None = None,
    on_failed: Callable[[RunHandle], Any] | None = None,
    on_cancelled: Callable[[RunHandle], Any] | None = None,
    on_finished: Callable[[RunHandle], Any] | None = None,
) -> None`
* `set_error_callback(callback: Callable[[RunHandle], Any]) -> None`  # convenience for failed + cancelled

**Wait helpers (optional but recommended):**
* `wait_for_running(name: str, timeout: float = 5.0) -> bool`
* `wait_for_completion(name: str, timeout: float = 30.0) -> RunHandle`
* `wait_for_success(name: str, timeout: float = 30.0) -> RunHandle`

---

## 3. Core Components

### `CommandOrchestrator`

Coordinates all components. Never runs subprocesses.

### `CommandExecutor`

Pure execution engine.

### `CommandRuntime`

Pure runtime state container.
- Stores current `CommandConfig`s
- Tracks live runs and history
- Provides queries for policy and orchestrator

### `ExecutionPolicy`

Pure decision logic.

### `TriggerEngine`

Full-featured event bus with wildcard support.

---

## 4–6. Configuration, Flow, Cycle Prevention

(Unchanged — already perfect.)

---

## 7. Callback & Event System

**Fully generic** — works with auto-events, config-defined triggers, and arbitrary `trigger()` calls.

**Callback signature:**
```python
async def handler(run_handle: RunHandle | None, context: Any | None) -> None:
    ...
```
* `run_handle`: Provided **only** for auto-lifecycle events (`command_started:name`, etc.)
* `context`: Whatever was passed to `trigger()`
* Callbacks may be sync or async — both are supported

**Wildcard support:**
* `"command_success:*"` → all successful commands
* `"*:Lint"` → all lifecycle events for the "Lint" command
* `"file_*"` → any event starting with `file_`

---

## 8. Expected Methods by Class (Complete + Return Types)

### `CommandOrchestrator`

**Public:**
* `run_command(...) -> RunHandle`
* `trigger(...) -> None`
* `add_command(config: CommandConfig) -> None`
* `remove_command(name: str) -> None`
* `update_command(config: CommandConfig) -> None`
* `reload_all_commands(configs: list[CommandConfig]) -> None`
* `list_commands() -> list[str]`
* `get_status(name: str) -> CommandStatus`
* `on_event(...) -> None`
* `off_event(...) -> None`
* `set_lifecycle_callback(...) -> None`
* `set_error_callback(...) -> None`

**Internal:**
* `_prepare_run(...) -> RunResult`
* `_apply_policy(...) -> NewRunDecision`
* `_cancel_runs(runs: list[RunResult]) -> None`
* `_start_run(...) -> None`
* `_handle_run_completion(result: RunResult) -> None`
* `_fire_auto_triggers(event_name: str, result: RunResult) -> None`
* `_dispatch_callbacks(event_name: str, run_handle: RunHandle | None, context: Any | None) -> None`

### `CommandExecutor`

* `start_run(result: RunResult, config: CommandConfig) -> None`
* `cancel_run(result: RunResult) -> None`

### `CommandRuntime`

* `register_command(config: CommandConfig) -> None`
* `remove_command(name: str) -> None`
* `replace_command(config: CommandConfig) -> None`
* `get_config(name: str) -> CommandConfig | None`
* `get_active_runs(name: str) -> list[RunResult]`
* `add_live_run(result: RunResult) -> None`
* `mark_run_complete(result: RunResult) -> None`
* `get_history(name: str) -> list[RunResult]`
* `list_commands() -> list[str]`
* `get_status(name: str) -> CommandStatus`  # derives from live/history

### `ExecutionPolicy`

* `decide(config: CommandConfig, active_runs: list[RunResult]) -> NewRunDecision`

### `TriggerEngine`

* `build_maps(configs: list[CommandConfig]) -> None`
* `on_event(
    event_name: str,
    run_handle: RunHandle | None,
    context: Any | None,
    trigger_context: TriggerContext
) -> None`
* `register_callback(event_name: str, callback: Callable[[RunHandle | None, Any | None], Any]) -> None`
* `unregister_callback(event_name: str, callback: Callable[[RunHandle | None, Any | None], Any]) -> None`
* `get_matching_callbacks(event_name: str) -> list[Callable]`  # internal, supports wildcards

### `RunResult` (internal)

* `mark_running() -> None`
* `mark_success() -> None`
* `mark_failed(error: str) -> None`
* `mark_cancelled() -> None`
* `cancel() -> None`

### `RunHandle` (public façade)

* `command_name: str`
* `event_name: str | None`                  # NEW: the triggering auto-event (e.g. "command_success:build")
* `state: RunState`
* `success: bool | None`
* `output: str`
* `error: str | None`
* `duration_str: str`
* `cancel() -> None`
* `wait(timeout: float | None = None) -> None`   # raises TimeoutError if not done

### Supporting Types

```python
@dataclass
class NewRunDecision:
    allow: bool
    runs_to_cancel: list[RunResult]

@dataclass
class TriggerContext:
    seen: set[str] = field(default_factory=set)