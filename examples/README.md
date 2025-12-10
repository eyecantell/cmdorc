# cmdorc Examples

Complete examples showcasing cmdorc features and use cases. Start with basic examples and progress to advanced patterns.

## Quick Start

```bash
# Run the simplest example
python examples/basic/01_hello_world.py

# Run a workflow example
python examples/basic/02_simple_workflow.py
```

## Examples by Level

### 🌟 Basic (Beginner - start here)

Perfect for learning core concepts.

| Example | Features | Time |
|---------|----------|------|
| **01_hello_world.py** | Single command execution, `run_command()`, `wait()` | 2 min |
| **02_simple_workflow.py** | Command chaining, lifecycle triggers, fire-and-forget | 3 min |
| **03_toml_config/** | TOML configuration, `load_config()`, workflow definition | 3 min |
| **04_runtime_variables.py** | Variable resolution, templates, runtime overrides | 3 min |
| **05_status_and_history.py** | Status tracking, command history, RunHandle properties | 3 min |

**Learning Path:**
1. Start with `01_hello_world.py` to understand basic execution
2. Move to `02_simple_workflow.py` to see chaining
3. Try `03_toml_config/` to understand TOML-based configuration
4. Study `04_runtime_variables.py` to master variable resolution
5. Review `05_status_and_history.py` to track command state

### 🎯 Developer Workflows (Intermediate - real-world scenarios)

Practical examples for development automation.

| Example | Scenario | Key Features |
|---------|----------|--------------|
| **ci_pipeline/** | Complete CI/CD pipeline | Chaining, error handling, result collection |
| **python_project/** | Python dev environment | CLI interface, concurrency policies, callbacks |
| **git_hooks.py** | Git workflow automation | Lifecycle triggers, cancellation, status tracking |

**Use Cases:**
- `ci_pipeline/` - See a complete lint→test→build→deploy workflow
- `python_project/` - Automate your Python development tasks
- `git_hooks.py` - Integrate with git workflows

### 📁 File Watching (Intermediate - reactive execution)

Watch files and trigger commands automatically.

| Example | Feature | Requirement |
|---------|---------|-------------|
| **simple_watcher.py** | Basic file watching | watchdog |
| **auto_tester/** | Auto-run tests on changes | watchdog |
| **hot_reload.py** | Dev server restart | watchdog |

**Prerequisites:**
```bash
pip install watchdog
```

**Running:**
```bash
# Watch and trigger linting on file changes
python examples/file_watching/simple_watcher.py

# Auto-test on Python file changes
python examples/file_watching/auto_tester/watcher.py

# Hot reload development server
python examples/file_watching/hot_reload.py
```

### 🎨 TUI Integration (Advanced - interactive UIs)

Build interactive terminal user interfaces with cmdorc.

| Example | Feature | Requirements |
|---------|---------|--------------|
| **simple_tui.py** | Basic TUI with buttons | textual, rich |
| **command_palette.py** | Command palette UI | textual, rich |
| **status_dashboard.py** | Live status dashboard | textual, rich |

**Prerequisites:**
```bash
pip install textual rich
```

### 🚀 Advanced (Expert - deep dive)

Advanced patterns and customization.

| Example | Topic | Concepts |
|---------|-------|----------|
| **01_callbacks_and_hooks.py** | Event callbacks | `on_event()`, `set_lifecycle_callback()`, wildcards |
| **02_error_handling.py** | Error handling | Catching exceptions, graceful degradation |
| **03_concurrency_policies.py** | Concurrency control | `max_concurrent`, `on_retrigger`, `debounce_in_ms` |
| **04_custom_executor.py** | Custom executors | Implementing CommandExecutor ABC |
| **05_cycle_detection.py** | Loop prevention | Cycle detection, TriggerContext |

## Features Covered

- ✅ **Basic Execution**: `run_command()`, `trigger()`, `wait()`
- ✅ **Configuration**: Programmatic and TOML-based
- ✅ **Triggers**: Lifecycle events, chaining, exact/wildcard matching
- ✅ **Variables**: Resolution, templating, runtime overrides
- ✅ **Callbacks**: Event patterns, lifecycle hooks
- ✅ **State Tracking**: Status, history, active handles
- ✅ **File Watching**: Reactive execution with watchdog
- ✅ **Concurrency**: Limits, policies, debouncing
- ✅ **Error Handling**: Exception catching, graceful degradation
- ✅ **UI Integration**: TUI with Textual

## Installation & Dependencies

### Core (included with cmdorc)
```bash
pip install cmdorc
```

### File Watching Examples
```bash
pip install watchdog
```

### TUI Examples
```bash
pip install textual rich
```

### All Examples
```bash
pip install cmdorc watchdog textual rich
```

Or install with optional dependencies:
```bash
pip install cmdorc[examples]
```

## Running Examples

### Individual Files
```bash
python examples/basic/01_hello_world.py
python examples/advanced/02_error_handling.py
```

### Directories (with config files)
```bash
cd examples/basic/03_toml_config
python run.py
```

## Example Output

### 01_hello_world.py
```
Starting command...
Command completed with state: SUCCESS
Success: True
Output: Hello from cmdorc!
```

### 02_simple_workflow.py
```
Starting workflow...
Waiting for workflow to complete...

Workflow Results:
  Lint: success
  Test: success
```

### File Watching
```
🔍 Watching /path/to/examples/file_watching for changes...
   (Modify .py files to trigger linting)
   Press Ctrl+C to stop

📝 watcher.py changed
  → RunTests started
  ✓ Tests passed (0.45s)
```

## Common Patterns

### Fire-and-Forget Execution
```python
await orchestrator.trigger("build")  # Returns immediately
# Do other work while commands run in background
```

### Wait for Completion
```python
handle = await orchestrator.run_command("Test")
await handle.wait(timeout=10.0)
print(f"Result: {handle.state}")
```

### Batch Execution
```python
handles = [
    await orchestrator.run_command("Lint"),
    await orchestrator.run_command("Test"),
]
await asyncio.gather(*[h.wait() for h in handles])
```

### Error Recovery
```python
try:
    handle = await orchestrator.run_command("Build")
    await handle.wait()
except ConcurrencyLimitError:
    print("Build already running")
except DebounceError as e:
    print(f"Too soon - wait {e.elapsed_ms}ms")
```

## Learning Resources

1. **README.md** - Main documentation
2. **architecture.md** - Detailed design
3. **triggers.md** - Trigger system philosophy
4. **CLAUDE.md** - Developer notes

## Tips & Best Practices

### For Learning
- Start with `basic/` examples
- Run examples locally to see real output
- Modify examples to experiment

### For Production
- Use TOML configuration for reproducibility
- Set appropriate `timeout_secs` for long tasks
- Use `debounce_in_ms` to prevent command spam
- Implement proper error handling
- Test with `MockExecutor` before running real commands

### Performance
- Set `max_concurrent` based on system resources
- Use `cancel_and_restart` for quick iteration
- Monitor active handles with `get_all_active_handles()`

## Troubleshooting

### "No module named 'watchdog'"
```bash
pip install watchdog
```

### "No module named 'textual'"
```bash
pip install textual rich
```

### Commands not triggering
- Check trigger strings match exactly (case-sensitive)
- Verify command `triggers` list includes the event
- Use `get_status()` to check command state

### Too many concurrent runs
- Set `max_concurrent` value
- Use `on_retrigger="ignore"` to skip if running
- Add `debounce_in_ms` delay between runs

## Contributing

Found an issue or want to add an example? Check the main repository for contribution guidelines.

---

**Happy orchestrating! 🚀**
