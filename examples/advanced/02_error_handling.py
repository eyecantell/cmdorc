"""
02_error_handling.py - Comprehensive error handling patterns

This example demonstrates:
- Catching cmdorc-specific exceptions
- Handling execution failures gracefully
- Timeout management
- Graceful degradation

Try it:
    python examples/advanced/02_error_handling.py
"""

import asyncio

from cmdorc import (
    CommandConfig,
    CommandNotFoundError,
    ConcurrencyLimitError,
    CommandOrchestrator,
    DebounceError,
    RunnerConfig,
)


async def main():
    """Demonstrate error handling patterns."""

    # Step 1: Create commands for error scenarios
    commands = [
        CommandConfig(
            name="FastTask",
            command="echo 'Done'; exit 0",
            triggers=["fast"],
            max_concurrent=1,
        ),
        CommandConfig(
            name="SlowTask",
            command="echo 'Running...'; sleep 2; echo 'Done'",
            triggers=["slow"],
            max_concurrent=1,
        ),
        CommandConfig(
            name="DebounceTask",
            command="echo 'Task'",
            triggers=["debounce"],
            debounce_in_ms=1000,
        ),
    ]

    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 2: Handle CommandNotFoundError
    print("1. CommandNotFoundError:")
    try:
        await orchestrator.run_command("NonExistent")
    except CommandNotFoundError as e:
        print(f"   ✓ Caught: {e}")

    # Step 3: Handle DebounceError
    print("\n2. DebounceError:")
    try:
        # Run once
        handle1 = await orchestrator.run_command("DebounceTask")
        await handle1.wait(timeout=1.0)

        # Try again immediately - should fail
        await orchestrator.run_command("DebounceTask")
    except DebounceError as e:
        print(f"   ✓ Caught: {e}")

    # Step 4: Handle ConcurrencyLimitError
    print("\n3. ConcurrencyLimitError:")
    try:
        # Start slow task
        handle1 = await orchestrator.run_command("SlowTask")
        await asyncio.sleep(0.1)  # Let it start

        # Try to run again (max_concurrent=1)
        await orchestrator.run_command("SlowTask")
    except ConcurrencyLimitError as e:
        print(f"   ✓ Caught: {e}")

    # Step 5: Handle execution timeouts gracefully
    print("\n4. Timeout Handling:")
    config_with_timeout = CommandConfig(
        name="TimedOut",
        command="sleep 10",  # Will timeout
        triggers=["timed_out"],
        timeout_secs=1,
    )
    orchestrator.add_command(config_with_timeout)

    try:
        handle = await orchestrator.run_command("TimedOut")
        await handle.wait(timeout=2.0)
        print(f"   State: {handle.state}")
        if handle.state == "failed":
            print(f"   ✓ Command timed out as expected")
    except asyncio.TimeoutError:
        print(f"   ✓ Wait timeout (command timed out)")

    # Step 6: Exception in callbacks (handled gracefully)
    print("\n5. Callback Exception Handling:")

    async def failing_callback(handle, context):
        """This callback will raise an exception."""
        raise RuntimeError("Callback failed")

    orchestrator.on_event("test_event", failing_callback)

    try:
        # Trigger should not raise even if callback fails
        await orchestrator.trigger("test_event")
        print("   ✓ Trigger succeeded despite callback exception")
    except Exception as e:
        print(f"   ✗ Unexpected: {e}")

    # Step 7: Wait before shutdown
    await asyncio.sleep(0.1)

    # Step 8: Clean up
    await orchestrator.shutdown()
    print("\n✅ Error handling demonstration complete")


if __name__ == "__main__":
    asyncio.run(main())
