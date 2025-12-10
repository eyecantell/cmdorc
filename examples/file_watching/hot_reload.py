"""
hot_reload.py - Hot reload development server on file changes

This example demonstrates:
- Using cancel_and_restart policy to restart on changes
- Managing long-running server processes
- Coordinating multiple dependent commands

Requirements:
    pip install watchdog

Scenario:
- Watch app files
- Restart development server when changes detected
- Previous server killed before new one starts

Try it:
    python examples/file_watching/hot_reload.py
"""

import asyncio
from pathlib import Path

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


class ServerFileHandler(FileSystemEventHandler):
    """Watch for code changes and restart server."""

    def __init__(self, orchestrator):
        """Initialize with orchestrator."""
        self.orchestrator = orchestrator
        self.last_restart = 0.0

    def on_modified(self, event: FileModifiedEvent):
        """Called when a file is modified."""
        if event.is_directory or not event.src_path.endswith(".py"):
            return

        filename = Path(event.src_path).name
        print(f"📝 {filename} changed - restarting server...")

        # Trigger restart
        asyncio.create_task(self.orchestrator.trigger("code_changed"))


async def main():
    """Manage hot-reload development server."""

    # Step 1: Create dev server commands
    commands = [
        CommandConfig(
            name="DevServer",
            # Simulated dev server that runs for a bit
            command="echo '🚀 Dev server started (http://localhost:8000)'; sleep 10; echo 'Server stopped'",
            triggers=["code_changed", "start"],
            max_concurrent=1,
            # cancel_and_restart: kill old server and start new one
            on_retrigger="cancel_and_restart",
            timeout_secs=None,  # No timeout, runs until cancelled
        ),
        CommandConfig(
            name="LogRestart",
            command="echo '♻️  Server restarted'",
            triggers=["command_cancelled:DevServer"],
            max_concurrent=1,
        ),
    ]

    # Step 2: Create orchestrator
    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 3: Set up callbacks
    async def on_server_start(handle, context):
        """Server started."""
        print(f"  ✓ Server started (run_id={handle.run_id[:8]}...)")

    async def on_server_cancel(handle, context):
        """Server was restarted."""
        print(f"  ⊘ Server stopped for restart")

    orchestrator.on_event("command_started:DevServer", on_server_start)
    orchestrator.on_event("command_cancelled:DevServer", on_server_cancel)

    # Step 4: Start file watcher
    event_handler = ServerFileHandler(orchestrator)
    observer = Observer()

    watch_path = Path(__file__).parent
    observer.schedule(event_handler, str(watch_path), recursive=False)

    # Step 5: Start dev server
    print("🚀 Starting hot-reload development server...")
    print(f"📁 Watching {watch_path} for changes...")
    print("   Try renaming or touching Python files to trigger restart")
    print("   Press Ctrl+C to stop\n")

    observer.start()
    await orchestrator.trigger("start")

    # Step 6: Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")

    # Step 7: Clean up
    observer.stop()
    observer.join()
    await asyncio.sleep(0.1)
    await orchestrator.shutdown(timeout=5.0, cancel_running=True)
    print("✅ Hot-reload server stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ImportError as e:
        print(f"Error: {e}")
        print("Install watchdog with: pip install watchdog")
