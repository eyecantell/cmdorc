# cmdorc: Command Orchestrator - Not yet ready, but "COMING SOON"

[![PyPI version](https://badge.fury.io/py/cmdorc.svg)](https://badge.fury.io/py/cmdorc)  
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)

**cmdorc** (short for "command orchestrator") is a lightweight, async-first Python library for configuring and running shell commands based on string-based triggers. It's designed as a backend for tools like developer TUIs (e.g., VibeDir), CI workflows, or any app needing event-driven command execution. No external dependencies beyond Python stdlib—pure, simple, and extensible.

Inspired by task runners like Make or npm scripts, but with a focus on triggers for orchestration: load a TOML config, fire events, and let the library handle async runs, state tracking, and cancellations.

## Features

- **Trigger-Based Execution**: Run commands on arbitrary string events (e.g., `runner.trigger("changes_applied")`).
- **Automatic Events**: Built-in emissions like `command_success:<name>` for easy chaining.
- **Async & Non-Blocking**: Uses `asyncio` for concurrent runs without blocking your app.
- **Configurable Policies**: Per-command settings for concurrency (`max_concurrent`), timeouts (`timeout_secs`), retrigger behavior (`on_retrigger`), and auto-cancels (`cancel_on_triggers`).
- **State & Result Tracking**: Query status (`idle`, `running`, etc.) and results (output, success) in memory.
- **Introspection**: Methods like `get_commands_by_trigger()` for building dynamic UIs.
- **TOML Config**: Simple, declarative setup with validation via pydantic.
- **Frontend-Agnostic**: Perfect for TUIs (e.g., Textual), VSCode extensions, or scripts—expose state for your frontend to render (e.g., status icons ✅/❌/⏳).
- **Zero Magic**: No implicit behaviors—everything explicit for predictability.

## Installation

```bash
pip install cmdorc
```

(Coming soon to PyPI—currently in development.)

## Quick Start

1. Create a `config.toml`:

```toml
[status_icons]  # Global overrides (optional)
success = "✅"
failed = "❌"

[[command]]
name = "Lint"
triggers = ["changes_applied", "Lint"]  # Explicit self-trigger for manual runs
cancel_on_triggers = ["prompt_send"]
command = "ruff check {{ base_directory }}"
max_concurrent = 1
on_retrigger = "cancel_and_restart"
timeout_secs = 300

[[command]]
name = "Tests"
triggers = ["command_success:Lint", "Tests"]
command = "pytest {{ tests_directory }}"
```

2. Use in your Python app:

```python
import asyncio
from cmdorc import CommandRunner, load_config

async def main():
    config = load_config("config.toml")
    runner = CommandRunner(config)
    
    # Simulate a workflow event
    await runner.trigger("changes_applied")  # Runs Lint → auto-triggers Tests on success
    
    # Check status
    print(runner.get_status("Lint"))  # e.g., "running"
    
    # Manual run
    await runner.trigger("Tests")
    
    # Cancel if needed
    runner.cancel_command("Tests")
    
    # Get results
    result = runner.get_result("Tests")
    print(result["output"])  # Captured stdout/stderr

asyncio.run(main())
```

## Documentation

- **[triggers.md](triggers.md)**: Full details on the trigger system, automatic events, and querying.
- **[command_config.md](command_config.md)**: Reference for per-command TOML fields and policies.
- **API Reference**: (Coming soon—pydoc for core classes like `CommandRunner`, `CommandConfig`.)
- **Examples**: See `examples/` for VibeDir integration, simple CLI wrapper, and async script demos.

## Plans & Roadmap

cmdorc is in early development (as of November 2025). Current focus:

- **MVP (v0.1)**: Core trigger system, async execution, state/results tracking, cancellation, TOML loading with pydantic validation.
- **v0.2**: Add history retention (`keep_history = N`), optional `result_file` persistence, and basic logging.
- **v0.3**: Hooks for extensions (e.g., custom success evaluators), and optional deps like `aiofiles` for async I/O.
- **Future**: Plugin system for watchers (e.g., file/dir via watchdog), timers, or webhooks—fired as custom triggers. Potential CLI entrypoint for standalone use.
- **Integrations**: Designed for VibeDir TUI (three-column layout with command column), but extensible to VSCode extensions or web apps.

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Why cmdorc?

Built from discussions on modular dev tools: Separates command orchestration from UIs, enabling reuse. If you're building a TUI like VibeDir (with clipboard/API modes for LLMs), this is the backend for your right-side "Command Results" column—handling runs, statuses, and results for prompts.

License: MIT.  
Author: [Your Name/Org].  
Issues/PRs: [GitHub Repo Link].