# command_config.md — Command Runner Configuration Reference (v1)

This document is the single source of truth for how individual commands are configured in `config.toml`.

```toml
[[command]]
name = "Tests"
triggers = ["changes_applied", "Tests"]          # required — explicit self-trigger for manual runs
cancel_on_triggers = ["changes_applied", "prompt_send"]
command = "pytest {{ tests_directory }}"
max_concurrent = 1                               # default: 1, use 0 for unlimited
timeout_secs = 600                               # optional — kill after N seconds
on_retrigger = "cancel_and_restart"             # default, or "ignore"
```

## Fields

| Field                 | Type             | Required? | Default                  | Meaning |
|-----------------------|------------------|-----------|--------------------------|---------------------------------------------------------------|
| `name`                | `str`            | Yes       | —                        | Unique name of the command. Used in triggers and UI. |
| `command`             | `str`            | Yes       | —                        | Shell command to execute. Supports `{{ base_directory }}` and any custom template vars passed by the host. |
| `triggers`            | `list[str]`      | Yes       | —                        | Exact strings that cause this command to run when `runner.trigger(...)` is called. Must explicitly include its own `name` if you want manual/hotkey execution. |
| `cancel_on_triggers`  | `list[str]`      | No        | `[]`                     | If any of these strings are triggered while the command is running → cancel it immediately. |
| `max_concurrent`      | `int`            | No        | `1`                      | Maximum number of concurrent instances. `0` = unlimited. |
| `timeout_secs`        | `int`            | No        | none                     | If set, automatically kill the process after this many seconds. |
| `on_retrigger`        | `str`            | No        | `"cancel_and_restart"`   | Behaviour when the command is triggered again while already running and `max_concurrent` is reached:<br>• `"cancel_and_restart"` → cancel existing run(s) and start fresh (default)<br>• `"ignore"` → silently skip the new request |

## Interaction Matrix (when a trigger arrives)

| max_concurrent | on_retrigger          | Command already running? | Result on new trigger |
|----------------|-----------------------|---------------------------|-----------------------|
| `1`            | `cancel_and_restart`  | Yes                       | Cancel old → start new |
| `1`            | `ignore`              | Yes                       | Do nothing (skip)     |
| `>1` or `0`    | any                   | Yes                       | Start another instance (parallel) |

## Automatic Events (emitted on completion)

| Event                        | When it fires                                 |
|------------------------------|-----------------------------------------------|
| `command_success:<name>`     | Process exits with code 0 (or custom success) |
| `command_failed:<name>`      | Process exits non-zero                        |
| `command_finished:<name>`    | Process completed (success or failure)       |
| `command_cancelled:<name>`   | Process was cancelled (manual or via `cancel_on_triggers`) |

## Examples

```toml
# Standard interactive test command (VibeDir default style)
[[command]]
name = "Tests"
triggers = ["changes_applied", "Tests"]
cancel_on_triggers = ["prompt_send"]
command = "pytest {{ tests_directory }}"
timeout_secs = 600
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
```

## Design Notes

- No implicit runs — a command is only executed if its name (or any other string) is explicitly listed in `triggers`.
- No `manual` magic string — manual execution is just `runner.trigger("CommandName")` after adding the name to its own `triggers`.
