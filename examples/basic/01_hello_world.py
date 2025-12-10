"""
01_hello_world.py - Minimal cmdorc example

This is the simplest possible cmdorc example. It demonstrates:
- Creating a CommandOrchestrator with a single command
- Running a command manually with run_command()
- Waiting for completion with handle.wait()

Try it:
    python examples/basic/01_hello_world.py
"""
# ruff: noqa: T201

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Run a simple 'echo' command using cmdorc."""

    # Step 1: Create a single command configuration
    # This command will print "Hello from cmdorc!"
    echo_config = CommandConfig(
        name="Echo",
        command="echo 'Hello from cmdorc!'",
        triggers=["Echo"],  # Can be triggered with trigger("Echo")
    )

    # Step 2: Create orchestrator with this command
    # RunnerConfig holds all commands and global variables
    config = RunnerConfig(commands=[echo_config], vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 3: Execute the command manually
    # run_command() returns a RunHandle immediately (non-blocking)
    print("Starting command...")
    handle = await orchestrator.run_command("Echo")

    # Step 4: Wait for the command to complete
    # handle.wait() is event-driven (no polling), so it's efficient
    await handle.wait(timeout=5.0)

    # Step 5: Check the result
    print(f"Command completed with state: {handle.state}")
    print(f"Success: {handle.success}")
    if handle.output:
        print(f"Output: {handle.output}")

    # Step 6: Clean up
    # Always shutdown the orchestrator to release resources
    await orchestrator.shutdown()


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
