# cmdorc Architecture Reference

**Version:** 2.0 (Refactored)  
**Status:** Authoritative design document for implementation

This is the single source of truth for cmdorc's architecture, class responsibilities, and API contracts.

---

## Table of Contents

1. [Design Principles](#design-principles)
2. [Public API](#public-api)
3. [Core Components](#core-components)
4. [Configuration System](#configuration-system)
5. [Variable Resolution](#variable-resolution)
6. [Execution Flow](#execution-flow)
7. [Trigger System](#trigger-system)
8. [State Management](#state-management)
9. [Executor Interface](#executor-interface)
10. [Data Containers](#data-containers)
11. [Error Handling](#error-handling)
12. [Testing Strategy](#testing-strategy)
13. [Implementation Checklist](#implementation-checklist)

---

## 1. Design Principles

### Core Values
- **Separation of concerns** - Each class has a single, clear responsibility
- **Testability first** - Pure functions and mockable interfaces
- **Predictable state** - Explicit state transitions, no hidden mutations
- **Swappable backends** - Executor as abstract interface
- **Config immutability** - `CommandConfig` is frozen; runtime state lives in `CommandRuntime`

### Anti-patterns to Avoid
- ❌ God objects (orchestrator doing too much)
- ❌ Mixing subprocess management with orchestration logic
- ❌ Circular dependencies between components
- ❌ Implicit state changes
- ❌ Leaking implementation details through public API

---

## 2. Public API

### CommandOrchestrator

The single public entrypoint:

### CommandStatus

```python
orchestrator = CommandOrchestrator(
    runner_config: RunnerConfig,
    executor: CommandExecutor | None = None  # defaults to LocalSubprocessExecutor
)

# Execution
handle = await orchestrator.run_command(
    name: str,
    vars: dict[str, str] | None = None
) -> RunHandle

# Triggering
await orchestrator.trigger(
    event_name: str,
    context: Any | None = None
) -> None

# Configuration
orchestrator.add_command(config: CommandConfig) -> None
orchestrator.remove_command(name: str) -> None
orchestrator.update_command(config: CommandConfig) -> None
orchestrator.reload_all_commands(configs: list[CommandConfig]) -> None

# Query
orchestrator.list_commands() -> list[str]
orchestrator.get_status(name: str) -> CommandStatus
orchestrator.get_history(name: str, limit: int = 10) -> list[RunResult]

# Callbacks
orchestrator.on_event(
    event_pattern: str,
    callback: Callable[[RunHandle | None, Any], Awaitable[None] | None]
) -> None

orchestrator.off_event(event_pattern: str, callback: Callable) -> None

orchestrator.set_lifecycle_callback(
    name: str,
    on_success: Callable | None = None,
    on_failed: Callable | None = None,
    on_cancelled: Callable | None = None
) -> None

# Cleanup
await orchestrator.cleanup() -> None
```

### RunHandle (User Facade)

```python
handle.command_name: str
handle.run_id: str
handle.state: RunState
handle.success: bool | None
handle.output: str
handle.error: str | Exception | None
handle.duration_str: str

await handle.wait(timeout: float | None = None) -> RunResult
await handle.cancel() -> None

# Internal (advanced usage)
handle._result: RunResult  # Direct access to underlying result
```

---

## 3. Core Components

### Component Hierarchy

```
CommandOrchestrator (public coordinator)
├── CommandRuntime (state store)
├── ConcurrencyPolicy (decision logic)
├── TriggerEngine (event routing)
└── CommandExecutor (subprocess management)
```

### Responsibilities

| Component | Owns | Does NOT Own |
|-----------|------|--------------|
| **CommandOrchestrator** | Public API, coordination, policy application | Subprocess handles, pattern matching |
| **CommandRuntime** | Registered configs, active runs, history, latest results, debounce timestamps | Execution decisions, subprocess lifecycle |
| **ConcurrencyPolicy** | Concurrency decisions (max_concurrent, on_retrigger) | Pattern matching, state, any I/O |
| **TriggerEngine** | ALL trigger pattern matching (exact + wildcards), callback dispatch, cycle prevention | Command execution, state mutations, concurrency decisions |
| **CommandExecutor** | Subprocess/task lifecycle, output capture | Orchestration policy, trigger logic |

**Note:** TriggerEngine is the single source of truth for all trigger matching. ConcurrencyPolicy focuses purely on concurrency rules.

---

## 4. Configuration System

### CommandConfig (frozen dataclass)

```python
@dataclass(frozen=True)
class CommandConfig:
    # Required
    name: str
    command: str  # May contain {{ template_vars }}
    triggers: list[str]
    
    # Concurrency control
    max_concurrent: int = 1  # 0 = unlimited
    on_retrigger: Literal["cancel_and_restart", "ignore"] = "cancel_and_restart"
    
    # Execution settings
    timeout_secs: int | None = None
    cwd: str | Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    vars: dict[str, str] = field(default_factory=dict)
    
    # Behavioral controls
    cancel_on_triggers: list[str] = field(default_factory=list)
    debounce_in_ms: int = 0
    loop_detection: bool = True
    
    # History
    keep_history: int = 1  # 0 = no history (but latest_result still tracked)
```

**Validation** (in `__post_init__`):
- Non-empty name and command
- `max_concurrent >= 0`
- `timeout_secs > 0` if set
- `on_retrigger` in allowed values
- Valid `cwd` path

### RunnerConfig

```python
@dataclass(frozen=True)
class RunnerConfig:
    commands: list[CommandConfig]
    vars: dict[str, str] = field(default_factory=dict)  # Global template vars
```

### load_config(path)

**Responsibilities:**
1. Parse TOML using `tomllib` / `tomli`
2. Resolve `[variables]` section with cycle detection
3. Resolve relative `cwd` paths **relative to config file location**
4. Validate all configs via `CommandConfig.__post_init__`
5. Return immutable `RunnerConfig`

**Does NOT:**
- Resolve runtime variables
- Start any executions
- Modify global state

---

## 5. Variable Resolution

### Three Distinct Phases

#### Phase 1: Config Load (Static)
**When:** During `load_config()`  
**What:** Resolve `[variables]` section  
**Example:**
```toml
[variables]
base_dir = "/home/user/project"
test_dir = "{{ base_dir }}/tests"  # Resolved to "/home/user/project/tests"
```

**Implementation:** `resolve_double_brace_vars()` with cycle detection

#### Phase 2: Runtime Merge (Per Execution)
**When:** In `CommandOrchestrator._prepare_run()`  
**What:** Merge variables in priority order:
1. `RunnerConfig.vars` (global)
2. `CommandConfig.vars` (command-specific)
3. `run_command(..., vars={...})` (call-time overrides)

**Result:** `merged_vars: dict[str, str]`

#### Phase 3: Template Substitution (Pre-Execution)
**When:** In `CommandOrchestrator._prepare_run()` (before executor)  
**What:** Create `ResolvedCommand` by substituting `{{ var }}` in:
- `command` string
- `env` values
- Any other templated fields

**Result:** `ResolvedCommand` (fully concrete, no templates)

### Critical Rule
**Orchestrator resolves variables, Executor receives resolved data.**

---

## 6. Execution Flow

### Manual Execution: `run_command(name, vars=None)`

```
1. Orchestrator.run_command()
   ↓
2. _prepare_run() → merge vars, create ResolvedCommand
   ↓
3. Check debounce window (if configured)
   ↓
4. ConcurrencyPolicy.decide() → NewRunDecision
   ↓
5. If runs_to_cancel → executor.cancel_run() for each
   ↓
6. If allow → create RunResult, register in CommandRuntime
   ↓
7. executor.start_run(result, resolved_command)
   ↓
8. Executor marks result.state = RUNNING, manages subprocess
   ↓
9. On completion → executor calls result.mark_success/failed/cancelled
   ↓
10. Orchestrator updates runtime (latest_result, history)
    ↓
11. Fire auto-triggers (command_success:name, etc.)
    ↓
12. Return RunHandle to caller
```

### Triggered Execution: `trigger(event_name, context)`

```
1. Orchestrator.trigger(event_name, context)
   ↓
2. Create fresh TriggerContext(seen=set())
   ↓
3. TriggerEngine.get_matching_commands(event_name, trigger_type="cancel_on_triggers")
   ↓
4. For each match → orchestrator.cancel_active_runs(config.name)
   ↓
5. TriggerEngine.get_matching_commands(event_name, trigger_type="triggers")
   ↓
6. For each match:
   - Check should_run_on_trigger → apply policy + execute if allowed
   ↓
7. TriggerEngine.on_event() → dispatch callbacks
   ↓
8. Add event_name to trigger_context.seen (if loop_detection=True)
   ↓
9. Any triggered commands may fire their own auto-triggers
   (cycle prevention via trigger_context.seen)
```

---

## 7. Trigger System

### TriggerEngine

**Responsibilities:**
- Match event names against registered patterns (exact + wildcards)
- Maintain callback registry
- Dispatch callbacks and command triggers in defined order
- Prevent infinite loops via `TriggerContext.seen`

**Does NOT:**
- Make execution decisions
- Manage command state
- Handle debouncing

### Trigger Patterns

**Supported:**
- Exact: `"build"`, `"file_saved"`
- Wildcards: `"command_success:*"`, `"*:Lint"`, `"file_*"`
- Auto-generated lifecycle events: `"command_success:name"`, `"command_failed:name"`, `"command_cancelled:name"`

**Matching Algorithm:**
```python
def matches(pattern: str, event_name: str) -> bool:
    if pattern == event_name:
        return True  # Exact match
    
    # Convert wildcard pattern to regex
    regex = re.escape(pattern).replace(r'\*', '.*')
    return re.fullmatch(regex, event_name) is not None
```

### TriggerContext & Cycle Prevention

### TriggerContext & Cycle Prevention

```python
@dataclass
class TriggerContext:
    seen: set[str] = field(default_factory=set)
```

**Design choice:** Uses `set` for O(1) membership checking rather than `list` (O(n) checking).
**Rationale:** Sets are significantly faster when checking if an item is contained within them, which is the primary operation for cycle detection.
**Debugging:** If ordered history is needed for debugging, add separate `history: list[str]` field or rely on logging.

**Rules:**
1. Fresh context created for each top-level `trigger()` call
2. Before processing event, check if `event_name in context.seen`
3. If already seen → log warning, abort this branch
4. After processing → add to `context.seen` (unless `loop_detection=False`)

**Escape Hatch:**
If `CommandConfig.loop_detection = False`, that command's auto-triggers do NOT add to `seen`. Use with extreme caution.

### Dispatch Order Guarantee

For a given event, callbacks/triggers execute in this order:
1. Exact match callbacks
2. Wildcard match callbacks  
3. Exact match command triggers
4. Wildcard command triggers

Within each group, order is registration order.

---

## 8. State Management

### CommandRuntime

**Primary State Store** - All mutable runtime state lives here.

```python
class CommandRuntime:
    # Configuration registry
    _configs: dict[str, CommandConfig]
    
    # Active runs (currently executing)
    _active_runs: dict[str, list[RunResult]]
    
    # Latest result per command (always present after first run)
    _latest_result: dict[str, RunResult]
    
    # Bounded history (per keep_history setting)
    _history: dict[str, deque[RunResult]]
    
    # Debounce tracking (tracks START times, not completion)
    _last_start: dict[str, datetime]
```

**Key Methods:**
```python
def register_command(config: CommandConfig) -> None
def remove_command(name: str) -> None
def get_config(name: str) -> CommandConfig | None

def add_live_run(result: RunResult) -> None
def mark_run_complete(result: RunResult) -> None
def get_active_runs(name: str) -> list[RunResult]

def get_latest_result(name: str) -> RunResult | None
def get_history(name: str, limit: int = 10) -> list[RunResult]

def get_status(name: str) -> CommandStatus
def list_commands() -> list[str]

def check_debounce(name: str, debounce_ms: int) -> bool
def record_completion(name: str) -> None
```

### Debounce Handling

**Decision:** Debounce is checked in `CommandOrchestrator` **before** calling `ConcurrencyPolicy.decide()`.

**Rationale:**
- `ConcurrencyPolicy` is stateless - it cannot track timestamps
- Debounce is a timing constraint, not a concurrency policy
- `CommandRuntime` tracks completion timestamps via explicit `_last_completion` dict
- Orchestrator queries runtime before applying policy

**Alternative considered:** Using `latest_result.end_time` instead of separate timestamp tracking.
**Trade-off:** Current approach is more explicit and flexible (e.g., could debounce differently for success vs failure states in future). If simplicity is preferred, can switch to `latest_result.end_time`.

**Flow:**
```python
async def run_command(self, name: str, vars: dict | None = None) -> RunHandle:
    config = self._runtime.get_config(name)
    
    # Check debounce FIRST (before policy)
    if config.debounce_in_ms > 0:
        if not self._runtime.check_debounce(name, config.debounce_in_ms):
            logger.debug(f"Command '{name}' is in debounce window, ignoring")
            # Return handle to most recent run? Or raise? TBD
            raise DebounceError(f"Command '{name}' is debounced")
    
    # Then apply policy
    active_runs = self._runtime.get_active_runs(name)
    decision = self._policy.decide(config, active_runs)
    # ... rest of execution flow
```

**CommandRuntime responsibilities:**
```python
def check_debounce(self, name: str, debounce_ms: int) -> bool:
    """Return True if enough time has passed since last completion."""
    last = self._last_completion.get(name)
    if last is None:
        return True  # Never run before
    
    elapsed_ms = (datetime.now() - last).total_seconds() * 1000
    return elapsed_ms >= debounce_ms

def record_completion(self, name: str) -> None:
    """Record completion timestamp for debounce tracking."""
    self._last_completion[name] = datetime.now()
```

```python
@dataclass(frozen=True)
class CommandStatus:
    state: str  # "never_run" | "running" | "success" | "failed" | "cancelled"
    active_count: int
    last_run: RunResult | None
```

**State Rules:**
- `"never_run"` if no runs ever started
- `"running"` if `active_count > 0`
- Otherwise: state of `last_run` (most recent completed)

### History Behavior

**Rules:**
1. `latest_result` is ALWAYS updated on completion (even if `keep_history=0`)
2. History deque has `maxlen=keep_history`
3. Append happens in completion order (not start order)
4. History is bounded per command independently

---

## 9. Executor Interface

### CommandExecutor (ABC)

```python
class CommandExecutor(ABC):
    @abstractmethod
    async def start_run(
        self,
        result: RunResult,
        resolved: ResolvedCommand
    ) -> None:
        """
        Start execution and take ownership of the RunResult.
        
        Responsibilities:
        - Mark result.state = RUNNING
        - Launch subprocess/task
        - Capture output
        - Call result.mark_success/failed/cancelled on completion
        - Handle timeouts
        
        Does NOT return anything (updates result in place).
        """
        ...
    
    @abstractmethod
    async def cancel_run(self, result: RunResult) -> None:
        """
        Cancel a running execution.
        
        Must be idempotent (safe to call multiple times).
        Should call result.mark_cancelled() when complete.
        """
        ...
    
    def supports_feature(self, feature: str) -> bool:
        """Check if executor supports optional features."""
        return False
    
    async def cleanup(self) -> None:
        """Clean up any resources (called on orchestrator shutdown)."""
        pass
```

### LocalSubprocessExecutor (Reference Implementation)

**Internal State:**
```python
_processes: dict[str, asyncio.subprocess.Process]  # Keyed by run_id
_tasks: dict[str, asyncio.Task]  # Monitor tasks, keyed by run_id
```

**Key Behaviors:**
- Uses `asyncio.create_subprocess_shell()`
- Captures stdout/stderr via `communicate()`
- Implements timeout via `asyncio.wait_for()`
- Cancellation sends SIGTERM, then SIGKILL after grace period
- Cleans up process handles on completion

---

## 10. Data Containers

### ResolvedCommand (frozen)

```python
@dataclass(frozen=True)
class ResolvedCommand:
    command: str  # Fully resolved, no {{ }} templates
    cwd: str | None
    env: dict[str, str]
    timeout_secs: int | None
    vars: dict[str, str]  # Snapshot of merged vars
```

**Purpose:** Clean separation between orchestration and execution. Executor receives concrete instructions, no variable resolution needed.

### RunResult (mutable)

```python
@dataclass
class RunResult:
    # Identity
    command_name: str
    run_id: str
    trigger_event: str | None
    
    # Output
    output: str
    success: bool | None
    error: str | Exception | None
    state: RunState
    
    # Timing
    start_time: datetime | None
    end_time: datetime | None
    duration: timedelta | None
    
    # Snapshot
    resolved_command: ResolvedCommand | None
```

**Critical Rules:**

1. **No subprocess handles** - Executor owns those internally
2. **No future** - Async coordination handled by `RunHandle`
3. **State transitions** - Only via `mark_running/success/failed/cancelled` methods
4. **Immutable after finalization** - Once `_finalize()` called, no further mutations

**State Transition Methods:**
```python
def mark_running() -> None:
    """Set state=RUNNING, record start_time."""

def mark_success() -> None:
    """Set state=SUCCESS, success=True, call _finalize()."""

def mark_failed(error: str | Exception) -> None:
    """Set state=FAILED, success=False, store error, call _finalize()."""

def mark_cancelled(reason: str | None = None) -> None:
    """Set state=CANCELLED, success=None, store reason, call _finalize()."""

def _finalize() -> None:
    """Record end_time, compute duration."""
```

**Helper Properties:**
```python
@property
def duration_secs(self) -> float | None

@property
def duration_str(self) -> str  # Human-readable: "452ms", "2.4s", "1m 23s"

@property
def is_finished(self) -> bool
```

### RunHandle Owns the Future

**Decision:** Move `future` from `RunResult` to `RunHandle`.

**Rationale:**
- Keeps `RunResult` as pure data container
- `RunHandle` is the public facade - appropriate place for async coordination
- Executor completes run by calling `mark_success/failed/cancelled`
- Orchestrator creates future when creating `RunHandle`

**Implementation:**
```python
class RunHandle:
    def __init__(self, result: RunResult):
        self._result = result
        self._future: asyncio.Future[RunResult] = asyncio.get_event_loop().create_future()
        self._completion_task = asyncio.create_task(self._watch_completion())
    
    async def _watch_completion(self):
        """Monitor result.is_finished and complete future when done."""
        while not self._result.is_finished:
            await asyncio.sleep(0.01)  # Poll interval
        self._future.set_result(self._result)
    
    async def wait(self, timeout: float | None = None) -> RunResult:
        if timeout:
            return await asyncio.wait_for(self._future, timeout)
        return await self._future
```

---

## 11. Error Handling

### Callback Error Semantics

**Manual triggers** (`await orchestrator.trigger("event")`):
- Callback exceptions propagate to caller
- Caller sees the exception
- Rationale: User-initiated, fail-fast

**Auto-triggers** (lifecycle events like `command_success:name`):
- Callback exceptions caught by orchestrator
- Logged with full traceback
- Optional error callback invoked
- Execution continues
- Rationale: Internal events should not crash the system

**Implementation Pattern:**
```python
async def _dispatch_callback(callback, handle, context):
    try:
        if asyncio.iscoroutinefunction(callback):
            await callback(handle, context)
        else:
            callback(handle, context)
    except Exception as e:
        if self._is_auto_trigger:
            logger.exception(f"Auto-trigger callback failed: {e}")
            if self._error_callback:
                self._error_callback(e, callback, handle)
        else:
            raise  # Re-raise for manual triggers
```

### Executor Error Handling

**start_run() failures:**
- Executor catches exceptions during launch
- Calls `result.mark_failed(exception)`
- Orchestrator sees completed result with `state=FAILED`

**cancel_run() safety:**
- Must be idempotent
- Should not raise if already cancelled/completed
- Orchestrator wraps calls in try/except anyway

---

## 12. Testing Strategy

### Unit Test Targets

**Pure Logic (No I/O):**
- `ConcurrencyPolicy.decide()` - all concurrency scenarios
- `resolve_double_brace_vars()` - nested resolution, cycles
- `TriggerEngine` matching - exact, wildcards, cycle prevention
- `RunResult` state transitions - all paths
- `CommandConfig` validation - all edge cases

**Stateful (With Mocks):**
- `CommandRuntime` - registration, active tracking, history
- `TriggerEngine` - callback dispatch order
- `CommandOrchestrator` - coordination logic with `MockExecutor`

### Integration Test Targets

**With LocalSubprocessExecutor:**
- Actual subprocess execution
- Output capture
- Timeout handling
- Cancellation (SIGTERM/SIGKILL)
- Concurrent runs

**End-to-End:**
- Load config → execute → trigger → callback
- Complex trigger chains
- Error propagation

### MockExecutor Pattern

```python
class MockExecutor(CommandExecutor):
    def __init__(self):
        self.started: list[tuple[RunResult, ResolvedCommand]] = []
        self.cancelled: list[RunResult] = []
        self._delay: float = 0.0
        self._should_fail: bool = False
    
    async def start_run(self, result: RunResult, resolved: ResolvedCommand):
        self.started.append((result, resolved))
        result.mark_running()
        
        await asyncio.sleep(self._delay)
        
        if self._should_fail:
            result.mark_failed("Simulated failure")
        else:
            result.output = "Simulated output"
            result.mark_success()
    
    async def cancel_run(self, result: RunResult):
        self.cancelled.append(result)
        result.mark_cancelled("Simulated cancel")
```

---

## 13. Implementation Checklist

### Phase 1: Core State Management ✅
- [x] `CommandConfig` with validation
- [x] `RunnerConfig`
- [x] `load_config()` with variable resolution
- [x] `RunResult` with state transitions
- [x] `ResolvedCommand`
- [x] `NewRunDecision`, `TriggerContext`, `CommandStatus`

### Phase 2: Runtime & Policy
- [ ] `CommandRuntime` implementation
  - [ ] Config registry
  - [ ] Active run tracking
  - [ ] History management (deque with maxlen)
  - [ ] Debounce tracking
  - [ ] Status queries
- [ ] `ConcurrencyPolicy` implementation
  - [ ] `decide()` with all concurrency cases
  - [ ] `should_run_on_trigger()`
  - [ ] `should_cancel_on_trigger()`

### Phase 3: Execution Backend
- [ ] `CommandExecutor` ABC
- [ ] `LocalSubprocessExecutor`
  - [ ] Subprocess lifecycle
  - [ ] Output capture
  - [ ] Timeout handling
  - [ ] Cancellation (SIGTERM → SIGKILL)
  - [ ] Cleanup

### Phase 4: Trigger System
- [ ] `TriggerEngine`
  - [ ] Pattern matching (exact + wildcards)
  - [ ] Callback registry
  - [ ] Dispatch with ordering guarantee
  - [ ] Cycle prevention
- [ ] `RunHandle` facade
  - [ ] Properties
  - [ ] `wait()`
  - [ ] `cancel()`

### Phase 5: Orchestrator
- [ ] `CommandOrchestrator`
  - [ ] `run_command()`
  - [ ] `trigger()`
  - [ ] Config management (add/remove/update/reload)
  - [ ] Query methods (list, get_status, get_history)
  - [ ] Callback registration (on_event, off_event, set_lifecycle_callback)
  - [ ] Internal coordination (_prepare_run, _apply_policy, etc.)
  - [ ] Cleanup

### Phase 6: Polish
- [ ] Comprehensive test suite
- [ ] Documentation (API reference, examples)
- [ ] Type hints validation (mypy clean)
- [ ] Performance profiling
- [ ] PyPI packaging

---

## Appendix: Design Rationale

### Why ABC for Executor?
- **Testability** - `MockExecutor` for unit tests
- **Extensibility** - `SSHExecutor`, `DockerExecutor`, `K8sExecutor`
- **Composition** - Wrap executors to add metrics/logging

### Why Pure Data RunResult?
- **Serialization** - Easy JSON export for UIs/persistence
- **Testing** - No mocking of OS calls needed
- **Clarity** - Obvious boundary between data and behavior

### Why Separate ResolvedCommand?
- **Clean API** - Executor receives concrete instructions
- **Testability** - Mock executor doesn't need variable resolution logic
- **Invariants** - Once resolved, immutable and complete

### Why TriggerContext.seen?
- **Safety** - Prevents infinite loops in complex trigger graphs
- **Explicitness** - User can disable per-command via `loop_detection=False`
- **Debuggability** - Logs when cycles are prevented
---

**End of Architecture Reference**