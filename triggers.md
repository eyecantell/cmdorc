# Triggers — Command Orchestration Design (v1)

## Core Principle
Every string passed to `runner.trigger(...)` means:  
**"Run every command whose `triggers` list contains this exact string."**

Triggers not only run commands but also fire registered callbacks—use `on_trigger()` for host reactivity.

That's it. No magic. No exceptions. No implicit runs based on command names—everything must be explicitly listed in `triggers` for clarity and safety.

## Public API

```python
runner.trigger(event_name: str)      # fire an event → run matching commands
runner.cancel_command(name: str)     # cancel a running instance
runner.cancel_all()                  # cancel everything

runner.get_commands_by_trigger("pre_commit") # → returns list of Command objects that have the given trigger
runner.has_trigger("pre_commit") # → True if at least one command has the given trigger
```

There is no separate `run_command()` method. Use `runner.trigger("CommandName")` for manual runs (after adding `"CommandName"` to its `triggers`).

```toml
[[command]]
name = "Tests"
triggers = ["changes_applied", "pre_commit", "Tests"]  # explicit self for manual runs
cancel_on_triggers = ["changes_applied", "prompt_send"]
command = "pytest {{ tests_directory }}"

[[command]]
name = "Lint"
triggers = ["changes_applied", "pre_commit"]
command = "ruff check {{ base_directory }}"
```

### Meaning of each section

| Field                | Type          | Meaning                                                                                   |
|----------------------|---------------|-------------------------------------------------------------------------------------------|
| `triggers`           | `list[str]`   | Run this command when any of these exact strings are passed to `runner.trigger(...)`      |
| `cancel_on_triggers` | `list[str]`   | If the command is running and any of these strings are triggered → cancel it immediately |

## Automatic Events (emitted by the runner — no config needed)

These events are fired automatically by CommandRunner as commands progress through their lifecycle. All auto-events propagate cycle detection context to prevent infinite loops.

| Event Name                     | When it fires                             | Example Use                                    |
|--------------------------------|-------------------------------------------|------------------------------------------------|
| `command_started:<name>`       | After command passes concurrency checks and begins execution | Show UI spinner, track metrics, cancel conflicting tasks |
| `command_success:<name>`       | After command `<name>` finishes successfully | `triggers = ["command_success:Lint"]` — chain next step |
| `command_failed:<name>`        | After command `<name>` finishes with failure  | `triggers = ["command_failed:Format"]` — show error notification |
| `command_finished:<name>`      | After command `<name>` finishes (success **or** failure, not cancelled) | Clean up resources regardless of outcome |
| `command_cancelled:<name>`     | After command `<name>` is cancelled       | `triggers = ["command_cancelled:Tests"]` — update UI |

**Important**: 
- `command_finished` is **only** emitted for success and failure states, not for cancelled commands
- `command_started` fires after concurrency/retrigger policy decisions but before subprocess spawns
- All auto-events include cycle detection to prevent infinite trigger loops

## Common Trigger Patterns (examples)

```toml
# Manual execution
triggers = ["Tests"]                      # runner.trigger("Tests") runs this command

# Batch execution
triggers = ["pre_commit"]                 # multiple commands share this string → one trigger runs all

# Workflow steps
triggers = ["changes_received"]           # right after applydir.json appears
triggers = ["changes_applied"]            # after successful patching
triggers = ["prompt_send"]                # right before copying/sending prompt to LLM

# Chaining off automatic events
triggers = ["command_finished:Lint"]      # run after Lint completes (success or failure)
triggers = ["command_success:Tests"]      # run only if Tests succeeds

# React to command lifecycle
triggers = ["command_started:Build"]      # show spinner when build starts
cancel_on_triggers = ["command_started:Tests"]  # cancel this if Tests starts
```

## Triggering Commands

- `runner.trigger("any_string")` → runs **every** command that lists `"any_string"` in its `triggers` (exact match only).
- To run a command manually: Add its name to its own `triggers`, then `runner.trigger("CommandName")`.
- No implicit runs—everything must be explicitly listed for clarity and safety.

## Cancellation

- **Explicit**: `runner.cancel_command("Tests")` or `runner.cancel_all()`.
- **Automatic**: If a command is running and a string in its `cancel_on_triggers` is fired via `trigger(...)`, cancel it.
- On cancel, emit `command_cancelled:<name>` (but **not** `command_finished:<name>`—cancels are separate from success/failure).

## Lifecycle Flow Example

When you trigger a command, here's the event sequence:

```python
await runner.trigger("changes_applied")  # User trigger

# If "Tests" command has this trigger:
# 1. Concurrency check (cancel old runs if needed)
# 2. 🔥 command_started:Tests
# 3. Subprocess executes
# 4a. Success path:
#     🔥 command_success:Tests
#     🔥 command_finished:Tests
# 4b. Failure path:
#     🔥 command_failed:Tests
#     🔥 command_finished:Tests
# 4c. Cancelled path:
#     🔥 command_cancelled:Tests
#     (NO command_finished)
```

## Example Uses

- **File/directory watching** → Implement in your host app (e.g., with watchdog), then `runner.trigger("file_modified:src/")`.
- **Timers** → Use a loop/timer in host: `runner.trigger("timer:30s")`.
- **Webhooks** → Host receives webhook → `runner.trigger("webhook:ci_passed")`.
- **Git events** → Poll or hook → `runner.trigger("git_head_moved")`.

All just strings. All just work. The library doesn't build these in. Users fire them as needed.

## Cycle Detection

cmdorc automatically detects and prevents infinite trigger loops:

```toml
[[command]]
name = "A"
triggers = ["start", "command_success:B"]
command = "echo A"

[[command]]
name = "B"
triggers = ["command_success:A"]
command = "echo B"
```

The first time through works: `start → A → B`. But when B finishes, it would trigger A again, creating a cycle. cmdorc detects this and logs a warning instead of running infinitely.

## Summary

- `runner.trigger("anything")` → run commands that list `"anything"` in `triggers`.
- **Automatic events**: `command_started:Name`, `command_success:Name`, `command_failed:Name`, `command_finished:Name`, `command_cancelled:Name`.
- Cancellation via `cancel_on_triggers` or explicit methods.
- Explicit self-triggers for manual runs (e.g., add `"Tests"` to Tests' triggers).
- Built-in cycle detection prevents infinite loops.

Zero magic. Infinite flexibility.