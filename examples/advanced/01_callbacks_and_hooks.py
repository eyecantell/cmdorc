"""
01_callbacks_and_hooks.py - Event callbacks and lifecycle hooks

This example demonstrates:
- on_event() with exact and wildcard patterns
- set_lifecycle_callback() for command lifecycle
- Both sync and async callbacks
- Exception handling in callbacks

Try it:
    python examples/advanced/01_callbacks_and_hooks.py
"""
# ruff: noqa: T201

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Demonstrate callback patterns."""

    # Commands
    commands = [
        CommandConfig(
            name="Build",
            command="echo '🔨 Building...'; sleep 0.3; echo '✓ Built'",
            triggers=["build"],
        ),
        CommandConfig(
            name="Test",
            command="echo '🧪 Testing...'; sleep 0.3; echo '✓ Passed'",
            triggers=["test"],
        ),
    ]

    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 1: Exact event callback
    async def on_build_event(handle, context):
        """Called for 'build_complete' event."""
        print("→ Build complete event fired")

    orchestrator.on_event("build_complete", on_build_event)

    # Step 2: Wildcard event callback (matches command_*:Test)
    async def on_test_lifecycle(handle, context):
        """Called on any Test lifecycle event."""
        event_type = "unknown"
        if handle and hasattr(handle, "state"):
            event_type = str(handle.state).lower()
        print(f"→ Test lifecycle event: {event_type}")

    orchestrator.on_event("command_*:Test", on_test_lifecycle)

    # Step 3: Wildcard for all command events
    def sync_callback(handle, context):
        """Synchronous callback (not async)."""
        if handle:
            print(f"  [Sync] {handle.command_name} event")

    orchestrator.on_event("command_*:Build", sync_callback)

    # Step 4: Lifecycle callbacks per command
    async def on_build_success(handle, context):
        """Called when Build succeeds."""
        print("  ✅ Build succeeded - can now test")

    async def on_build_failure(handle, context):
        """Called when Build fails."""
        print("  ❌ Build failed - fix errors")

    orchestrator.set_lifecycle_callback(
        "Build",
        on_success=on_build_success,
        on_failed=on_build_failure,
    )

    # Step 5: Callback that handles exceptions gracefully
    async def risky_callback(handle, context):
        """Callback that might fail."""
        if handle and handle.command_name == "Test":
            # Simulate work that might fail
            await asyncio.sleep(0.1)
            print("  ℹ️  Test callback executed")

    orchestrator.on_event("command_success:*", risky_callback)

    # Step 6: Run commands and observe callbacks
    print("Running Build command...")
    handle1 = await orchestrator.run_command("Build")
    await handle1.wait(timeout=5.0)
    await asyncio.sleep(0.2)

    print("\nRunning Test command...")
    handle2 = await orchestrator.run_command("Test")
    await handle2.wait(timeout=5.0)
    await asyncio.sleep(0.2)

    # Step 7: Trigger event manually
    print("\nTriggering manual event...")
    await orchestrator.trigger("build_complete")
    await asyncio.sleep(0.2)
    # Step Clean up
    await orchestrator.shutdown()
    print("\n✅ Callbacks demonstration complete")


if __name__ == "__main__":
    asyncio.run(main())
