# cmdorc Architecture Overview (Unified)

This document is the authoritative, up-to-date class / architecture reference for **cmdorc**.
It merges the previous `classes.md`, the design decisions in `new.md`, and the current implementation in `src/cmdorc/`. Use this as the single source of truth when implementing, testing, documenting, or publishing `cmdorc`.

---

## Table of Contents

1. Design Goals
2. Public API Surface
3. Core Components & Responsibilities
4. Configuration Components & Loading
5. Variable Resolution Phases
6. Execution Flow (Manual and Triggered)
7. Trigger Engine, Context, and Cycle Prevention
8. Callback & Error Handling Semantics
9. Executor Architecture (Swappable)
10. Runtime / History / Status Behavior
11. `RunResult` (pure data) rules
12. `RunHandle` (public façade)
13. Pitfalls & Best Practices
13. Expected Methods & Signatures (by class)
---

# 1. Design Goals

* **Separation of concerns** — small classes, single responsibilities.
* **Predictable lifecycle** — Orchestrator → Policy → Runtime → Executor.
* **Pure data where appropriate** — state containers separated from lifecycle logic.
* **Swappable execution backends** — executor as an abstract interface.
* **Config-first, runtime mutable** — keep RunnerConfig immutable; CommandRuntime holds mutable state.
* **Safe trigger system** — wildcards + cycle prevention + clear semantics for auto vs manual triggers.
* **Easy to test** — provide mock executors and pure data objects that are trivial to assert.

---

# 2. Public API Surface

Primary entrypoint: `CommandOrchestrator`.

Typical usage:

```py
orchestrator = CommandOrchestrator(runner_config, executor=LocalSubprocessExecutor())

# start a run (non-blocking); returns a handle immediately
handle = await orchestrator.run_command("build", vars={"target": "prod"})

# trigger an arbitrary event
await orchestrator.trigger("file_saved", context={"path": "main.py"})

# register callbacks
orchestrator.on_event("command_success:build", on_build_done)
orchestrator.set_lifecycle_callback("test", on_success=show_results)

# query status
status = orchestrator.list_commands()
info = orchestrator.get_status("build")
```

Key public methods expected on the orchestrator:

* `async run_command(name: str, vars: dict[str,str] | None = None) -> RunHandle`
* `async trigger(event_name: str, context: Any | None = None) -> None`
* `add_command(config: CommandConfig) -> None`
* `remove_command(name: str) -> None`
* `update_command(config: CommandConfig) -> None`
* `reload_all_commands(configs: list[CommandConfig]) -> None`
* `list_commands() -> list[str]`
* `get_status(name: str) -> CommandStatus`
* `on_event(event_name: str, callback: Callable[[RunHandle | None, Any | None], Any]) -> None`
* `off_event(event_name: str, callback: Callable) -> None`
* `set_lifecycle_callback(name: str, on_success: Callable|None = None, on_failed: Callable|None = None, on_cancelled: Callable|None = None) -> None`
* Helper waiters: `wait_for_running`, `wait_for_completion`, `wait_for_success`

---

# 3. Core Components & Responsibilities

| Class                 | Responsibility                                                                                                              |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `CommandOrchestrator` | Public coordinator. Applies policies, coordinates runtime updates, fires events. **Does not** manage subprocesses directly. |
| `ExecutionPolicy`     | Stateless decision logic (allow, cancel, ignore) based on `CommandConfig` and active runs.                                  |
| `CommandExecutor`     | Abstract executor interface. Starts, monitors, and cancels subprocesses or equivalent. Owns subprocess/task lifecycle.      |
| `CommandRuntime`      | Mutable state store: registered commands, active runs, `latest_result`, bounded history.                                    |
| `TriggerEngine`       | Event matching (exact + wildcard), callback registration, dispatching, and cycle prevention.   
| `ResolvedCommand`     | a concrete resolved-snapshot representation of a command prepared for execution (resolved vars, command string, env, cwd, timeout).                             |
| `RunResult`           | Pure data container for a single run (state, timings, outputs, resolved config snapshot).                                   |
| `RunHandle`           | Public façade that wraps a `RunResult` and exposes `cancel()` and `wait()` to users.                                        |

---

# 4. Configuration Components & Loading

### `CommandConfig` (frozen dataclass)

Immutable command definition. Key fields:

```py
name: str
command: str                # may include {{ template_vars }}
triggers: list[str]
cancel_on_triggers: list[str] = []
max_concurrent: int = 1     # 0 = unlimited
timeout_secs: int | None = None
on_retrigger: Literal["cancel_and_restart","ignore"] = "cancel_and_restart"
keep_history: int = 1       # 0 = no history (latest_result is still tracked)
vars: dict[str,str] = {}
cwd: str | Path | None = None   # resolved relative to config file during load_config
env: dict[str,str] = {}
```

Validation occurs in `CommandConfig.__post_init__` (non-empty name/command, positive timeouts, valid `on_retrigger`, etc).

### `RunnerConfig`

Immutable top-level object returned by `load_config()`:

```py
commands: list[CommandConfig]
vars: dict[str,str]  # global template vars (already resolved during load)
```

### `load_config(path)`

* Reads TOML using `tomli` / `tomllib`.
* Resolves `[variables]` with `resolve_double_brace_vars()` and protects against cycles.
* Resolves relative `cwd` **relative to the config file location** and stores absolute paths in `CommandConfig`.
* Returns a `RunnerConfig` with fully resolved global vars.

---

# 5. Variable Resolution Phases

There are three explicit phases:

**Phase 1 — Config load time (static)**

* Resolve `[variables]` in the TOML file (nested `{{ var }}` resolution).
* Result stored in `RunnerConfig.vars`.
* Example: `test_dir = "{{ base_dir }}/tests"` → resolved during load.

**Phase 2 — Runtime merge & template substitution**

* When starting a run, merge variables in this order (later overrides earlier):

  1. `RunnerConfig.vars` (global)
  2. `CommandConfig.vars` (command-specific)
  3. `run_command(..., vars=...)` runtime overrides
* Use merged map to resolve `{{ }}` placeholders inside `command` string and other templates.
* This resolution is done by the executor (or by orchestrator before handing to executor) before launching the subprocess.

**Phase 3 — Subprocess environment**

* Build `resolved_env` by merging `os.environ`, `CommandConfig.env`, and runtime vars converted to env keys as needed.
* Launch subprocess with `resolved_env` and `resolved_cwd`.

**Cycle protection**: `resolve_double_brace_vars()` has depth-limit and throws `ValueError` if unresolved cycles remain.

---

# 6. Execution Flow

## Manual `run_command(name, vars=None)`

1. Orchestrator looks up `CommandConfig`.
2. `CommandRuntime` provides list of active runs for this command.
3. **Debounce Check** Orchestrator checks debounce window.
3. `ExecutionPolicy.decide(config, active_runs)` → `NewRunDecision`.
4. If `runs_to_cancel` present → orchestrator instructs executor to cancel them (via `CommandExecutor.cancel_run()`).
5. If `allow`:

   * Orchestrator creates a `RunResult` in `PENDING` state and registers it in `CommandRuntime`.
   * Orchestrator hands it to `CommandExecutor.start_run()` (snapshotting resolved config into the `RunResult`).
   * `CommandExecutor` marks it `RUNNING` (via `result.mark_running()`) and owns lifecycle.
6. On completion, executor calls `result.mark_success()` / `mark_failed()` / `mark_cancelled()` and informs orchestrator (or orchestrator monitors executor callbacks).
7. `CommandRuntime` updates `latest_result` and bounded history (per `keep_history`).
8. Orchestrator fires auto-triggers (e.g., `command_success:<name>`) via `TriggerEngine`.

## Triggered `trigger(event_name, context=None)`

1. Create a fresh `TriggerContext` (with `seen = set()`).
2. `TriggerEngine` finds matching commands (exact matches and wildcard matches).
3. For each matching command:

   * If `ExecutionPolicy.should_cancel_on_trigger()` indicates cancellation, orchestrator cancels active runs.
   * If `ExecutionPolicy.should_run_on_trigger()` → apply `decide()` and follow same flow as manual execution.

---

# 7. Trigger Engine & Cycle Prevention

### loop_detection = False

If a command has `loop_detection=False`, then:

* Its generated events do **not** add entries to `TriggerContext.seen`.
* This allows intentional recursive workflows.
* Default remains True for safety.

### Trigger Ordering Guarantee

Defined as:

1. Exact match callbacks
2. Wildcard match callbacks
3. Exact match command triggers
4. Wildcard command triggers

This ordering is deterministic and documented.

### `TriggerContext`

```py
@dataclass
class TriggerContext:
    seen: set[str] = field(default_factory=set)
```

* A fresh `TriggerContext` is created per top-level `trigger()` call.
* When an event is processed, its name is added to `seen`.
* If a propagation attempts to process an event already in `seen`, that branch is aborted and a warning is logged — preventing infinite cycles (e.g., `command_success:A` → triggers B → triggers A).

### Wildcards & Matching

* Support exact matches (e.g., `build`), auto-lifecycle events (`command_success:build`), and wildcard patterns such as:

  * `command_success:*`
  * `*:Lint`
  * `file_*`
* `TriggerEngine` provides:

  * `build_maps(configs: list[CommandConfig])` → internal mappings for fast matching
  * `on_event(event_name, run_handle, context, trigger_context)` → dispatches callbacks and command triggers
  * Registration APIs: `register_callback`, `unregister_callback`, `get_matching_callbacks`

---

# 8. Callback & Error Handling Semantics

### Callback signature

```py
async def handler(run_handle: RunHandle | None, context: Any | None) -> None:
    ...
```

* `run_handle` is present for lifecycle events (e.g., `command_success:name`); `None` for arbitrary events without an associated run.
* `context` is whatever the caller passed to `trigger()`.

### Sync and async callbacks supported

* Framework accepts regular functions and `async def` functions and will await appropriately.

### Error behavior — clear rule set

* **Manual triggers**: If a user calls `await orchestrator.trigger("something")` and a callback raises, the exception propagates to the caller.
* **Auto-triggers** (internal lifecycle events): Callback exceptions are caught by orchestrator/trigger engine, logged, and do not stop the system. Orchestrator will also call a registered error callback if provided.
* **Rationale**: visibility for manual actions (fail fast); resiliency for internal auto-generated flows.

---

# 9. Executor Architecture (Swappable) & `ResolvedCommand`

`CommandExecutor` is an abstract base class (ABC). Implementations include `LocalSubprocessExecutor` (default) and test/mock/external executors.

### Required interface (async)

```py
class CommandExecutor(ABC):
    async def start_run(self, result: RunResult, config: CommandConfig, run_vars: dict[str,str] | None = None) -> None: ...
    async def cancel_run(self, result: RunResult) -> None: ...
    def supports_feature(self, feature: str) -> bool: ...
    async def cleanup(self) -> None: ...
```

### Executor responsibilities

* Launch and monitor subprocesses (or remote jobs).
* Update `RunResult` snapshots: `resolved_vars`, `resolved_env`, `resolved_cwd`, `resolved_timeout_secs`, `resolved_command`.
* Call `result.mark_running()` when process starts monitoring and `mark_success()` / `mark_failed()` / `mark_cancelled()` when done.
* Maintain internal maps of active processes/tasks keyed by `result.run_id`.
* Implement idempotent cancellation (`cancel_run()`).

### Why ABC?

* Testing: `MockExecutor` can simulate runs without actual subprocesses.
* Extensibility: `SSHExecutor`, `DockerExecutor`, `K8sExecutor`, `InstrumentedExecutor`, `DryRunExecutor`.
* Composition: wrap executors to add metrics/logging.

# 9. `ResolvedCommand`

```python
@dataclass(frozen=True)
class ResolvedCommand:
    command: str
    cwd: str | None
    env: dict[str, str]
    timeout_secs: int | None
    vars: dict[str, str]
```

### Purpose

* Single container holding all *resolved* runtime attributes.
* Created by orchestrator before calling executor.
* Executor receives:

  * RunResult (empty result container)
  * ResolvedCommand (execution instructions)

### Why this is better

* Executor no longer needs to merge vars or manipulate RunResult fields.
* RunResult becomes cleaner and more obviously a *result*.
* Executor code becomes simpler, more testable, and easier to mock.
---

# 10. Runtime / History / Status Behavior

### `CommandRuntime` responsibilities

* Register/replace/remove `CommandConfig` definitions.
* Track active runs: `get_active_runs(name) -> list[RunResult]`.
* Track `latest_result` per command — always available even if `keep_history == 0`.
* Track bounded history per `keep_history` using `deque(maxlen=keep_history)`.
* Expose `get_status(name) -> CommandStatus`.

### History policy

* `keep_history: int` controls number of completed RunResult objects kept (0 = no history, but `latest_result` still tracked).
* When a run completes:

  * Update `latest_result[name] = result`.
  * If `keep_history > 0`, append to `history[name]` deque (bounded).
* `get_history(name)` returns up to `keep_history` items.

History ordering is append-in-completion-order.

### `CommandStatus` (frozen)

Provides:

* `state: str` — `"never_run"`, `"running"`, `"success"`, `"failed"`, `"cancelled"`.
* `active_count: int`
* `last_run: RunResult | None` (latest_result)

---

# 11. `RunResult` — Pure Data Container (Rules)

`RunResult` is intentionally a pure, serializable data container. **Key rules:**

* **No subprocess handles or asyncio.Task in RunResult.** Executor owns those.
* **Mutations permitted**: start/end times, output, state, resolved snapshots — but this is still a data object.
* **`future` semantics**: `future` is an `asyncio.Future[RunResult]` used as a *completion signal*. It **must always** be completed with `future.set_result(self)` (never `set_exception`). Callers check `result.state`/`result.success` for outcome.
* **State transitions** via methods:

  * `mark_running()` — sets `RUNNING`, records `start_time`.
  * `mark_success()` — sets `SUCCESS`, `success=True`, calls `_finalize()`.
  * `mark_failed(error)` — sets `FAILED`, `success=False`, stores `error`, calls `_finalize()`.
  * `mark_cancelled(reason=None)` — sets `CANCELLED`, `success=None`, stores reason, calls `_finalize()`.
* `_finalize()` records `end_time`, computes duration, and sets the future result (if not done).
* `to_dict()` produces a JSON-serializable dict (do not include full env; list keys instead).
* `duration_str`, `duration_secs`, `is_finished` are helper properties.

**Rationale**: Keep `RunResult` easy to test, easy to serialize, and clearly separated from lifecycle concerns.

---

# 12. `RunHandle` (public façade)

`RunHandle` is the user-facing wrapper around `RunResult`. It should:

* Expose read-only properties: `command_name`, `run_id`, `state`, `success`, `output`, `error`, `duration_str`.
* Provide control helpers:

  * `cancel() -> None` — delegates to the orchestrator/executor (returns immediately).
  * `async wait(timeout: float | None = None) -> RunResult` — awaits `run_result.future`.
* Optionally expose internal future for advanced users (documented as internal).
* `RunHandle.cancel()` should be safe/ idempotent — orchestrator will route to executor.

---
# 13. Pitfalls & Best Practices (New Section)

This new section summarizes architectural risks and guidance:

### 1. Avoiding “God Object” Orchestrator

Encourage internal helpers (RunController, CallbackDispatcher).

### 2. Future-friendly ExecutionPolicy

Document new policy hooks (debounce, future queueing/throttling).

### 3. Trigger Graph Complexity

Explicit ordering + loop_detection option provide safe defaults.

### 4. Cancellation Safety

Orchestrator must wrap executor.cancel_run(result) in try/except.

### 5. History Ordering

Explicitly documented as completion-time order.

### 6. Trigger Validation

Whitespace trimming + pattern checks prevent confusing configs.

### 7. Executor Resolution Separation

ResolvedCommand enforces clean separation and clearer invariants.

# 13. Expected Methods & Signatures (by class)

### `CommandOrchestrator` (public)

* `async run_command(name: str, vars: dict[str,str] | None = None) -> RunHandle`
* `async trigger(event_name: str, context: Any | None = None) -> None`
* `add_command(config: CommandConfig) -> None`
* `remove_command(name: str) -> None`
* `update_command(config: CommandConfig) -> None`
* `reload_all_commands(configs: list[CommandConfig]) -> None`
* `list_commands() -> list[str]`
* `get_status(name: str) -> CommandStatus`
* `on_event(event_name: str, callback: Callable) -> None`
* `off_event(event_name: str, callback: Callable) -> None`
* `set_lifecycle_callback(name: str, ...) -> None`
* Internal helpers:

  * `_prepare_run(...) -> RunResult`
  * `_apply_policy(...) -> NewRunDecision`
  * `_cancel_runs(runs: list[RunResult]) -> None`
  * `_start_run(result: RunResult) -> None`
  * `_handle_run_completion(result: RunResult) -> None`
  * `_fire_auto_triggers(event_name: str, result: RunResult) -> None`
  * `_dispatch_callbacks(...) -> None`

### `CommandExecutor` (abstract)

* `async start_run(result: RunResult, config: CommandConfig, run_vars: dict[str,str] | None = None) -> None`
* `async cancel_run(result: RunResult) -> None`
* `def supports_feature(self, feature: str) -> bool`
* `async cleanup(self) -> None`

### `CommandRuntime`

* `register_command(config: CommandConfig) -> None`
* `remove_command(name: str) -> None`
* `replace_command(config: CommandConfig) -> None`
* `get_config(name: str) -> CommandConfig | None`
* `get_active_runs(name: str) -> list[RunResult]`
* `add_live_run(result: RunResult) -> None`
* `mark_run_complete(result: RunResult) -> None`
* `get_history(name: str) -> list[RunResult]`
* `get_latest_result(name: str) -> RunResult | None`
* `list_commands() -> list[str]`
* `get_status(name: str) -> CommandStatus`

### `ExecutionPolicy`

* `decide(config: CommandConfig, active_runs: list[RunResult]) -> NewRunDecision`
* `should_run_on_trigger(config: CommandConfig, trigger_event: str) -> bool`
* `should_cancel_on_trigger(config: CommandConfig, trigger_event: str) -> bool`

### `TriggerEngine`

* `build_maps(configs: list[CommandConfig]) -> None`
* `on_event(event_name: str, run_handle: RunHandle | None, context: Any | None, trigger_context: TriggerContext) -> None`
* `register_callback(event_pattern: str, callback: Callable) -> None`
* `unregister_callback(event_pattern: str, callback: Callable) -> None`
* `get_matching_callbacks(event_name: str) -> list[Callable]`

### `RunResult`

* `mark_running() -> None`
* `mark_success() -> None`
* `mark_failed(error: str|Exception) -> None`
* `mark_cancelled(reason: str|None = None) -> None`
* `to_dict() -> dict[str,Any]`

---

# 14. Notes on Testing, Serialization, and Extensibility

* **Testing**:

  * Use `MockExecutor` to simulate success/failure without subprocess overhead.
  * `RunResult` is easy to construct and assert on; no mocking of OS/syscalls required.
* **Serialization**:

  * `RunResult.to_dict()` should be the canonical serializer for UI and persistence; it intentionally avoids dumping full env contents.
* **Extensibility**:

  * Add executors for remote/backed execution without changing orchestrator policy.
  * Add optional features (debounce, queue) as opt-in config fields in `CommandConfig` if needed; current design intentionally keeps re-trigger behavior explicit and simple (`on_retrigger` + `max_concurrent`).
* **Versioning**:

  * Keep public API stable for packaging on PyPI; introduce new features as additive optional fields or through new classes.

---

## Appendix — Quick Rationale Summary

* `RunResult` pure-data → predictable testing + serialization.
* `CommandExecutor` ABC → testability & swappability.
* Separate `RunnerConfig` and `CommandRuntime` → keep immutable config distinct from mutable runtime state; allows hot reload without losing active runs.
* `future.set_result(self)` on completion → future signals completion only; callers inspect state for success/failure.
* Trigger context + wildcard support → flexible event wiring while preventing cycles.
