"""
auto_tester/watcher.py - Auto-run tests on Python file changes

This example demonstrates:
- Loading test configuration from TOML
- Monitoring specific file patterns (.py files)
- Debounce in action (prevents test spam)
- Real-time status updates

Requirements:
    pip install watchdog

Try it:
    python examples/file_watching/auto_tester/watcher.py
"""
# ruff: noqa: T201

import asyncio
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from cmdorc import CommandOrchestrator, load_config


class PythonFileHandler(FileSystemEventHandler):
    """Watch for Python file changes and trigger tests."""

    def __init__(self, orchestrator):
        """Initialize with orchestrator."""
        self.orchestrator = orchestrator

    def on_modified(self, event: FileModifiedEvent):
        """Called when a file is modified."""
        if event.is_directory:
            return

        # Only trigger on Python files
        if event.src_path.endswith(".py"):
            filename = Path(event.src_path).name
            print(f"📝 {filename} changed")

            # Trigger the test command
            # Debounce in config prevents rapid re-runs
            asyncio.create_task(self.orchestrator.trigger("file_changed"))


async def main():
    """Watch Python files and auto-run tests."""

    # Step 1: Load test configuration
    config_path = Path(__file__).parent / "config.toml"
    print(f"Loading test config from {config_path.name}...")
    config = load_config(config_path)
    orchestrator = CommandOrchestrator(config)

    # Step 2: Set up file watcher
    event_handler = PythonFileHandler(orchestrator)
    observer = Observer()

    # Watch the parent directory (file_watching)
    watch_path = Path(__file__).parent.parent
    observer.schedule(event_handler, str(watch_path), recursive=False)

    # Step 3: Set up callbacks for feedback
    async def on_test_success(handle, context):
        """Called when tests pass."""
        duration = (
            f"{handle.end_time - handle.start_time:.2f}s"
            if handle.end_time and handle.start_time
            else "unknown"
        )
        print(f"  ✓ Tests passed ({duration})")

    async def on_test_failure(handle, context):
        """Called when tests fail."""
        print("  ✗ Tests failed - fix the issues and save to retry")

    orchestrator.on_event("command_success:RunTests", on_test_success)
    orchestrator.on_event("command_failed:RunTests", on_test_failure)

    # Step 4: Start watching
    print(f"🔍 Watching {watch_path} for Python file changes...")
    print("   Modify .py files to trigger tests")
    print("   Debounce: Tests won't re-run within 1 second of previous run")
    print("   Press Ctrl+C to stop\n")

    observer.start()

    # Step 5: Keep running
    try:
        while True:
            await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        print("\n🛑 Stopping watcher...")

    # Step 6: Clean up
    observer.stop()
    observer.join()
    await asyncio.sleep(0.1)
    await orchestrator.shutdown()
    print("✅ Auto-tester stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ImportError as e:
        print(f"Error: {e}")
        print("Install watchdog with: pip install watchdog")
