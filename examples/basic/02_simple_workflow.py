"""
02_simple_workflow.py - Command chaining with lifecycle triggers

This example demonstrates:
- Creating multiple commands that form a workflow
- Using lifecycle triggers (command_success:Name) to chain commands
- Fire-and-forget execution patterns
- Monitoring multiple runs concurrently

Workflow: Lint → Test
- Lint runs first
- If Lint succeeds, Test runs automatically
- Both run in the background

Try it:
    python examples/basic/02_simple_workflow.py
"""

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Run a lint → test workflow."""

    # Step 1: Create command configurations
    # Lint command - runs first
    lint_config = CommandConfig(
        name="Lint",
        command="echo '✓ Lint passed'",  # Simulated success
        triggers=["Lint", "start"],  # Manual trigger or "start" event
    )

    # Test command - runs after Lint succeeds
    # The trigger "command_success:Lint" is auto-emitted when Lint succeeds
    test_config = CommandConfig(
        name="Test",
        command="echo '✓ Tests passed'",  # Simulated success
        triggers=["command_success:Lint", "Test"],
    )

    # Step 2: Create orchestrator with both commands
    config = RunnerConfig(commands=[lint_config, test_config], vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 3: Fire-and-forget execution
    # Trigger the workflow - this returns immediately without waiting
    print("Starting workflow...")
    await orchestrator.trigger("start")

    # Step 4: Wait for everything to complete
    # In a real application, you might do other work here (like handle UI events)
    # For this example, we just sleep to let the workflow finish
    print("Waiting for workflow to complete...")
    await asyncio.sleep(1.5)

    # Step 5: Check status after workflow completes
    lint_status = orchestrator.get_status("Lint")
    test_status = orchestrator.get_status("Test")

    print(f"\nWorkflow Results:")
    print(f"  Lint: {lint_status.state}")
    print(f"  Test: {test_status.state}")

    # Step 6: Get command history
    lint_history = orchestrator.get_history("Lint", limit=5)
    test_history = orchestrator.get_history("Test", limit=5)

    print(f"\nExecution History:")
    print(f"  Lint ran {len(lint_history)} time(s)")
    print(f"  Test ran {len(test_history)} time(s)")

    # Step 7: Wait before shutdown to let any pending tasks finish
    await asyncio.sleep(0.1)

    # Step 8: Clean up
    await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
