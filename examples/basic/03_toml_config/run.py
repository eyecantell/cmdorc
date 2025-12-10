"""
03_toml_config/run.py - Loading and running commands from TOML configuration

This example demonstrates:
- Loading configuration from a TOML file using load_config()
- Accessing commands from the loaded config
- Triggering commands defined in the config
- Showing status of all commands

The config.toml file in this directory defines the commands.

Try it:
    python examples/basic/03_toml_config/run.py
"""

import asyncio
from pathlib import Path

from cmdorc import CommandOrchestrator, load_config


async def main():
    """Load config from TOML and run commands."""

    # Step 1: Load configuration from TOML file
    # The config file is in the same directory as this script
    config_path = Path(__file__).parent / "config.toml"
    print(f"Loading configuration from {config_path.name}...")

    config = load_config(config_path)

    # Step 2: Create orchestrator from loaded config
    orchestrator = CommandOrchestrator(config)

    # Step 3: List all registered commands
    commands = orchestrator.list_commands()
    print(f"\nRegistered commands: {', '.join(commands)}")

    # Step 4: Trigger the workflow
    # This will run commands that have "start" in their triggers list
    print("\nTriggering 'start' event...")
    await orchestrator.trigger("start")

    # Step 5: Wait for initial commands to complete
    await asyncio.sleep(0.5)

    # Step 6: Show status of all commands
    print("\nCommand Status:")
    for command_name in commands:
        status = orchestrator.get_status(command_name)
        print(f"  {command_name}: {status.state}")

    # Step 7: Trigger Test after Lint completes
    # (In the TOML config, Test has trigger "command_success:Lint")
    print("\nWaiting for workflow chain to complete...")
    await asyncio.sleep(1.0)

    # Step 8: Show final status
    print("\nFinal Status:")
    for command_name in commands:
        status = orchestrator.get_status(command_name)
        print(f"  {command_name}: {status.state}")

    # Step 9: Wait before shutdown
    await asyncio.sleep(0.1)

    # Step 10: Clean up
    await orchestrator.shutdown()
    print("\nShutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
