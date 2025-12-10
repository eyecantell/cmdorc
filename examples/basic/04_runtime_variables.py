"""
04_runtime_variables.py - Variable resolution and templating

This example demonstrates:
- Global variables (RunnerConfig.vars)
- Command-specific variables (CommandConfig.vars)
- Runtime variables passed to run_command()
- Variable priority and overriding
- Template syntax {{ var }} and $VAR_NAME

Variable priority (highest to lowest):
1. Runtime variables (run_command(..., vars={...}))
2. Command-specific variables (CommandConfig.vars)
3. Environment variables (os.environ)
4. Global variables (RunnerConfig.vars)

Try it:
    python examples/basic/04_runtime_variables.py
"""

import asyncio
import os

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Demonstrate variable resolution."""

    # Step 1: Create commands with different variable sources
    # Command 1: Uses global and command-specific variables
    greet_config = CommandConfig(
        name="Greet",
        command="echo 'Hello {{ name }}, welcome to {{ environment }}'",
        triggers=["greet"],
        # Command-specific variables (can override global)
        vars={"name": "Developer", "environment": "cmdorc"},
    )

    # Command 2: Uses environment variables
    # $HOME is converted to {{ HOME }} internally
    pwd_config = CommandConfig(
        name="ShowPath",
        command="echo 'Home directory: $HOME'",
        triggers=["show_path"],
    )

    # Command 3: Shows variable priority
    priority_config = CommandConfig(
        name="Priority",
        command="echo 'Environment: {{ env }}' && echo 'Mode: {{ mode }}'",
        triggers=["priority"],
        vars={"mode": "default", "env": "staging"},
    )

    # Step 2: Create orchestrator with global variables
    config = RunnerConfig(
        commands=[greet_config, pwd_config, priority_config],
        # Global variables available to all commands
        vars={"name": "User", "env": "development"},
    )
    orchestrator = CommandOrchestrator(config)

    # Step 3: Run command with global/command variables
    print("1. Running with global and command-specific variables:")
    handle1 = await orchestrator.run_command("Greet")
    await handle1.wait(timeout=5.0)
    print()

    # Step 4: Run command with environment variables
    print("2. Running with environment variables ($HOME):")
    # Ensure HOME is in environment
    if "HOME" not in os.environ:
        os.environ["HOME"] = "/home/user"
    handle2 = await orchestrator.run_command("ShowPath")
    await handle2.wait(timeout=5.0)
    print()

    # Step 5: Run command with runtime variables (highest priority)
    print("3. Running with runtime variable override:")
    print("   Original 'name' value: User (global)")
    print("   Override with runtime vars: Alice")
    handle3 = await orchestrator.run_command(
        "Greet",
        vars={"name": "Alice"},  # Override global variable
    )
    await handle3.wait(timeout=5.0)
    print()

    # Step 6: Demonstrate variable priority
    print("4. Demonstrating variable priority:")
    print("   'env' is in global vars (development)")
    print("   'mode' is in command vars (default)")
    print("   Running with runtime override for 'env' (production):")
    handle4 = await orchestrator.run_command(
        "Priority",
        vars={"env": "production"},  # Override global
    )
    await handle4.wait(timeout=5.0)
    print()

    # Step 7: Wait before shutdown
    await asyncio.sleep(0.1)

    # Step 8: Clean up
    await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
