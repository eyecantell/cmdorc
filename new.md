# cmdorc Design Decisions & Rationale

This document captures key architectural decisions made during the design and refactoring of cmdorc, including rationale, trade-offs, and implementation guidance.

---

## Table of Contents

1. [Async/Await Consistency](#asyncawait-consistency)
2. [Pure Data Container Philosophy](#pure-data-container-philosophy)
3. [RunnerConfig vs CommandRuntime](#runnerconfig-vs-commandruntime)
4. [Working Directory Resolution](#working-directory-resolution)
5. [CommandExecutor Swappability](#commandexecutor-swappability)
6. [Error Handling Strategy](#error-handling-strategy)
7. [Rapid Re-trigger Handling](#rapid-re-trigger-handling)
8. [Auto-Triggers vs Manual Triggers](#auto-triggers-vs-manual-triggers)
9. [Variable Resolution Phases](#variable-resolution-phases)
10. [History Management](#history-management)
11. [RunResult Future Behavior](#runresult-future-behavior)
12. [Task Tracking Location](#task-tracking-location)

---

## Async/Await Consistency

### Decision
`run_command()` returns immediately with a handle (non-blocking).

### Usage
```python
# Returns immediately, command runs in background
handle = await orchestrator.run_command("build")

# User can wait explicitly if needed
await handle.wait()

# Or access the future directly
result = await handle._result.future
```

### Rationale
- **Maximum flexibility**: Users choose when to wait
- **Fire-and-forget workflows**: Don't block on command completion
- **Concurrent execution**: Can launch multiple commands without blocking
- **Async best practices**: Spawn task, await separately (like `asyncio.create_task()`)

### Trade-offs
- **Pro**: More powerful API, supports complex orchestration patterns
- **Con**: Slightly more complex than "await until done" for simple cases
- **Mitigation**: Provide helper methods like `wait_for_success()` for common patterns

---

## Pure Data Container Philosophy

### Decision
`RunResult` is a pure data container with no side effects or business logic.

### What This Means
- ❌ No subprocess management
- ❌ No `task` field on RunResult
- ❌ No business logic or decision making
- ✅ Only state tracking and derived properties
- ✅ `future.set_result()` always succeeds (never `set_exception()`)

### Example: Pure vs Impure

#### ✅ Pure (Current Design)
```python
# Easy to test - no mocking needed
result = RunResult(command_name="test")
result.mark_running()
result.output = "test output"
result.mark_success()

assert result.state == RunState.SUCCESS
assert result.success is True
assert result.duration_secs < 1.0
```

#### ❌ Impure (Rejected Alternative)
```python
# Would need complex mocking
result = RunResult(command_name="test")
await result.execute()  # Who owns the subprocess?
# Where does the process live?
# How do we test without real subprocess?
```

### Benefits

1. **Predictable Testing**
   - Construct in tests with any state
   - No need to mock subprocess, asyncio, or OS calls
   - Can test state transitions in isolation

2. **Clear Ownership**
   ```python
   # Clear separation of concerns:
   # - RunResult = state tracking (what happened)
   # - CommandExecutor = lifecycle management (how it happened)
   # - CommandOrchestrator = coordination (when it happened)
   ```

3. **Serialization**
   ```python
   # Easy to convert to JSON for TUIs, APIs, persistence
   status_json = result.to_dict()
   send_to_ui(status_json)
   save_to_disk(status_json)
   ```

4. **Thread Safety** (future consideration)
   - Simple locking around mutations
   - No cross-thread process communication complexity

### Who Manages What

| Component | Responsibility |
|-----------|----------------|
| `RunResult` | State tracking (pending/running/success/failed/cancelled) |
| `CommandExecutor` | Subprocess lifecycle (start, monitor, cancel) |
| `CommandRuntime` | Registry and history (active runs, completed runs) |
| `CommandOrchestrator` | Coordination (policy, triggers, callbacks) |

---

## RunnerConfig vs CommandRuntime

### Decision
Keep `RunnerConfig` and `CommandRuntime` as separate components despite apparent overlap.

### Comparison

| Aspect | RunnerConfig | CommandRuntime |
|--------|--------------|----------------|
| **Mutability** | Frozen (immutable) | Mutable |
| **When Created** | Config load time | Orchestrator init |
| **Lifespan** | Read once, discarded | Lives entire session |
| **Purpose** | Configuration input | State tracking |
| **Contains** | Command definitions, global vars | Active runs, history, status |
| **Hot Reload** | Can't modify | Can add/remove/update commands |

### Analogy
- **RunnerConfig** = Blueprint (what to build)
- **CommandRuntime** = Construction site (what's being built, what's done, what's in progress)

### Why Not Merge?

If they were merged into one class:

```python
# ❌ Merged (problems)
class CommandRuntime:
    commands: list[CommandConfig]  # Config or state? Immutable or not?
    vars: dict[str, str]           # Global or per-command?
    _active_runs: dict[str, list[RunResult]]
    _history: dict[str, deque[RunResult]]
```

**Problems**:
1. Unclear ownership of `commands` field
2. Can't reload config without losing active runs
3. Mixing immutable config with mutable state
4. Hard to serialize (do you save active runs with config?)

### Hot Reload Example

```python
# With separation, hot reload is clean:
new_config = load_config(path)  # Fresh immutable RunnerConfig

for cmd in new_config.commands:
    if runtime.get_config(cmd.name):
        runtime.replace_command(cmd)  # Update definition
    else:
        runtime.register_command(cmd)  # Add new

# Active runs preserved! State tracking independent of config.
```

### Data Flow
```
Config File → load_config() → RunnerConfig (frozen)
                                    ↓
                            CommandOrchestrator.__init__()
                                    ↓
                            CommandRuntime (mutable)
                                    ↓
                            Active runs, history, status
```

---

## Working Directory Resolution

### Decision
Relative `cwd` paths are resolved relative to the config file's directory, not the program's working directory.

### Example
```toml
# /home/user/projects/myapp/cmdorc.toml
[commands.build]
command = "make build"
cwd = "./build"  
# Resolves to: /home/user/projects/myapp/build
# NOT: wherever the user ran the program from
```

### Rationale

1. **Portability**: Can move project directory, config still works
2. **Intuition**: Users expect paths relative to config location
3. **Consistency**: Behavior independent of where program is executed
4. **Industry Standard**: 
   - Docker Compose: paths relative to `docker-compose.yml`
   - package.json: paths relative to `package.json`
   - Makefile: paths relative to Makefile location
   - .env files: paths relative to `.env`

### Counter-Example (Why Not Program CWD)

```bash
# User runs program from different directory:
cd /home/user
python -m myapp --config projects/myapp/cmdorc.toml

# If cwd="./build" was relative to program CWD:
# Would resolve to: /home/user/build (WRONG!)

# With config-relative resolution:
# Resolves to: /home/user/projects/myapp/build (CORRECT!)
```

### Implementation

```python
def load_config(path: Path) -> RunnerConfig:
    config_dir = path.parent.resolve()
    data = tomli.loads(path.read_text())
    
    commands = []
    for cmd_data in data.get("commands", {}).values():
        if cwd := cmd_data.get("cwd"):
            cwd_path = Path(cwd)
            if not cwd_path.is_absolute():
                # Make relative paths absolute
                cwd = str(config_dir / cwd_path)
        
        commands.append(CommandConfig(..., cwd=cwd))
    
    return RunnerConfig(commands=commands, vars=...)
```

### Documentation in CommandConfig

```python
cwd: str | Path | None = None
"""
Optional working directory for the command.
- Absolute paths used as-is
- Relative paths resolved relative to the directory containing the config file
- Resolution happens during config loading (in load_config.py)
- Stored as absolute path string in CommandConfig after loading
"""
```

---

## CommandExecutor Swappability

### Decision
Make `CommandExecutor` an abstract base class to enable swapping implementations.

### Interface

```python
from abc import ABC, abstractmethod

class CommandExecutor(ABC):
    """Abstract base class for command execution backends"""
    
    @abstractmethod
    async def start_run(
        self, 
        result: RunResult, 
        config: CommandConfig, 
        run_vars: dict[str, str] | None = None
    ) -> None:
        """Execute command and update result with outcome"""
        pass
    
    @abstractmethod
    async def cancel_run(self, result: RunResult) -> None:
        """Cancel a running command (idempotent)"""
        pass
    
    def supports_feature(self, feature: str) -> bool:
        """Check if executor supports optional features"""
        return feature in {
            "cancellation", "timeout", "output_capture",
            "working_directory", "environment"
        }
    
    async def cleanup(self) -> None:
        """Optional cleanup hook for shutdown"""
        pass
```

### Default Implementation

```python
class LocalSubprocessExecutor(CommandExecutor):
    """Default executor - runs commands as local subprocesses"""
    
    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._monitor_tasks: dict[str, asyncio.Task] = {}
    
    async def start_run(self, result: RunResult, config: CommandConfig, ...) -> None:
        # Resolve template vars in command
        # Launch subprocess
        # Track process by result.run_id
        # Monitor completion
        pass
    
    async def cancel_run(self, result: RunResult) -> None:
        # SIGTERM → wait → SIGKILL if needed
        pass
```

### Use Cases

#### 1. Testing
```python
class MockExecutor(CommandExecutor):
    """Predictable executor for tests - no real subprocesses"""
    
    async def start_run(self, result: RunResult, ...) -> None:
        result.mark_running()
        await asyncio.sleep(0.01)  # Simulate work
        result.mark_success()
        result.output = "Mock output"

# In tests:
orchestrator = CommandOrchestrator(config, executor=MockExecutor())
handle = await orchestrator.run_command("test")
assert handle.success  # Fast, predictable, no subprocess overhead
```

#### 2. Remote Execution
```python
class SSHExecutor(CommandExecutor):
    """Run commands on remote hosts via SSH"""
    def __init__(self, host: str, user: str):
        self.connection = SSHConnection(host, user)

class DockerExecutor(CommandExecutor):
    """Run commands in containers"""
    def __init__(self, image: str):
        self.image = image

class KubernetesJobExecutor(CommandExecutor):
    """Run as Kubernetes Jobs"""
    pass
```

#### 3. Instrumentation
```python
class InstrumentedExecutor(CommandExecutor):
    """Wrap another executor with metrics/logging"""
    def __init__(self, inner: CommandExecutor, metrics: MetricsCollector):
        self.inner = inner
        self.metrics = metrics
    
    async def start_run(self, result: RunResult, ...) -> None:
        start = time.time()
        try:
            await self.inner.start_run(result, ...)
            self.metrics.record_success(result.command_name, time.time() - start)
        except Exception as e:
            self.metrics.record_failure(result.command_name, str(e))
            raise
```

#### 4. Resource Control
```python
class ThrottledExecutor(CommandExecutor):
    """Limit concurrent executions and resource usage"""
    def __init__(self, max_concurrent: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def start_run(self, result: RunResult, ...) -> None:
        async with self.semaphore:
            # Use cgroups/ulimit to restrict resources
            pass
```

#### 5. Development
```python
class DryRunExecutor(CommandExecutor):
    """Log commands without executing (for testing configs)"""
    async def start_run(self, result: RunResult, config: CommandConfig, ...) -> None:
        print(f"Would execute: {config.command}")
        result.mark_success()
```

### Benefits

| Benefit | Example |
|---------|---------|
| **Testability** | MockExecutor with instant responses |
| **Extensibility** | SSH, Docker, K8s executors |
| **Composition** | Wrap executors (logging, metrics, retry) |
| **Resource Control** | Throttling, memory limits |
| **Development** | Dry-run executor that logs without running |

### Trade-offs

**Pros**:
- Clean separation of concerns
- Easy to test without subprocess overhead
- Enables advanced use cases
- Future-proof for new backends

**Cons**:
- Slightly more complex than hardcoded subprocess logic
- Need to maintain interface contract
- Executors must handle edge cases consistently

**Verdict**: ✅ Benefits far outweigh minimal complexity

---

## Error Handling Strategy

### Decision
Callback errors throw exceptions to the caller.

### Behavior

```python
orchestrator.on_event("command_success:build", failing_callback)

# If failing_callback raises, exception propagates to:
# - The trigger() caller (for manual triggers)
# - The orchestrator's error handling (for auto-triggers)
```

### Rationale
1. **Visibility**: Errors are never silent
2. **Debuggability**: Clear stack traces point to problem
3. **Flexibility**: Users can wrap in try/catch if desired
4. **Fail-fast**: Detect problems immediately, not later

### Error Sources

| Error Type | Example | Handling |
|------------|---------|----------|
| **Run failures** | Command returns non-zero exit code | `result.mark_failed()`, `result.success = False` |
| **Callback errors** | Callback raises exception | Propagates to caller or logged (auto-triggers) |
| **Startup failures** | Bad command syntax, missing binary | `result.mark_failed()` before process starts |
| **Timeout** | Command exceeds `timeout_secs` | `result.mark_cancelled("timeout")` |

### Auto-Trigger Error Handling

```python
async def _fire_auto_triggers(self, event_name: str, result: RunResult) -> None:
    try:
        await self._trigger_engine.on_event(event_name, ...)
    except Exception as e:
        logger.error(f"Auto-trigger '{event_name}' failed: {e}")
        # Log but don't stop orchestrator
        # User can register error callback to handle
```

---

## Rapid Re-trigger Handling

### Decision
Follow policy (max_concurrent, on_retrigger), no automatic debouncing/queuing.

### Current Behavior

When the same event fires rapidly:
1. `ExecutionPolicy.decide()` enforces `max_concurrent` limit
2. `on_retrigger` determines behavior:
   - `"cancel_and_restart"`: Cancel active runs, start new one
   - `"ignore"`: Drop new trigger if at limit
3. No automatic debouncing
4. No queue of pending runs

### Example

```toml
[commands.build]
command = "make build"
max_concurrent = 1
on_retrigger = "cancel_and_restart"
```

```python
# Rapid triggers:
await orchestrator.trigger("build")  # Starts run #1
await orchestrator.trigger("build")  # Cancels #1, starts run #2
await orchestrator.trigger("build")  # Cancels #2, starts run #3
# Only run #3 completes
```

### Rationale
- **Simplicity**: Easy to understand and predict
- **Correctness**: Policy enforces configured behavior
- **Flexibility**: Users can add debouncing externally if needed
- **Future-proof**: Can add as opt-in feature later

### Future Enhancement (Not in Initial Release)

```python
@dataclass(frozen=True)
class CommandConfig:
    # ...
    debounce_ms: int = 0  # Optional: ignore triggers within N ms of last
    queue_depth: int = 0  # Optional: queue up to N pending runs
```

---

## Auto-Triggers vs Manual Triggers

### Decision
Auto-triggers are code-generated lifecycle events. Manual triggers are config-defined or user-called.

### Auto-Triggers (Generated by Orchestrator)

Always fired automatically after state transitions:
- `command_started:<command_name>`
- `command_success:<command_name>`
- `command_failed:<command_name>`
- `command_cancelled:<command_name>`

```python
# Orchestrator automatically calls:
await self._trigger_engine.on_event(f"command_success:{name}", ...)
```

### Manual Triggers (User-Defined)

Only exist if specified in `CommandConfig.triggers` or called explicitly:

```toml
[commands.deploy]
triggers = ["tests_passed", "manual_deploy"]
```

```python
# User triggers explicitly:
await orchestrator.trigger("tests_passed", context={"branch": "main"})
```

### Both Support

- Callbacks via `on_event()`
- Wildcard matching (`"command_*"`, `"*:deploy"`)
- Cycle prevention via `TriggerContext`
- Context passing

### Example Workflow

```toml
[commands.test]
command = "pytest"
triggers = ["code_changed"]

[commands.deploy]
triggers = ["command_success:test"]  # Auto-trigger from test success
```

```python
# User saves file:
await orchestrator.trigger("code_changed")

# This causes:
# 1. "code_changed" → starts test command
# 2. Test completes → auto-trigger "command_success:test"
# 3. "command_success:test" → starts deploy command
```

---

## Variable Resolution Phases

### Decision
Three distinct phases of variable resolution.

### Phase 1: Config Load Time (Static)

```toml
[variables]
base_dir = "/home/user/project"
test_dir = "{{ base_dir }}/tests"  # Resolved during load
build_dir = "{{ base_dir }}/build"
```

After loading:
```python
config.vars = {
    "base_dir": "/home/user/project",
    "test_dir": "/home/user/project/tests",  # Already resolved
    "build_dir": "/home/user/project/build"
}
```

**Handled by**: `resolve_double_brace_vars()` in `load_config.py`

### Phase 2: Runtime Override (Dynamic)

```python
# User provides runtime values:
await orchestrator.run_command("build", vars={"target": "prod", "version": "2.0"})

# Merged in order (later overrides earlier):
# 1. Global vars from RunnerConfig.vars
# 2. Command-specific vars from CommandConfig.vars
# 3. Runtime vars from run_command() call
```

**Handled by**: `CommandExecutor.start_run()`

### Phase 3: Subprocess Execution (Environment)

```python
# In CommandExecutor.start_run():
resolved_env = {
    **os.environ,           # System environment
    **config.env,           # Command-specific env vars
    **runtime_vars_as_env   # Converted run_vars
}

proc = await asyncio.create_subprocess_shell(..., env=resolved_env)
```

**Handled by**: `LocalSubprocessExecutor`

### Template Resolution in Commands

```toml
[commands.build]
command = "gcc -o {{ output_dir }}/app main.c"
```

The `{{ output_dir }}` is resolved at **Phase 2** (runtime), using merged vars.

### Cycle Detection

```toml
[variables]
a = "{{ b }}"
b = "{{ a }}"  # ERROR: Cycle detected during config load
```

Handled by `resolve_double_brace_vars()` with cycle tracking.

---

## History Management

### Decision
`keep_history` controls history retention, but `latest_result` is always available.

### Behavior

```python
keep_history: int = 1
"""
How many completed RunResult objects to keep in history.
- 0 = no history retained (but latest_result always tracked)
- 1 = keep 1 in history + latest_result (default)
- N = keep N in history + latest_result
"""
```

### Implementation

```python
# CommandRuntime maintains two separate structures:
self._history: dict[str, deque[RunResult]] = {}      # Limited by keep_history
self._latest_result: dict[str, RunResult] = {}       # Always has most recent

# When run completes:
def mark_run_complete(self, result: RunResult) -> None:
    name = result.command_name
    config = self._commands[name]
    
    # Always update latest
    self._latest_result[name] = result
    
    # Add to history if keep_history > 0
    if config.keep_history > 0:
        if name not in self._history:
            self._history[name] = deque(maxlen=config.keep_history)
        self._history[name].append(result)
```

### API Behavior

```python
# Always available (even if keep_history=0):
latest = runtime.get_latest_result("build")

# Returns up to keep_history items:
history = runtime.get_history("build")  # Returns [] if keep_history=0

# Status always shows latest:
status = runtime.get_status("build")
status.last_run  # Same as get_latest_result()
```

### Rationale

1. **UI Needs**: Status displays always need most recent result
2. **Memory Control**: Long-running orchestrators can limit history
3. **Separation of Concerns**: Latest result ≠ historical runs
4. **Predictability**: Users always have access to latest state

---

## RunResult Future Behavior

### Decision
`result.future` always resolves successfully with `set_result(self)`, never raises exceptions.

### Implementation

```python
def _finalize(self) -> None:
    """Record end time, compute duration, and signal the future."""
    self.end_time = datetime.datetime.now()
    if self.start_time:
        self.duration = self.end_time - self.start_time
    else:
        self.duration = datetime.timedelta(0)

    # Always set result successfully - callers check state/success
    if not self.future.done():
        self.future.set_result(self)
```

### Usage

```python
# Wait for completion:
result = await run_result.future

# Check outcome:
if result.state == RunState.SUCCESS:
    print("Success!")
elif result.state == RunState.FAILED:
    print(f"Failed: {result.error}")
elif result.state == RunState.CANCELLED:
    print("Cancelled")
```

### Rationale

**Separation of concerns**:
- **Run failures** (command returned non-zero) → stored in `result.state` and `result.success`
- **Callback errors** (callback raised exception) → propagated separately
- **Future completion** → just signals "run finished", doesn't carry semantics of success/failure

**Benefits**:
1. Consistent interface (await always succeeds)
2. No exception handling needed for normal failures
3. Clear: `future` = completion signal, `state` = outcome
4. Allows chaining without try/catch overhead

### Alternative Rejected

```python
# ❌ Rejected: future.set_exception() on failure
if result.state == RunState.SUCCESS:
    future.set_result(self)
else:
    future.set_exception(RuntimeError(result.error))

# Would require:
try:
    result = await run_result.future
except RuntimeError:
    # Command failed... but this is expected behavior, not exceptional
```

This conflates normal failure (command returns non-zero) with exceptional conditions.

---

## Task Tracking Location

### Decision
`CommandExecutor` tracks monitoring tasks internally, not in `RunResult`.

### Why Not in RunResult?

```python
# ❌ Rejected: task field in RunResult
@dataclass
class RunResult:
    task: asyncio.Task | None = None  # Who sets this? When? How to serialize?
```

**Problems**:
1. Violates pure data container principle
2. Serialization becomes complex (can't serialize tasks)
3. Unclear ownership (who creates/manages task?)
4. Testing complexity (need to mock task management)

### Current Approach

```python
# ✅ Accepted: executor tracks tasks
class LocalSubprocessExecutor(CommandExecutor):
    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._monitor_tasks: dict[str, asyncio.Task] = {}  # Keyed by result.run_id
    
    async def start_run(self, result: RunResult, ...) -> None:
        # Start subprocess
        proc = await asyncio.create_subprocess_shell(...)
        self._processes[result.run_id] = proc
        
        # Create monitoring task
        task = asyncio.create_task(self._monitor_process(result, proc))
        self._monitor_tasks[result.run_id] = task
    
    async def cancel_run(self, result: RunResult) -> None:
        # Look up and cancel task
        if task := self._monitor_tasks.get(result.run_id):
            task.cancel()
        if proc := self._processes.get(result.run_id):
            proc.terminate()
```

### Benefits

1. **Clean separation**: RunResult = data, Executor = lifecycle
2. **Easy testing**: Mock executor, real RunResult
3. **Serialization**: RunResult.to_dict() works without special cases
4. **Ownership**: Executor clearly owns subprocess/task lifecycle

---

## Summary Table

| Decision | Choice | Key Rationale |
|----------|--------|---------------|
| **run_command() blocking?** | No, returns handle immediately | Flexibility, concurrency support |
| **RunResult pure data?** | Yes | Testability, clear ownership |
| **Merge RunnerConfig/Runtime?** | No, keep separate | Immutable config vs mutable state |
| **CWD resolution?** | Relative to config file | Portability, industry standard |
| **Swappable executor?** | Yes, ABC pattern | Testing, extensibility |
| **Callback errors?** | Throw exceptions | Visibility, fail-fast |
| **Debouncing?** | Not initially | Simplicity, can add later |
| **Auto vs manual triggers?** | Both supported | Flexibility, clear distinction |
| **Variable phases?** | Three distinct phases | Clear resolution order |
| **History tracking?** | Separate from latest_result | Memory control, UI needs |
| **Future exceptions?** | Never, always set_result | Cleaner API, clear semantics |
| **Task tracking?** | In executor, not result | Pure data principle |