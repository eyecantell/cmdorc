"""
Example: Trigger Chain (Breadcrumb) Tracking

Demonstrates how to access and display the chain of triggers
that led to a command's execution.
"""

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig
from cmdorc.mock_executor import MockExecutor


async def main():
    # Create a workflow: Save → Lint → Test → Deploy
    commands = [
        CommandConfig(
            name="Lint",
            command="echo 'Linting...'",
            triggers=["file_saved"],
        ),
        CommandConfig(
            name="Test",
            command="echo 'Testing...'",
            triggers=["command_success:Lint"],
        ),
        CommandConfig(
            name="Deploy",
            command="echo 'Deploying...'",
            triggers=["command_success:Test"],
        ),
    ]

    config = RunnerConfig(commands=commands)
    executor = MockExecutor(delay=0.1)  # Simulate 100ms per command
    orchestrator = CommandOrchestrator(config, executor=executor)

    # Set up callback to print chains
    def on_start(handle, context):
        if handle is None:
            return  # Skip if no handle
        chain = handle.trigger_chain
        if chain:
            chain_str = " → ".join(chain)
            print(f"  {handle.command_name} triggered by: {chain_str}")
        else:
            print(f"  {handle.command_name} started manually")

    orchestrator.on_event("command_started:*", on_start)

    print("=== Manual Run (No Chain) ===")
    handle = await orchestrator.run_command("Lint")
    await handle.wait()
    print(f"Chain: {handle.trigger_chain}\n")

    print("=== Triggered Workflow ===")
    await orchestrator.trigger("file_saved")
    await asyncio.sleep(0.5)  # Let chain complete

    print("\n=== History Inspection ===")
    for cmd_name in ["Lint", "Test", "Deploy"]:
        history = orchestrator.get_history(cmd_name, limit=1)
        if history:
            result = history[0]
            chain_str = " → ".join(result.trigger_chain) if result.trigger_chain else "manual"
            print(f"{cmd_name}: {chain_str}")

    await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
