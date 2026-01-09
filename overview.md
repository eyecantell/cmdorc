# Cmdorc Project Ecosystem Overview

This document provides a concise reference to the three interconnected repositories that form the cmdorc ecosystem: a command orchestration backend, supporting Textual widgets, and a full TUI frontend.

## cmdorc – Command Orchestration Backend
**Repository**: https://github.com/eyecantell/cmdorc

**Purpose**  
`cmdorc` is a lightweight, async-first Python library for event-driven execution of shell commands. It acts as a robust backend for triggering commands based on string events (e.g., `"lint"`, `"tests_passed"`), suitable for developer tools, TUIs, automation scripts, or LLM agents.

**Key Features**
- Event-triggered command execution with auto-events (`command_started`, `command_success`, etc.).
- Async, non-blocking runs with cancellation, timeouts, debounce, and concurrency controls.
- Declarative TOML configuration (`cmdorc.toml`).
- Template variable resolution (`{{ var }}`) with nesting and cycle detection.
- Persistent output storage (`.cmdorc/outputs/`) with history retention.
- Full lifecycle hooks and state tracking (active runs, history, durations, breadcrumbs).
- Cycle detection and safety mechanisms.
- Minimal dependencies (stdlib + `tomli` for older Python).

**Core Components**
- `CommandOrchestrator`: Main async context manager for loading config and handling triggers.
- `RunHandle` / `RunResult`: Objects for live and completed command state.
- Designed to separate orchestration logic from any frontend.

## textual-filelink – Textual Widgets for File and Command Links
**Repository**: https://github.com/eyecantell/textual-filelink

**Purpose**  
Provides reusable Textual widgets for displaying clickable file paths and command execution controls in terminal UIs. Enables opening files in external editors (VS Code, vim, etc.) and rich command status visualization.

**Key Widgets**
- `FileLink`: Clickable file path; supports line/column jumping and custom editor commands.
- `CommandLink`: Shows command status with play/stop buttons, timers, spinners, and icons.
- `FileLinkList`: Container for managing lists of links with toggles, remove buttons, and batch operations.
- `FileLinkWithIcons`: Extends `FileLink` with configurable, clickable icons (before/after filename).

**Features**
- Full keyboard accessibility and customizable shortcuts.
- Dynamic status icons, tooltips with shortcut hints, and animated spinners.
- Highly composable within Textual apps; emits events like `Opened`, `PlayClicked`.

These widgets are intentionally generic but prove especially useful for command-oriented TUIs.

## textual-cmdorc – TUI Frontend for cmdorc
**Repository**: https://github.com/eyecantell/textual-cmdorc

**Purpose**  
A complete Textual-based terminal UI for cmdorc, providing an interactive command dashboard with real-time status, manual controls, and optional file watching.

**Key Features**
- Loads `cmdorc.toml` (or custom path) to display commands in a flat list.
- Real-time status via `CommandLink` widgets (icons: ◯/⏳/✅/❌, tooltips with last-run info).
- Play/stop buttons and global keyboard shortcuts (1-9, a-z, F1-F12).
- File watching via `watchdog` to auto-trigger events on filesystem changes.
- Command chaining (success/failure triggers).
- Modal details screen (`s` key) showing history, output preview, triggers.
- Live config reload (`r`), help screen (`h`).
- Embeddable `CmdorcWidget` for integration into larger multi-panel apps.
- Headless-capable `OrchestratorAdapter` (no Textual deps) for custom frontends.

**Dependencies & Integration**
- Uses `cmdorc` for orchestration logic.
- Uses `textual-filelink` for the core `CommandLink` display widgets.
- Extends cmdorc TOML with optional `[keyboard]` and `[[file_watcher]]` sections.

**Quick Start**
```bash
pip install textual-cmdorc
cmdorc-tui  # generates starter commands.toml and/or cmdorc-tui.toml based on user input
```

## Relationship Summary
- **cmdorc**: Pure backend – handles the heavy lifting of async command execution and state.
- **textual-filelink**: UI building blocks – provides the interactive widgets used in the TUI.
- **textual-cmdorc**: Complete application – ties the backend and widgets together into a usable developer tool.

This modular design keeps concerns separated: the backend remains framework-agnostic, widgets are reusable, and the TUI delivers a polished experience without over-engineering the core.