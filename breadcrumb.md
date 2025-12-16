# Breadcrumb Implementation Plan (Corrected)

**Goal:** Add trigger chain tracking to cmdorc without breaking changes, performance degradation, or architectural violations.

**Core Principle:** Extend, don't replace. Keep `TriggerContext.seen` for O(1) cycle detection, add `history` for breadcrumbs.

---

## Design Decisions

### 1. Data Structure Choices

**TriggerContext:**
```python
@dataclass
class TriggerContext:
    seen: set[str] = field(default_factory=set)      # O(1) cycle detection (keep)
    history: list[str] = field(default_factory=list)  # Ordered breadcrumb (add)
```
- Both `seen` and `history` track the same events
- `seen` for fast cycle detection (O(1))
- `history` for ordered display and propagation

**RunResult:**
```python
@dataclass
class RunResult:
    trigger_event: str | None = None                 # Keep for backward compat
    trigger_chain: list[str] = field(default_factory=list)  # Add new field
```
- Use `list[str]` not `tuple` (simpler, RunResult is mutable anyway)
- `trigger_event` remains for existing code
- `trigger_chain` is the full breadcrumb

**Relationship:**
- `trigger_event` = immediate trigger (last event before this run started)
- `trigger_chain` = full path from root trigger to this run
- Example: `trigger_chain = ["user_saves", "command_success:Lint"]`, `trigger_event = "command_success:Lint"`

### 2. Propagation Strategy

**Three scenarios:**

1. **Manual run_command()** - No trigger context
   ```python
   handle = await orchestrator.run_command("Tests")
   # trigger_chain = []
   # trigger_event = None
   ```

2. **Root trigger()** - User fires event
   ```python
   await orchestrator.trigger("user_saves")
   # Creates new context: history=["user_saves"]
   # Commands get: trigger_chain=["user_saves"]
   ```

3. **Chained trigger** - Auto-trigger from command completion
   ```python
   # After Lint succeeds, fires "command_success:Lint"
   # Inherits parent chain: ["user_saves"] + ["command_success:Lint"]
   # Next command gets: trigger_chain=["user_saves", "command_success:Lint"]
   ```

### 3. Context Lifecycle

**Key insight:** TriggerContext is **created fresh** for each top-level trigger, then **copied with extensions** for nested triggers.

```python
# Top-level trigger
context = TriggerContext(seen=set(), history=[])

# Nested trigger (auto-trigger)
child_context = TriggerContext(
    seen=parent_context.seen.copy(),      # Inherit cycle detection
    history=parent_context.history.copy()  # Inherit breadcrumb
)
```

**No stack cleanup needed** - each trigger gets its own context branch.

---

## Implementation Steps

### Phase 1: Data Model Updates (No Behavior Changes)

#### Step 1.1: Update `types.py`
```python
@dataclass
class TriggerContext:
    """Context for tracking triggers and preventing cycles."""
    
    seen: set[str] = field(default_factory=set)
    """Events already processed in this trigger chain (for O(1) cycle detection)."""
    
    history: list[str] = field(default_factory=list)
    """Ordered list of events in this trigger chain (for breadcrumb display)."""
```

**Testing:**
- Run existing tests - should all pass (no behavior change yet)
- Verify `TriggerContext()` creates empty seen and history

#### Step 1.2: Update `run_result.py`
```python
@dataclass
class RunResult:
    # ... existing fields ...
    
    trigger_event: str | None = None
    """Immediate trigger event that started this run (for backward compatibility)."""
    
    trigger_chain: list[str] = field(default_factory=list)
    """Ordered list of trigger events leading to this run.
    
    Examples:
      - [] = manually started via run_command()
      - ["user_saves"] = triggered directly by user_saves event
      - ["user_saves", "command_success:Lint"] = chained trigger
    
    The last element matches trigger_event (if trigger_event is not None).
    """
```

**Update `to_dict()` method:**
```python
def to_dict(self) -> dict[str, Any]:
    return {
        # ... existing fields ...
        "trigger_event": self.trigger_event,
        "trigger_chain": self.trigger_chain.copy(),  # Add this
        # ... rest ...
    }
```

**Update `__repr__()` method:**
```python
def __repr__(self) -> str:
    chain_display = "->".join(self.trigger_chain) if self.trigger_chain else "manual"
    return (
        f"RunResult(id={self.run_id[:8]}, cmd='{self.command_name}', "
        f"state={self.state.value}, chain={chain_display})"
    )
```

**Testing:**
- Create `RunResult` with empty chain - should work
- Create `RunResult` with populated chain - should work
- Verify `to_dict()` includes `trigger_chain`
- Verify `__repr__()` shows chain

---

### Phase 2: Context Propagation (Core Logic)

#### Step 2.1: Update `trigger()` in `command_orchestrator.py`

**Current implementation:**
```python
async def trigger(self, event_name: str, context: TriggerContext | None = None):
    if context is None:
        context = TriggerContext(seen=set())
    
    if not self._trigger_engine.check_cycle(event_name, context):
        raise TriggerCycleError(event_name, list(context.seen))
    
    context.seen.add(event_name)
    # ... rest of logic ...
```

**New implementation:**
```python
async def trigger(self, event_name: str, context: TriggerContext | None = None):
    # Check shutdown
    if self._is_shutdown:
        raise OrchestratorShutdownError("Orchestrator is shutting down")
    
    # Create or extend context
    async with self._orchestrator_lock:
        if context is None:
            # Root trigger - fresh context
            context = TriggerContext(seen=set(), history=[])
        
        # Check cycle BEFORE adding
        if not self._trigger_engine.check_cycle(event_name, context):
            # Include history in error for better debugging
            raise TriggerCycleError(event_name, context.history)
        
        # Add to both seen and history
        context.seen.add(event_name)
        context.history.append(event_name)
    
    # Release lock before executing commands/callbacks
    
    logger.debug(f"Trigger: {event_name} (chain: {' -> '.join(context.history)})")
    
    # Rest of existing logic (cancel_on_triggers, triggers, callbacks)
    # ... unchanged from current implementation ...
```

**Key changes:**
1. Initialize `history=[]` when creating fresh context
2. Check cycle using existing `_trigger_engine.check_cycle()` (still uses `seen`)
3. Add to both `seen` and `history`
4. Log the full chain for debugging
5. Pass updated context to subsequent calls

**Testing:**
- Manual trigger with no context - should create fresh context
- Manual trigger with existing context - should extend it
- Cycle detection - should raise `TriggerCycleError` with history

#### Step 2.2: Update `_prepare_run()` signature

**Current:**
```python
def _prepare_run(
    self,
    config: CommandConfig,
    call_time_vars: dict[str, str] | None,
    trigger_event: str | None,
) -> tuple[ResolvedCommand, RunResult]:
```

**New:**
```python
def _prepare_run(
    self,
    config: CommandConfig,
    call_time_vars: dict[str, str] | None,
    trigger_event: str | None,
    trigger_chain: list[str] | None = None,
) -> tuple[ResolvedCommand, RunResult]:
    """
    Prepare resolved command and result container.
    
    Args:
        config: CommandConfig to prepare
        call_time_vars: Optional call-time variable overrides
        trigger_event: Optional immediate trigger event
        trigger_chain: Optional full trigger chain leading to this run
    
    Returns:
        Tuple of (ResolvedCommand, RunResult)
    """
    # ... existing variable resolution logic ...
    
    # Create result with trigger chain
    result = RunResult(
        command_name=config.name,
        trigger_event=trigger_event,
        trigger_chain=trigger_chain.copy() if trigger_chain else [],  # Copy to avoid mutations
        resolved_command=resolved,
    )
    
    return resolved, result
```

**Testing:**
- Call with no trigger_chain - should get empty list
- Call with trigger_chain - should copy it into RunResult
- Verify no mutations to passed chain

#### Step 2.3: Update `run_command()` - Manual execution

**Current call to `_prepare_run()`:**
```python
resolved, result = self._prepare_run(config, vars, trigger_event=None)
```

**New:**
```python
resolved, result = self._prepare_run(
    config, 
    vars, 
    trigger_event=None,
    trigger_chain=None  # Manual runs have no chain
)
```

**Testing:**
- Manual `run_command()` - should have empty trigger_chain

#### Step 2.4: Update `_trigger_run_command()` - Triggered execution

**Current call to `_prepare_run()`:**
```python
resolved, result = self._prepare_run(config, None, event_name)
```

**New:**
```python
resolved, result = self._prepare_run(
    config,
    None,
    trigger_event=event_name,
    trigger_chain=context.history.copy()  # Pass full chain from context
)
```

**Testing:**
- Triggered command should have full chain
- Chain should match context.history

---

### Phase 3: Auto-Trigger Propagation

#### Step 3.1: Update `_emit_auto_trigger()`

**Current:**
```python
async def _emit_auto_trigger(
    self,
    event_name: str,
    handle: RunHandle | None,
    context: TriggerContext | None = None,
) -> None:
    try:
        # Check loop_detection...
        await self.trigger(event_name, context)
    except TriggerCycleError as e:
        logger.debug(f"Cycle prevented for {event_name}: {e}")
    # ... error handling ...
```

**New:**
```python
async def _emit_auto_trigger(
    self,
    event_name: str,
    handle: RunHandle | None,
    context: TriggerContext | None = None,
) -> None:
    try:
        # If no context provided and we have a handle, inherit its chain
        if context is None and handle is not None:
            parent_chain = handle._result.trigger_chain
            context = TriggerContext(
                seen=set(parent_chain),       # Inherit cycle detection
                history=parent_chain.copy()   # Inherit breadcrumb
            )
        
        # Check loop_detection setting
        if handle is not None:
            command_name = handle.command_name
            if not self._trigger_engine.should_track_in_context(command_name):
                # loop_detection=False - don't propagate context
                context = None
        
        # Trigger with inherited/fresh context
        await self.trigger(event_name, context)
        
    except TriggerCycleError as e:
        logger.debug(f"Cycle prevented for {event_name}: {e}")
    except OrchestratorShutdownError:
        logger.debug(f"Auto-trigger {event_name} skipped (shutting down)")
    except Exception as e:
        logger.exception(f"Error in auto-trigger {event_name}: {e}")
```

**Key changes:**
1. Inherit parent's trigger chain when creating context
2. Copy chain to avoid mutations
3. Respect `loop_detection=False` setting

**Testing:**
- Auto-trigger inherits parent chain
- Chain grows with each auto-trigger
- loop_detection=False resets chain

---

### Phase 4: Public API Updates

#### Step 4.1: Add `trigger_chain` property to `RunHandle`

**In `run_handle.py`:**
```python
@property
def trigger_chain(self) -> list[str]:
    """
    Ordered list of trigger events that led to this run.
    
    Returns a copy to prevent external mutations.
    
    Examples:
      - [] = manually started via run_command()
      - ["user_saves"] = triggered directly by user_saves event
      - ["user_saves", "command_success:Lint"] = chained trigger
    
    Returns:
        Copy of the trigger chain
    """
    return self._result.trigger_chain.copy()
```

**Update `__repr__()`:**
```python
def __repr__(self) -> str:
    chain_display = " -> ".join(self.trigger_chain) if self.trigger_chain else "manual"
    return (
        f"RunHandle(command_name={self.command_name!r}, "
        f"run_id={self.run_id[:8]!r}, state={self.state.name}, "
        f"chain={chain_display!r})"
    )
```

**Testing:**
- Access `handle.trigger_chain` - should return copy
- Mutate returned list - should not affect internal state
- `__repr__()` should show chain

---

### Phase 5: Error Enhancement

#### Step 5.1: Update `TriggerCycleError` in `exceptions.py`

**Current:**
```python
class TriggerCycleError(CmdorcError):
    def __init__(self, event_name: str, cycle_path: list[str]):
        self.event_name = event_name
        self.cycle_path = cycle_path
        cycle_display = " -> ".join(cycle_path) + f" -> {event_name}"
        super().__init__(f"Trigger cycle detected: {cycle_display}")
```

**New (enhanced message):**
```python
class TriggerCycleError(CmdorcError):
    """Raised when a trigger cycle is detected.
    
    Attributes:
        event_name: The event that would create the cycle
        cycle_path: Ordered list of events leading to the cycle
        cycle_point: Index where the cycle begins (where event_name appears in cycle_path)
    """
    
    def __init__(self, event_name: str, cycle_path: list[str]):
        self.event_name = event_name
        self.cycle_path = cycle_path
        
        # Find where cycle begins
        try:
            self.cycle_point = cycle_path.index(event_name)
        except ValueError:
            self.cycle_point = None
        
        # Build detailed error message
        if self.cycle_point is not None:
            pre_cycle = cycle_path[:self.cycle_point]
            cycle = cycle_path[self.cycle_point:]
            
            msg_parts = []
            if pre_cycle:
                msg_parts.append(f"Trigger chain: {' -> '.join(pre_cycle)}")
            msg_parts.append(f"Cycle: {' -> '.join(cycle)} -> {event_name}")
            message = "\n".join(msg_parts)
        else:
            full_chain = " -> ".join(cycle_path) + f" -> {event_name}"
            message = f"Trigger cycle detected: {full_chain}"
        
        super().__init__(message)
```

**Testing:**
- Create error with cycle - message should show structure
- Access `cycle_point` - should be correct index
- Error without cycle in history - should handle gracefully

---

### Phase 6: Testing

#### Step 6.1: Unit Tests - `tests/test_trigger_chain.py` (new file)

```python
"""Tests for trigger chain (breadcrumb) functionality."""

import pytest
from cmdorc import (
    CommandConfig,
    CommandOrchestrator,
    RunnerConfig,
    TriggerCycleError,
)
from cmdorc.mock_executor import MockExecutor
from cmdorc.types import TriggerContext


@pytest.fixture
def orchestrator_with_chain():
    """Orchestrator with commands that chain via triggers."""
    commands = [
        CommandConfig(
            name="Step1",
            command="echo step1",
            triggers=["start"],
        ),
        CommandConfig(
            name="Step2",
            command="echo step2",
            triggers=["command_success:Step1"],
        ),
        CommandConfig(
            name="Step3",
            command="echo step3",
            triggers=["command_success:Step2"],
        ),
    ]
    
    config = RunnerConfig(commands=commands)
    executor = MockExecutor(delay=0.01)  # Fast simulation
    return CommandOrchestrator(config, executor=executor)


class TestTriggerChainBasics:
    """Test basic trigger chain functionality."""
    
    async def test_manual_run_has_empty_chain(self, orchestrator_with_chain):
        """Manual run_command should have empty trigger_chain."""
        handle = await orchestrator_with_chain.run_command("Step1")
        await handle.wait()
        
        assert handle.trigger_chain == []
        assert handle._result.trigger_event is None
    
    async def test_direct_trigger_has_single_event(self, orchestrator_with_chain):
        """Direct trigger should have single-element chain."""
        await orchestrator_with_chain.trigger("start")
        
        # Wait for Step1 to complete
        import asyncio
        await asyncio.sleep(0.05)
        
        # Get Step1's last run
        history = orchestrator_with_chain.get_history("Step1", limit=1)
        assert len(history) == 1
        result = history[0]
        
        assert result.trigger_chain == ["start"]
        assert result.trigger_event == "start"
    
    async def test_chained_triggers_accumulate(self, orchestrator_with_chain):
        """Chained triggers should accumulate in history."""
        await orchestrator_with_chain.trigger("start")
        
        # Wait for chain to complete
        import asyncio
        await asyncio.sleep(0.15)
        
        # Check each step's chain
        step1_history = orchestrator_with_chain.get_history("Step1", limit=1)
        assert step1_history[0].trigger_chain == ["start"]
        
        step2_history = orchestrator_with_chain.get_history("Step2", limit=1)
        assert step2_history[0].trigger_chain == ["start", "command_success:Step1"]
        
        step3_history = orchestrator_with_chain.get_history("Step3", limit=1)
        expected = ["start", "command_success:Step1", "command_success:Step2"]
        assert step3_history[0].trigger_chain == expected


class TestTriggerContext:
    """Test TriggerContext behavior."""
    
    def test_empty_context_creation(self):
        """Empty context should have empty seen and history."""
        context = TriggerContext()
        assert context.seen == set()
        assert context.history == []
    
    def test_context_with_data(self):
        """Context can be created with data."""
        context = TriggerContext(
            seen={"a", "b"},
            history=["a", "b"]
        )
        assert context.seen == {"a", "b"}
        assert context.history == ["a", "b"]
    
    def test_history_is_mutable(self):
        """History can be extended (for propagation)."""
        context = TriggerContext(history=["a"])
        context.history.append("b")
        assert context.history == ["a", "b"]


class TestCycleDetectionWithChains:
    """Test cycle detection includes chain info."""
    
    async def test_cycle_error_includes_path(self):
        """TriggerCycleError should include full path."""
        commands = [
            CommandConfig(
                name="A",
                command="echo a",
                triggers=["start"],
            ),
            CommandConfig(
                name="B",
                command="echo b",
                triggers=["command_success:A"],
            ),
            CommandConfig(
                name="C",
                command="echo c",
                triggers=["command_success:B", "start"],  # Creates cycle
            ),
        ]
        
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)
        
        # This should detect cycle
        with pytest.raises(TriggerCycleError) as exc_info:
            await orchestrator.trigger("start")
            import asyncio
            await asyncio.sleep(0.1)
        
        error = exc_info.value
        assert error.event_name == "start"
        assert "start" in error.cycle_path
    
    async def test_loop_detection_false_bypasses_cycle(self):
        """loop_detection=False should allow cycles."""
        commands = [
            CommandConfig(
                name="Infinite",
                command="echo loop",
                triggers=["command_success:Infinite"],
                loop_detection=False,  # Allow self-trigger
                max_concurrent=1,
                on_retrigger="ignore",  # Prevent pile-up
            ),
        ]
        
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)
        
        # Start the loop
        handle = await orchestrator.run_command("Infinite")
        
        # Let it run a bit
        import asyncio
        await asyncio.sleep(0.05)
        
        # Should have multiple runs started (not crashed)
        # Cancel to stop
        await orchestrator.cancel_command("Infinite")
```

#### Step 6.2: Integration Tests - Update `tests/test_command_orchestrator.py`

Add tests in existing file:

```python
class TestTriggerChainIntegration:
    """Integration tests for trigger chains in orchestrator."""
    
    async def test_run_handle_exposes_chain(self):
        """RunHandle should expose trigger_chain property."""
        commands = [
            CommandConfig(name="Test", command="echo test", triggers=["go"]),
        ]
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)
        
        # Trigger it
        await orchestrator.trigger("go")
        await asyncio.sleep(0.05)
        
        # Get handle via history
        history = orchestrator.get_history("Test", limit=1)
        result = history[0]
        
        assert result.trigger_chain == ["go"]
    
    async def test_chain_persists_in_history(self):
        """Trigger chain should persist in history."""
        commands = [
            CommandConfig(name="Cmd", command="echo cmd", triggers=["event"]),
        ]
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)
        
        # Run multiple times with different triggers
        await orchestrator.trigger("event")
        await asyncio.sleep(0.05)
        
        handle = await orchestrator.run_command("Cmd")
        await handle.wait()
        
        # Check history
        history = orchestrator.get_history("Cmd", limit=10)
        assert len(history) == 2
        
        # First should have chain
        assert history[0].trigger_chain == ["event"]
        
        # Second should be empty (manual)
        assert history[1].trigger_chain == []
```

#### Step 6.3: Update Existing Tests

Search for any tests that create `TriggerContext` or check cycle errors:

```bash
grep -r "TriggerContext" tests/
grep -r "TriggerCycleError" tests/
```

Update them to include `history=[]` if needed.

---

### Phase 7: Documentation

#### Step 7.1: Update `README.md`

Add section under "Core Concepts":

```markdown
### Trigger Chains (Breadcrumbs)

Every run tracks the sequence of triggers that led to its execution:

```python
# Manual run
handle = await orchestrator.run_command("Tests")
print(handle.trigger_chain)  # []

# Triggered run
await orchestrator.trigger("user_saves")  # â†' Lint â†' Tests
handle = orchestrator.get_active_handles("Tests")[0]
print(handle.trigger_chain)  
# ["user_saves", "command_success:Lint", "command_started:Tests"]
```

**Use cases:**
- **Debugging:** "Why did this command run?"
- **UI Display:** Show breadcrumb trail in status bar
- **Cycle Errors:** See the full path that caused the cycle

**Access via:**
- `RunHandle.trigger_chain` - Live runs
- `RunResult.trigger_chain` - Historical runs (via `get_history()`)
```

#### Step 7.2: Update `architecture.md`

**Section 7: Trigger System**

Add under "TriggerContext & Cycle Prevention":

```markdown
### Trigger Chain Tracking (Breadcrumbs)

`TriggerContext` maintains both cycle detection and breadcrumb tracking:

```python
@dataclass
class TriggerContext:
    seen: set[str]      # O(1) cycle detection
    history: list[str]  # Ordered breadcrumb trail
```

**Design rationale:**
- `seen` enables fast cycle detection (O(1) membership test)
- `history` provides ordered path for debugging and UI display
- Both track the same events, optimized for different use cases

**Propagation:**
1. Root trigger creates fresh context: `TriggerContext(seen=set(), history=[])`
2. Each trigger adds to both: `seen.add(event)`, `history.append(event)`
3. Auto-triggers inherit parent context and extend it
4. RunResult stores frozen snapshot: `trigger_chain = context.history.copy()`

**Example flow:**
```
user_saves                          â†' context.history = ["user_saves"]
  â†' command_success:Lint            â†' context.history = ["user_saves", "command_success:Lint"]
    â†' command_started:Tests         â†' context.history = ["user_saves", "command_success:Lint", "command_started:Tests"]
      â†' Tests RunResult.trigger_chain = ["user_saves", "command_success:Lint", "command_started:Tests"]
```
```

**Section 10: Data Containers**

Update `RunResult` documentation:

```markdown
### RunResult (mutable)

```python
@dataclass
class RunResult:
    # ... existing fields ...
    
    trigger_event: str | None
    """Immediate trigger event (last in chain, for backward compatibility)."""
    
    trigger_chain: list[str]
    """Ordered list of trigger events leading to this run.
    
    Examples:
      - [] = manually started via run_command()
      - ["user_saves"] = triggered directly by user_saves event
      - ["user_saves", "command_success:Lint"] = chained trigger
    
    The last element matches trigger_event (if trigger_event is not None).
    Immutable after finalization (treat as read-only).
    """
```
```

#### Step 7.3: Add Example - `examples/advanced/04_trigger_chains.py`

```python
"""
Example: Trigger Chain (Breadcrumb) Tracking

Demonstrates how to access and display the chain of triggers
that led to a command's execution.
"""

import asyncio
from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig
from cmdorc.mock_executor import MockExecutor


async def main():
    # Create a workflow: Save â†' Lint â†' Test â†' Deploy
    commands = [
        CommandConfig(
            name="Lint",
            command="echo 'Linting...'",
            triggers=["file_saved"],
        ),
        CommandConfig(
            name="Test",
            command="echo 'Testing...'",
            triggers=["command_success:Lint"],
        ),
        CommandConfig(
            name="Deploy",
            command="echo 'Deploying...'",
            triggers=["command_success:Test"],
        ),
    ]
    
    config = RunnerConfig(commands=commands)
    executor = MockExecutor(delay=0.1)  # Simulate 100ms per command
    orchestrator = CommandOrchestrator(config, executor=executor)
    
    # Set up callback to print chains
    def on_start(handle, context):
        chain = handle.trigger_chain
        if chain:
            chain_str = " â†' ".join(chain)
            print(f"  {handle.command_name} triggered by: {chain_str}")
        else:
            print(f"  {handle.command_name} started manually")
    
    orchestrator.on_event("command_started:*", on_start)
    
    print("=== Manual Run (No Chain) ===")
    handle = await orchestrator.run_command("Lint")
    await handle.wait()
    print(f"Chain: {handle.trigger_chain}\n")
    
    print("=== Triggered Workflow ===")
    await orchestrator.trigger("file_saved")
    await asyncio.sleep(0.5)  # Let chain complete
    
    print("\n=== History Inspection ===")
    for cmd_name in ["Lint", "Test", "Deploy"]:
        history = orchestrator.get_history(cmd_name, limit=1)
        if history:
            result = history[0]
            chain_str = " â†' ".join(result.trigger_chain) if result.trigger_chain else "manual"
            print(f"{cmd_name}: {chain_str}")
    
    await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
```

**Expected output:**
```
=== Manual Run (No Chain) ===
  Lint started manually
Chain: []

=== Triggered Workflow ===
  Lint triggered by: file_saved
  Test triggered by: file_saved â†' command_success:Lint
  Deploy triggered by: file_saved â†' command_success:Lint â†' command_success:Test

=== History Inspection ===
Lint: file_saved
Test: file_saved â†' command_success:Lint
Deploy: file_saved â†' command_success:Lint â†' command_success:Test
```

---

### Phase 8: Validation & Polish

#### Step 8.1: Run Full Test Suite
```bash
pdm run pytest -v
pdm run pytest --cov=cmdorc --cov-report=html
```

**Target:** Maintain 94%+ coverage

#### Step 8.2: Type Checking
```bash
pdm run mypy src/cmdorc
```

**Fix any type errors** from new `trigger_chain` field.

#### Step 8.3: Linting
```bash
pdm run ruff check . && pdm run ruff format .
```

#### Step 8.4: Manual Testing

Run all examples:
```bash
python examples/basic/01_hello_world.py
python examples/basic/02_simple_workflow.py
python examples/advanced/04_trigger_chains.py  # New example
```

Verify chains are logged correctly.

---

## Summary Checklist

- [ ] **Phase 1:** Data models updated (TriggerContext, RunResult)
- [ ] **Phase 2:** Context propagation in trigger()
- [ ] **Phase 3:** Auto-trigger propagation via _emit_auto_trigger()
- [ ] **Phase 4:** RunHandle.trigger_chain property
- [ ] **Phase 5:** Enhanced TriggerCycleError messages
- [ ] **Phase 6:** All tests passing (new + updated)
- [ ] **Phase 7:** Documentation updated (README, architecture, examples)
- [ ] **Phase 8:** Full validation (coverage, types, lint, manual)