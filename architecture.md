# cmdorc Architecture Reference

**Version:** 0.1.0 (Refactored)  
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

# Handle Management
handle = orchestrator.get_handle_by_run_id(run_id: str) -> RunHandle | None
handles = orchestrator.get_active_handles(name: str) -> list[RunHandle]
all_handles = orchestrator.get_all_active_handles() -> list[RunHandle]

# Cancellation
count = await orchestrator.cancel_command(
    name: str,
    comment: str | None = None
) -> int  # Returns count of runs cancelled

success = await orchestrator.cancel_run(
    run_id: str,
    comment: str | None = None
) -> bool  # Returns True if run was cancelled

count = await orchestrator.cancel_all(
    comment: str | None = None
) -> int  # Returns total count of runs cancelled

# Shutdown
result = await orchestrator.shutdown(
    timeout: float = 30.0,
    cancel_running: bool = True
) -> dict  # Returns: {cancelled_count, completed_count, timeout_expired}

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
handle.is_finalized: bool
handle.start_time: datetime.datetime | None
handle.end_time: datetime.datetime | None
handle.comment: str | None

await handle.wait(timeout: float | None = None) -> RunResult
handle.cleanup() -> None
# Cancels the internal watcher task if still running.
# Should be called when the handle is no longer needed (e.g. during orchestrator shutdown).
# Idempotent and safe to call multiple times.

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
| **CommandOrchestrator** | Public API, coordination, policy application, **RunHandle registry** | Subprocess handles, pattern matching |
| **CommandRuntime** | Registered configs, active RunResults, history, latest results, debounce timestamps | Execution decisions, subprocess lifecycle, handle abstraction |
| **ConcurrencyPolicy** | Concurrency decisions (max_concurrent, on_retrigger) | Pattern matching, state, any I/O |
| **TriggerEngine** | ALL trigger pattern matching (exact + wildcards), callback dispatch, cycle prevention | Command execution, state mutations, concurrency decisions |
| **CommandExecutor** | Subprocess/task lifecycle, output capture | Orchestration policy, trigger logic |

**Note on Handle Registry:** CommandOrchestrator maintains a `_handles: dict[str, RunHandle]` mapping (run_id → RunHandle). CommandRuntime tracks the underlying RunResults only. Users interact with handles (public facade), while the runtime manages results (internal state).

---

## 4. Configuration System

### CommandConfig (frozen dataclass)

```python
@dataclass(frozen=True)
class CommandConfig:
    # Required
    name: str
    command: str  # May contain {{ template_vars }} - resolved at runtime, not load time
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
2. Extract `[variables]` section **as templates** (no resolution at load time)
3. Resolve relative `cwd` paths **relative to config file location**
4. Validate all configs via `CommandConfig.__post_init__`
5. Return immutable `RunnerConfig` with variable templates stored as-is

**Does NOT:**
- Resolve template variables (happens at runtime in `_prepare_run()`)
- Validate variable references exist
- Start any executions
- Modify global state

**Important:** Variable templates are stored verbatim in `RunnerConfig.vars` and `CommandConfig.vars`. They may contain `{{ }}` references that will only be resolved when commands execute.

---

## 5. Variable Resolution

### Two Distinct Phases (Runtime Resolution)

Variables are **NOT** resolved at load time. Instead, they're stored as templates and resolved when commands execute. This enables:
- Environment variable overrides
- Per-run parameter customization
- Dynamic values that change between runs

#### Phase 1: Runtime Merge (Per Execution)
**When:** In `CommandOrchestrator._prepare_run()`
**What:** Merge variables in priority order:
1. `RunnerConfig.vars` (global template vars)
2. `os.environ` (system environment variables)
3. `CommandConfig.vars` (command-specific overrides)
4. `run_command(..., vars={...})` (call-time overrides)

**Result:** `merged_vars: dict[str, str]` (fully populated dictionary)

**Example:**
```toml
[variables]
base_dir = "/home/user/project"  # Global var (stored as template)
test_dir = "{{ base_dir }}/tests"  # Nested template

[[command]]
name = "Tests"
command = "pytest {{ test_dir }}"  # Template string
triggers = ["tests"]
[command.vars]
test_dir = "/alternate/tests"  # Command-specific override
```

When `run_command("Tests", vars={"test_dir": "/custom/tests"})` is called:
- Phase 1 merges: global `/home/user/project` → env vars → command `/alternate/tests` → call-time `/custom/tests`
- Result: `base_dir = "/home/user/project"`, `test_dir = "/custom/tests"`

#### Phase 2: Template Substitution (Pre-Execution)
**When:** In `CommandOrchestrator._prepare_run()` (before executor)
**What:** Create `ResolvedCommand` by substituting `{{ var }}` and `$VAR_NAME` in:
- `command` string
- `env` values
- Any other templated fields

**Result:** `ResolvedCommand` (fully concrete, no templates, immutable)

**Example (continued):**
- Input: `"pytest {{ test_dir }}"`
- Merged vars: `{"test_dir": "/custom/tests", "base_dir": "/home/user/project"}`
- Output: `"pytest /custom/tests"`

**Environment Variable Support:**
- `$VAR_NAME` syntax supported (converted to `{{ VAR_NAME }}` internally)
- Only uppercase identifiers matched (prevents `$$` shell escaping)
- Example: `$HOME` → looks up `os.environ["HOME"]`

### Variable Freezing (Per-Run Immutability)
Once Phase 1 resolves variables for a run, the snapshot is **frozen**:
- Stored in `ResolvedCommand.vars`
- Immutable across run lifetime
- Different runs can see different values if env changes between them

### Critical Rule
**Orchestrator resolves variables at runtime, Executor receives fully resolved data (no templates).**

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
7. Create RunHandle(result), register in orchestrator._handles[run_id]
   ↓
8. Fire command_started:name auto-trigger
   ↓
9. executor.start_run(result, resolved_command)
   ↓
10. Executor marks result.state = RUNNING, manages subprocess
    ↓
11. On completion → executor calls result.mark_success/failed/cancelled
    ↓
12. Orchestrator observes state change, updates runtime (latest_result, history)
    ↓
13. Fire auto-triggers (command_success:name, command_failed:name, etc.)
    ↓
14. Return RunHandle to caller (already in registry for handle management methods)
```

**Handle Lifecycle:**
- Created step 7, available for queries/cancellation immediately
- Unregistered when run completes (via cleanup or history rotation)
- Caller can use `await handle.wait()` to block for completion

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

### Monitoring (internal task)

1. Await RunHandle.wait()
2. Mark complete in runtime
3. Emit lifecycle trigger (success/failed/cancelled)
4. Dispatch lifecycle callback
5. Unregister handle
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

```python
@dataclass
class TriggerContext:
    seen: set[str] = field(default_factory=set)
    history: list[str] = field(default_factory=list)
```

**Design:** Dual-field approach optimizes for both performance and observability:
- **`seen`:** Set for O(1) cycle detection via membership checking
- **`history`:** Ordered list for breadcrumb tracking and debugging

**Rationale:**
- Sets are significantly faster for cycle detection (primary operation)
- Lists provide ordered event history for troubleshooting and UI display
- Both track same events, optimized for different use cases

**Rules:**
1. Fresh context created for each top-level `trigger()` call
2. Before processing event, check if `event_name in context.seen`
3. If already seen → raise `TriggerCycleError` with full `history` breadcrumb
4. After passing cycle check → add to both `context.seen` AND `context.history`

**Escape Hatch:**
If `CommandConfig.loop_detection = False`, that command's auto-triggers do NOT add to `seen`. Use with extreme caution.

### Trigger Chain Tracking (Breadcrumbs)

`TriggerContext` propagates through trigger chains, enabling complete breadcrumb tracking:

```python
# Top-level trigger
context = TriggerContext(seen=set(), history=[])

# Nested trigger (auto-trigger)
child_context = TriggerContext(
    seen=parent_context.seen.copy(),      # Inherit cycle detection
    history=parent_context.history.copy()  # Inherit breadcrumb
)
```

**Propagation flow:**
1. `user_saves` trigger fires → `context.history = ["user_saves"]`
2. Triggers `command_started:Lint` → `context.history = ["user_saves", "command_started:Lint"]`
3. Triggers `command_success:Lint` → `context.history = ["user_saves", "command_started:Lint", "command_success:Lint"]`
4. Each run stores snapshot: `RunResult.trigger_chain = context.history.copy()`

**Access:**
- `RunHandle.trigger_chain` - Live runs (returns copy to prevent mutations)
- `RunResult.trigger_chain` - Historical runs (via `get_history()`)
- `TriggerCycleError.cycle_path` - Full path when cycle detected

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
def get_command(name: str) -> CommandConfig | None

def add_live_run(result: RunResult) -> None
def mark_run_complete(result: RunResult) -> None
def get_active_runs(name: str) -> list[RunResult]

def get_latest_result(name: str) -> RunResult | None
def get_history(name: str, limit: int = 10) -> list[RunResult]

def get_status(name: str) -> CommandStatus
def list_commands() -> list[str]

def check_debounce(name: str, debounce_ms: int) -> bool
```

### Debounce Handling

**Decision:** Debounce is checked in `CommandOrchestrator` **before** calling `ConcurrencyPolicy.decide()`.

**Rationale:**
- `ConcurrencyPolicy` is stateless - it cannot track timestamps
- Debounce is a timing constraint, not a concurrency policy
- `CommandRuntime` tracks start timestamps via explicit `_last_start` dict
- Orchestrator queries runtime before applying policy

**Alternative considered:** Using `latest_result.end_time` instead of separate timestamp tracking.
**Trade-off:** Current approach is more explicit and flexible (e.g., could debounce differently for success vs failure states in future). If simplicity is preferred, can switch to `latest_result.end_time`.

**Flow:**
```python
async def run_command(self, name: str, vars: dict | None = None) -> RunHandle:
    config = self._runtime.get_command(name)
    
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
    """Return True if enough time has passed since last start."""
    last = self._last_start.get(name)
    if last is None:
        return True  # Never run before

    elapsed_ms = (datetime.now() - last).total_seconds() * 1000
    return elapsed_ms >= debounce_ms

# Note: Debounce timestamps are recorded in add_live_run() when the run starts,
# not at completion. This tracks START times, not completion times.
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
    async def cancel_run(self, result: RunResult, comment: str | None = None) -> None:
        """
        Cancel a running execution.

        This method should:
        1. Send termination signal to the process (SIGTERM, then SIGKILL)
        2. Wait for cleanup
        3. Call result.mark_cancelled(comment)

        Must be idempotent (safe to call multiple times).
        Should be a no-op if the run is already finished.

        Args:
            result: The RunResult to cancel
            comment: Optional reason for cancellation (e.g., "timeout", "user request", "retrigger policy")
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
    trigger_chain: list[str]

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
    # Comment (for cancellation reasons, notes, etc.)
    comment: str
    _completion_callback: Callable[[], None] | None = None
    _is_finalized: bool = False
```

**Critical Rules:**

1. **No subprocess handles** - Executor owns those internally
2. **No future** - Async coordination handled by `RunHandle`
3. **State transitions** - Only via `mark_running/success/failed/cancelled` methods
4. **Immutable after finalization** - Once `_finalize()` called, no further mutations
5. **Comment field** - Optional field for cancellation reasons, notes, debugging info (not the same as `error`)
6. **trigger_chain field** - Immutable snapshot of trigger breadcrumb (set at creation, never modified)

**Trigger Chain Details:**
- **Populated at:** `RunResult` creation in `_prepare_run()` (copy of `context.history`)
- **Immutable after:** Finalization (like all result data)
- **For debugging:** Shows "why did this command run?" - full event sequence
- **Examples:**
  - `[]` = manually started via `run_command()`
  - `["user_saves"]` = triggered directly by single event
  - `["user_saves", "command_started:Lint", "command_success:Lint"]` = chained triggers

**State Transition Methods:**
```python
def mark_running(comment: str = None) -> None:
    """Set state=RUNNING, record start_time, optional comment."""

def mark_success(comment: str = None) -> None:
    """Set state=SUCCESS, success=True, call _finalize(), optional comment."""

def mark_failed(error: str | Exception, comment: str = None) -> None:
    """Set state=FAILED, success=False, store error, call _finalize(), optional comment."""

def mark_cancelled(comment: str = None) -> None:
    """Set state=CANCELLED, success=None, call _finalize(), optional comment."""

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
def is_finalized(self) -> bool

def _set_completion_callback(callback)  # Idempotent for same callback
```
**Note:** Mutable during execution; treat as immutable after `is_finalized=True`.

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
- If executor.start_run() raises an exception, orchestrator catches it
- Marks the run as failed with the exception message
- Marks run complete in runtime
- Unregisters the handle to prevent orphaned state
- Re-raises the exception so caller can handle it

**cancel_run() safety:**
- Must be idempotent
- Should not raise if already cancelled/completed
- Orchestrator wraps calls in try/except anyway

### Exception Hierarchy

**Status:** ✅ **Implemented in `src/cmdorc/exceptions.py`**

```python
# exceptions.py

class CmdorcError(Exception):
    """Base exception for all cmdorc errors."""
    pass

class CommandNotFoundError(CmdorcError):
    """Raised when attempting to operate on an unregistered command."""
    pass

class DebounceError(CmdorcError):
    """Raised when a command is triggered within its debounce window."""

    def __init__(self, command_name: str, debounce_ms: int, elapsed_ms: float):
        self.command_name = command_name
        self.debounce_ms = debounce_ms
        self.elapsed_ms = elapsed_ms
        super().__init__(
            f"Command '{command_name}' is in debounce window "
            f"(elapsed: {elapsed_ms:.1f}ms, required: {debounce_ms}ms)"
        )

class ConfigValidationError(CmdorcError):
    """Raised when CommandConfig validation fails."""
    pass

class ExecutorError(CmdorcError):
    """Raised when executor encounters an unrecoverable error."""
    pass

class TriggerCycleError(CmdorcError):
    """Raised when a trigger cycle is detected (when loop_detection=True)."""

    def __init__(self, event_name: str, cycle_path: list[str]):
        self.event_name = event_name
        self.cycle_path = cycle_path
        cycle_display = " -> ".join(cycle_path) + f" -> {event_name}"
        super().__init__(f"Trigger cycle detected: {cycle_display}")

class ConcurrencyLimitError(CmdorcError):
    """Raised when concurrency policy denies command execution."""

    def __init__(
        self,
        command_name: str,
        active_count: int,
        max_concurrent: int,
        policy: str = "ignore",
    ):
        self.command_name = command_name
        self.active_count = active_count
        self.max_concurrent = max_concurrent
        self.policy = policy
        super().__init__(
            f"Command '{command_name}' cannot start: "
            f"{active_count}/{max_concurrent} active, on_retrigger={policy}"
        )

class OrchestratorShutdownError(CmdorcError):
    """Raised when operation is rejected during orchestrator shutdown."""
    pass
```

**Usage:**
- `CommandConfig.__post_init__` raises `ConfigValidationError` for validation failures
- `CommandRuntime.get_command()` raises `CommandNotFoundError` if command not registered
- `run_command()` raises `DebounceError` if in debounce window
- `run_command()` raises `ConcurrencyLimitError` if policy denies execution
- `TriggerEngine` raises `TriggerCycleError` when cycles detected
- `run_command()` and `trigger()` raise `OrchestratorShutdownError` during shutdown

**Benefits:**
- Enables specific exception handling by users
- Provides better error messages with context
- Makes error cases more testable
- Follows Python best practices

---

## 12. Testing Strategy

### Unit Test Targets

**Pure Logic (No I/O):**
- `ConcurrencyPolicy.decide()` - all concurrency scenarios
- `runtime_vars.resolve_double_brace_vars()` - nested resolution, cycles (moved to runtime_vars.py)
- `runtime_vars.merge_vars()` - variable priority ordering
- `runtime_vars.prepare_resolved_command()` - end-to-end resolution
- `TriggerEngine` matching - exact, wildcards, cycle prevention
- `RunResult` state transitions - all paths
- `CommandConfig` validation - all edge cases

**Stateful (With Mocks):**
- `CommandRuntime` - registration, active tracking, history
- `TriggerEngine` - callback dispatch order
- `CommandOrchestrator` - coordination logic with `MockExecutor`

### Integration Test Targets

**With LocalSubprocessExecutor:** ✅
- Actual subprocess execution ✅
- Output capture ✅
- Timeout handling ✅
- Cancellation (SIGTERM/SIGKILL) ✅
- Concurrent runs ✅

**End-to-End:** (pending)
- Load config → execute → trigger → callback
- Complex trigger chains
- Error propagation

### MockExecutor Pattern ✅

```python
class MockExecutor(CommandExecutor):
    def __init__(self, delay: float = 0.0, should_fail: bool = False):
        self.started: list[tuple[RunResult, ResolvedCommand]] = []
        self.cancelled: list[tuple[RunResult, str | None]] = []
        self.delay: float = delay
        self.should_fail: bool = should_fail
        self.failure_message: str = "Simulated failure"
        self.simulated_output: str = "Simulated output"
        self.cleaned_up: bool = False

    async def start_run(self, result: RunResult, resolved: ResolvedCommand):
        self.started.append((result, resolved))
        result.mark_running()

        await asyncio.sleep(self.delay)

        if self.should_fail:
            result.mark_failed(self.failure_message)
        else:
            result.output = self.simulated_output
            result.mark_success()

    async def cancel_run(self, result: RunResult, comment: str | None = None):
        self.cancelled.append((result, comment))
        result.mark_cancelled(comment or "Mock cancellation")
```

**Fully implemented and tested in `mock_executor.py`.**

---

## 13. Implementation Checklist

### Phase 1: Core State Management ✅
- [x] `CommandConfig` with validation
- [x] `RunnerConfig`
- [x] `load_config()` with variable resolution
- [x] `RunResult` with state transitions
- [x] `ResolvedCommand`
- [x] `NewRunDecision`, `TriggerContext`, `CommandStatus`

### Phase 2: Runtime & Policy ✅
- [x] `CommandRuntime` implementation
  - [x] Config registry
  - [x] Active run tracking
  - [x] History management (deque with maxlen)
  - [x] Debounce tracking
  - [x] Status queries
- [x] `ConcurrencyPolicy` implementation
  - [x] `decide()` with all concurrency cases

### Phase 3: Execution Backend ✅
- [x] `CommandExecutor` ABC
- [x] `LocalSubprocessExecutor`
  - [x] Subprocess lifecycle
  - [x] Output capture
  - [x] Timeout handling
  - [x] Cancellation (SIGTERM → SIGKILL)
  - [x] Cleanup
- [x] `MockExecutor` (test double)

### Phase 4: Trigger System & RunHandle ✅
- [x] `TriggerEngine`
  - [x] Pattern matching (exact + wildcards)
  - [x] Callback registry
  - [x] Dispatch with ordering guarantee
  - [x] Cycle prevention
- [x] `RunHandle` facade
  - [x] Properties (command_name, run_id, state, success, output, error, duration_str, is_finalized, start_time, end_time, comment) 
  - [x] `wait()` with optional timeout
  - [x] Internal monitoring task (event-driven via asyncio.Event) 

### Phase 5: Orchestrator
- [x] `CommandOrchestrator`
  - [x] `run_command()` - returns RunHandle
  - [x] `trigger()` - event dispatching with cycle prevention
  - [x] Config management (add/remove/update/reload)
  - [x] Query methods (list, get_status, get_history)
  - [x] Handle management:
    - [x] `get_handle_by_run_id()`
    - [x] `get_active_handles()`
    - [x] `get_all_active_handles()`
  - [x] Cancellation:
    - [x] `cancel_command()` - cancel all runs of a command
    - [x] `cancel_run()` - cancel specific run by run_id
    - [x] `cancel_all()` - cancel all active runs
  - [x] Graceful shutdown:
    - [x] `shutdown()` - with timeout and optional cancel_running
  - [x] Callback registration (on_event, off_event, set_lifecycle_callback)
  - [x] Internal coordination (_prepare_run, _apply_policy, etc.)
  - [x] Internal handle registry management (_register_handle, _unregister_handle)
  - [x] Cleanup

### Phase 6: Polish
- [x] Comprehensive test suite (in progress: ~100+ tests so far)
- [x] Documentation (API reference, examples)
- [x] Type hints validation (mypy clean)
- [x] Performance profiling
- [x] PyPI packaging

---

## Current Implementation Status

### ✅ Completed Components (Production Ready)

1. **Configuration System** - `CommandConfig`, `RunnerConfig`, `load_config()`
2. **Runtime Variable Resolution** - `runtime_vars.py` with merge/resolve logic (30 tests, 100% coverage)
3. **State Management** - `CommandRuntime` (full implementation with 48 tests)
4. **Concurrency Policy** - `ConcurrencyPolicy`
5. **Data Containers** - `RunResult`, `ResolvedCommand`, type definitions
6. **Executor System** - ABC, `LocalSubprocessExecutor`, `MockExecutor` (48 tests)
7. **Exception System** - `CmdorcError` hierarchy with 40 tests, 100% coverage
8. **RunHandle** - Public async facade for command runs (33 tests, 100% coverage)
9. **TriggerEngine** - Pattern matching, callbacks, cycle prevention (planned)
10. **CommandOrchestrator** - Main coordinator tying everything together (planned)

### 📊 Code Statistics

- **Total lines of production code:** ~2,900
- **Total lines of test code:** ~2,500
- **Test coverage:** 95% overall (all completed components have comprehensive tests)
  - `run_handle.py`: 100% coverage (71 statements, 33 tests)
  - `exceptions.py`: 100% coverage (22 statements, 40 tests)
  - `runtime_vars.py`: 100% coverage (58 statements, 30 tests)
  - `load_config.py`: 92% coverage
- **Total tests:** 220 tests passing
- **Components completed:** 8 of 8 core components (Orchestrator+TriggerEngine are next)

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
- **Clarity** - Obvious boundary between data and behavior
- **Invariants** - Once resolved, immutable and complete

### Why TriggerContext.seen?
- **Safety** - Prevents infinite loops in complex trigger graphs
- **Explicitness** - User can disable per-command via `loop_detection=False`
- **Debuggability** - Logs when cycles are prevented

---

## Appendix B: Future Enhancements

**Source:** External architecture review (December 2025)
**Status:** Recommendations for future implementation

### For CommandOrchestrator Implementation

**1. Resource Cleanup**
```python
def cleanup(self) -> None:
    """Cancel the RunHandle watcher tasks if active. Idempotent."""
```
- **Priority:** Should have before 1.0
- **Rationale:** Prevents lingering asyncio tasks when orchestrator shuts down or handles are garbage collected after long-lived runs.

**1. Convenience Cancellation Method**
```python
async def cancel_command(name: str, comment: str | None = None) -> int:
    """Cancel all active runs of a command. Returns count of cancelled runs."""
```
- **Priority:** Should have before 1.0
- **Rationale:** Common operation, cleaner API

**2. Debugging/Inspection Methods**
```python
def get_trigger_graph() -> dict[str, list[str]]
"""Returns mapping of triggers to commands."""

def get_active_commands() -> list[str]
"""Returns list of command names with active runs."""

def explain_trigger(event_name: str) -> dict
"""Explain what would happen if this event were triggered (dry-run)."""
```
- **Priority:** Should have for production use
- **Rationale:** Essential for debugging complex trigger graphs

**3. Graceful Shutdown**
```python
async def shutdown(timeout: float = 30.0, cancel_running: bool = True) -> dict
"""Gracefully shut down orchestrator with optional timeout."""
```
- **Priority:** Must have for production
- **Rationale:** Prevents orphaned subprocesses, clean lifecycle management


### Optional Enhancements (Post 1.0)

**1. RunResult.metadata Field**
```python
metadata: dict[str, Any] = field(default_factory=dict)
```
- Extensibility for custom executors (e.g., hostname, resource usage)
- Not critical for core functionality

**2. TriggerContext.history for Debugging**
```python
history: list[str] = field(default_factory=list)  # Ordered event list
```
- Helpful for debugging trigger chains
- Could be opt-in via debug mode to avoid overhead

**3. Enhanced loop_detection Safety**
- Require explicit `_allow_infinite_loops=True` when `loop_detection=False`
- Similar to Terraform's confirmation for dangerous operations
- **Decision:** Keep simple for now, users are expected to understand the config

---

**End of Architecture Reference**