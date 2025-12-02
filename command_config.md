# command_config.md — Command Runner Configuration Reference (v1)

This document is the single source of truth for how individual commands are configured in `config.toml`.

```toml
[variables]  # Global template vars (optional section)
tests_directory = "{{ base_directory }}/tests"  # Nested ok 
base_directory = "."  # But usually overridden by host

[[command]]
name = "Tests"
triggers = ["changes_applied", "Tests"]          # required — explicit self-trigger for manual runs
cancel_on_triggers = ["changes_applied", "prompt_send"]
command = "pytest {{ tests_directory }}"         # tests_directory must be defined in variables or added at runtime
max_concurrent = 1                               # default: 1, use 0 for unlimited
timeout_secs = 600                               # optional — kill after N seconds
on_retrigger = "cancel_and_restart"             # default, or "ignore"
keep_history = 1                                 # default: 1, how many past runs to keep
```

## Fields

| Field                 | Type             | Required? | Default                  | Meaning |
|-----------------------|------------------|-----------|--------------------------|---------------------------------------------------------------|
| `name`                | `str`            | Yes       | —                        | Unique name of the command. Used in triggers and UI. |
| `command`             | `str`            | Yes       | —                        | Shell command to execute. Supports `{{ base_directory }}` and any custom template vars passed by the host. |
| `triggers`            | `list[str]`      | Yes       | —                        | Exact strings that cause this command to run when `runner.trigger(...)` is called. Must explicitly include its own `name` if you want manual/hotkey execution. |
| `cancel_on_triggers`  | `list[str]`      | No        | `[]`                     | If any of these strings are triggered while the command is running → cancel it immediately. |
| `max_concurrent`      | `int`            | No        | `1`                      | Maximum number of concurrent instances. `0` = unlimited. |
| `timeout_secs`        | `int`            | No        | `None`                   | If set, automatically kill the process after this many seconds. |
| `on_retrigger`        | `str`            | No        | `"cancel_and_restart"`   | Behaviour when the command is triggered again while already running and `max_concurrent` is reached:<br>• `"cancel_and_restart"` → cancel existing run(s) and start fresh (default)<br>• `"ignore"` → silently skip the new request |
| `keep_history`        | `int`            | No        | `1`                      | Number of past RunResult objects to keep. `0` = keep none (only latest via `get_result()`), `N` = keep last N runs. |

## Interaction Matrix (when a trigger arrives)

| max_concurrent | on_retrigger          | Command already running? | Result on new trigger |
|----------------|-----------------------|---------------------------|-----------------------|
| `1`            | `cancel_and_restart`  | Yes                       | Cancel old → start new |
| `1`            | `ignore`              | Yes                       | Do nothing (skip)     |
| `>1` or `0`    | any                   | Yes                       | Start another instance (parallel) |

## Automatic Events (emitted on completion)

These events are emitted automatically by the runner — no configuration needed.

| Event                        | When it fires                                 |
|------------------------------|-----------------------------------------------|
| `command_started:<name>`     | After command passes concurrency checks and begins execution |
| `command_success:<name>`     | Process exits with code 0 (success) |
| `command_failed:<name>`      | Process exits non-zero (failure) |
| `command_finished:<name>`    | Process completed successfully or failed (not cancelled) |
| `command_cancelled:<name>`   | Process was cancelled (manual or via `cancel_on_triggers`) |

**Note**: `command_finished` is only emitted for success/failure states, not for cancelled commands.

## Examples

```toml
# Standard interactive test command (VibeDir default style)
[[command]]
name = "Tests"
triggers = ["changes_applied", "Tests"]
cancel_on_triggers = ["prompt_send"]
command = "pytest {{ tests_directory }}"
timeout_secs = 600
keep_history = 5
# max_concurrent and on_retrigger use defaults (1 + cancel_and_restart)

# Expensive background check you don't want to spam
[[command]]
name = "FullAudit"
triggers = ["nightly"]
command = "python audit.py"
max_concurrent = 1
on_retrigger = "ignore"          # if already running, just skip

# Fire-and-forget logger (allow many in parallel)
[[command]]
name = "LogEvent"
triggers = ["webhook:deploy"]
command = "curl -X POST https://logs.example.com/..."
max_concurrent = 0               # unlimited parallelism

# React to command lifecycle events
[[command]]
name = "Notify"
triggers = ["command_started:Tests"]
command = "notify-send 'Tests started'"

[[command]]
name = "Cleanup"
triggers = ["command_finished:Tests"]
command = "rm -rf /tmp/test_artifacts"
```

## Design Notes

- No implicit runs — a command is only executed if its name (or any other string) is explicitly listed in `triggers`.
- No `manual` magic string — manual execution is just `runner.trigger("CommandName")` after adding the name to its own `triggers`.
- `keep_history` controls retention: `0` means no history (only latest result accessible), higher values retain more runs for debugging/analysis.