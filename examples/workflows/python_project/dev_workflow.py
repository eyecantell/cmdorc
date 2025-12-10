"""
python_project/dev_workflow.py - Python development workflow orchestration

This example demonstrates:
- Creating a development workflow for Python projects
- Interactive command selection via CLI arguments
- Managing long-running tasks with cancellation policies
- Real-time status and output tracking

Workflow commands:
  - Lint: Check code with ruff
  - Format: Auto-format with ruff
  - Test: Run pytest
  - Build: Build distribution packages
  - Clean: Remove build artifacts

Features:
- cancel_and_restart policy: Re-run build if triggered while running
- Timeout handling: Some tasks have time limits
- Variable resolution: Uses project paths from config

Try it:
    python examples/workflows/python_project/dev_workflow.py [command]
    python examples/workflows/python_project/dev_workflow.py lint
    python examples/workflows/python_project/dev_workflow.py test
"""
# ruff: noqa: T201

import argparse
import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Run Python development workflow."""

    # Step 1: Parse command line arguments
    parser = argparse.ArgumentParser(description="Python project development workflow")
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        help="Command to run (lint, format, test, build, clean, all)",
    )
    args = parser.parse_args()

    # Step 2: Define development commands
    # These simulate typical Python development tools
    commands = [
        CommandConfig(
            name="Lint",
            command="echo '📝 Running ruff check...'; sleep 0.3; echo '✓ No issues found'",
            triggers=["lint", "all"],
            max_concurrent=1,
            timeout_secs=60,
        ),
        CommandConfig(
            name="Format",
            command="echo '✨ Running ruff format...'; sleep 0.3; echo '✓ Formatted'",
            triggers=["format", "all"],
            max_concurrent=1,
            timeout_secs=60,
        ),
        CommandConfig(
            name="Test",
            command="echo '🧪 Running pytest...'; sleep 0.5; echo '✓ All tests passed'",
            triggers=["test", "all", "command_success:Lint"],
            max_concurrent=1,
            timeout_secs=180,
        ),
        CommandConfig(
            name="Build",
            command="echo '🔨 Building package...'; sleep 0.3; echo '✓ Package built'",
            triggers=["build", "all"],
            max_concurrent=1,
            on_retrigger="cancel_and_restart",  # Restart build if retriggered
            timeout_secs=120,
        ),
        CommandConfig(
            name="Clean",
            command="echo '🗑️  Cleaning build artifacts...'; sleep 0.2; echo '✓ Cleaned'",
            triggers=["clean"],
            max_concurrent=1,
        ),
    ]

    # Step 3: Create orchestrator
    config = RunnerConfig(
        commands=commands,
        vars={"project_dir": ".", "test_dir": "tests"},
    )
    orchestrator = CommandOrchestrator(config)

    # Step 4: Set up event callbacks for real-time feedback
    async def on_command_started(handle, context):
        """Called when a command starts."""
        print(f"→ {handle.command_name} started (run_id={handle.run_id[:8]}...)")

    async def on_command_success(handle, context):
        """Called when a command succeeds."""
        print(f"✓ {handle.command_name} completed successfully")

    async def on_command_failure(handle, context):
        """Called when a command fails."""
        print(f"✗ {handle.command_name} failed")

    orchestrator.on_event("command_started:*", on_command_started)
    orchestrator.on_event("command_success:*", on_command_success)
    orchestrator.on_event("command_failed:*", on_command_failure)

    # Step 5: Display available commands
    print("Available commands:")
    for cmd in orchestrator.list_commands():
        print(f"  - {cmd}")
    print()

    # Step 6: Run the requested command(s)
    print(f"Running: {args.command}")
    print("-" * 50)
    await orchestrator.trigger(args.command)

    # Step 7: Wait for completion
    max_wait = 30.0
    elapsed = 0.0
    while elapsed < max_wait:
        await asyncio.sleep(0.5)
        elapsed += 0.5

        active = orchestrator.get_all_active_handles()
        if not active:
            break

    # Step 8: Show final status
    print("-" * 50)
    print("Final Status:")
    for cmd_name in orchestrator.list_commands():
        status = orchestrator.get_status(cmd_name)
        if status.state != "never_run":
            symbol = "✓" if status.state == "success" else "✗"
            print(f"  {symbol} {cmd_name}: {status.state}")
    # Step Clean up
    await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
