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
* **Predictable lifecycle**: Orchestrator → Policy → Runtime → Executor flow.
* **Maintainability**: Small, testable components.
* **Extensibility**: Easy to add new triggers, policies, executors, or callbacks.
* **Flat structure**: All implementation lives directly under `cmdorc/`.
* **Powerful yet simple event system**: Generic callbacks on any trigger (auto or custom).
* **Pure data where possible**: `RunResult` and `CommandRuntime` are data containers only — no side effects.

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
* `get_status(name: str) -> CommandStatus`

**Callback registration:**

* `on_event(event_name: str, callback: Callable[[RunHandle | None, Any | None], Any]) -> None`
* `off_event(event_name: str, callback: Callable[[RunHandle | None, Any | None], Any]) -> None`
* `set_lifecycle_callback(...) -> None`
* `set_error_callback(...) -> None`

**Wait helpers:**
* `wait_for_running(...) -> bool`
* `wait_for_completion(...) -> RunHandle`
* `wait_for_success(...) -> RunHandle`

---

## 3. Core Components

| Class                | Responsibility |
|----------------------|----------------|
| `CommandOrchestrator`| User-facing coordinator. Never runs subprocesses. |
| `CommandExecutor`    | Pure execution engine. Owns subprocess lifecycle and cancellation. |
| `CommandRuntime`     | Pure state container. Tracks configs, active runs, latest result, and history. |
| `ExecutionPolicy`    | Pure decision logic (`allow`, `cancel_and_restart`, `ignore`). |
| `TriggerEngine`      | Full-featured event bus with wildcard and cycle prevention support. |

---

## 4. Configuration Components

### `CommandConfig` (frozen dataclass)

Immutable definition of a single command.

```python
name: str
command: str
triggers: list[str]
cancel_on_triggers: list[str] = []
max_concurrent: int = 1                 # 0 = unlimited
timeout_secs: int | None = None
on_retrigger: Literal["cancel_and_restart", "ignore"] = "cancel_and_restart"
keep_history: int = 1                    # 0 = no history (but latest_result is always tracked separately)
vars: dict[str, str] = {}
cwd: str | Path | None = None
env: dict[str, str] = {}
```

### `RunnerConfig`

Top-level config object returned by loader.

```python
commands: list[CommandConfig]
vars: dict[str, str]                     # global defaults
```

### `load_config.py`

* Reads TOML (via `tomli`/`tomllib`)
* Resolves nested `{{ var }}` references in `[variables]` section
* Builds and validates `RunnerConfig`

### `resolve_double_brace_vars`

* Handles `{{ var }}` resolution with nesting and cycle protection
* Used only during config loading (not at runtime)

---

## 5. Execution Flow Overview

### Manual Execution (`run_command`)

1. Orchestrator retrieves `CommandConfig`
2. `CommandRuntime` provides current active runs
3. `ExecutionPolicy.decide()` → `NewRunDecision`
4. Orchestrator cancels runs if required
5. Orchestrator creates new `RunResult` (PENDING)
6. `CommandExecutor.start_run()`:
   - Snapshots resolved config (vars, env, cwd, timeout)
   - Resolves template in `command`
   - Launches subprocess
   - Marks `RUNNING`
7. `CommandRuntime` tracks live run
8. On completion → `mark_success` / `mark_failed` / `mark_cancelled`
9. `CommandRuntime` updates `latest_result` + history
10. Auto-triggers may fire (`command_success:name`, etc.)

### Triggered Execution (`trigger()`)

1. User calls `trigger(event_name, context=...)`
2. `TriggerEngine` finds matching commands (exact + wildcards)
3. For each command:
   - Policy decides whether to start/cancel
   - Orchestrator follows same flow as manual execution

---

## 6. Trigger Cycle Prevention

Implemented via `TriggerContext`:

```python
@dataclass
class TriggerContext:
    seen: set[str] = field(default_factory=set)
```

* Created fresh on every top-level `trigger()` call
* Passed down through `TriggerEngine.on_event`
* If an event name is already in `seen`, the engine aborts that branch and logs a warning
* Prevents infinite loops (e.g., `command_success:A` → trigger B → trigger A)

---

## 7. Callback & Event System

Fully generic — works with auto-events, config-defined triggers, and manual `trigger()` calls.

**Callback signature:**
```python
async def handler(run_handle: RunHandle | None, context: Any | None) -> None:
    ...
```

* `run_handle` is provided **only** for lifecycle auto-events
* `context` is whatever was passed to `trigger()`
* Sync and async callbacks both supported
* Wildcard support: `"command_success:*"`, `"*:Lint"`, `"file_*"`

---

## 8. Expected Methods by Class (Complete + Return Types)

### `CommandOrchestrator`

**Public** (see section 2)

**Internal**
* `_prepare_run(...) -> RunResult`
* `_apply_policy(...) -> NewRunDecision`
* `_cancel_runs(runs: list[RunResult]) -> None`
* `_start_run(result: RunResult) -> None`
* `_handle_run_completion(result: RunResult) -> None`
* `_fire_auto_triggers(event_name: str, result: RunResult) -> None`
* `_dispatch_callbacks(...) -> None`

### `CommandExecutor`

* `start_run(result: RunResult, config: CommandConfig, run_vars: dict[str, str] | None = None) -> None`
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
* `get_latest_result(name: str) -> RunResult | None`   # always available
* `list_commands() -> list[str]`
* `get_status(name: str) -> CommandStatus`

### `ExecutionPolicy`

* `decide(config: CommandConfig, active_runs: list[RunResult]) -> NewRunDecision`
* `should_run_on_trigger(self, config: CommandConfig, trigger_event: str) -> bool`
* `should_cancel_on_trigger(self, config: CommandConfig, trigger_event: str) -> bool`

### `TriggerEngine`

* `build_maps(configs: list[CommandConfig]) -> None`
* `on_event(event_name: str, run_handle: RunHandle | None, context: Any | None, trigger_context: TriggerContext) -> None`
* `register_callback(...)`, `unregister_callback(...)`, `get_matching_callbacks(...)`

### `RunResult` (internal, pure data)

* `mark_running() -> None`
* `mark_success() -> None`
* `mark_failed(error: str | Exception) -> None`
* `mark_cancelled(reason: str | None = None) -> None`
* `to_dict() -> dict[str, Any]`

**No `cancel()` method** — cancellation is owned by `CommandExecutor`.

### `RunHandle` (public façade)

* `command_name`, `event_name`, `state`, `success`, `output`, `error`, `duration_str`
* `cancel() -> None`
* `wait(timeout: float | None = None) -> None`

### Supporting Types

```python
@dataclass
class NewRunDecision:
    allow: bool
    runs_to_cancel: list[RunResult]

@dataclass
class TriggerContext:
    seen: set[str] = field(default_factory=set)

@dataclass(frozen=True)
class CommandStatus:
    state: str
    active_count: int = 0
    last_run: RunResult | None = None
