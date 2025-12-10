"""
simple_watcher.py - Basic file watching with cmdorc

This example demonstrates:
- Using watchdog to monitor file changes
- Triggering cmdorc commands on file events
- Debouncing to prevent rapid re-runs
- Graceful shutdown

Requirements:
    pip install watchdog

The watcher monitors the current directory and triggers commands
when Python files change.

Try it:
    python examples/file_watching/simple_watcher.py
"""
# ruff: noqa: T201

import asyncio
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


class FileChangeHandler(FileSystemEventHandler):
    """Handle file system events and trigger cmdorc commands."""

    def __init__(self, orchestrator):
        """Initialize with orchestrator instance."""
        self.orchestrator = orchestrator

    def on_modified(self, event: FileModifiedEvent):
        """Called when a file is modified."""
        if not event.is_directory and event.src_path.endswith(".py"):
            # Extract just the filename for logging
            filename = Path(event.src_path).name
            print(f"📝 {filename} changed")

            # Trigger the build command
            # This runs asynchronously in the background
            asyncio.create_task(self.orchestrator.trigger("file_changed"))


async def main():
    """Watch files and run commands on changes."""

    # Step 1: Create commands that respond to file changes
    commands = [
        CommandConfig(
            name="Lint",
            command="echo '📝 Linting changed files...'; sleep 0.3; echo '✓ Lint passed'",
            triggers=["file_changed"],
            max_concurrent=1,
            # Debounce: ignore changes within 500ms (prevents excessive re-runs)
            debounce_in_ms=500,
            timeout_secs=60,
        ),
    ]

    # Step 2: Create orchestrator
    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 3: Set up file watcher
    event_handler = FileChangeHandler(orchestrator)
    observer = Observer()

    # Watch the examples directory
    watch_path = Path(__file__).parent
    observer.schedule(event_handler, str(watch_path), recursive=False)

    # Step 4: Start watching
    print(f"🔍 Watching {watch_path} for changes...")
    print("   (Modify .py files to trigger linting)")
    print("   Press Ctrl+C to stop\n")

    observer.start()

    # Step 5: Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping watcher...")

    # Step 6: Clean up
    observer.stop()
    observer.join()
    await asyncio.sleep(0.1)
    await orchestrator.shutdown()
    print("✅ Watcher stopped")


if __name__ == "__main__":
    # Note: This example requires watchdog
    # Install with: pip install watchdog
    try:
        asyncio.run(main())
    except ImportError as e:
        print(f"Error: {e}")
        print("Install watchdog with: pip install watchdog")
