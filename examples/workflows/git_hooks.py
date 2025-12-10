"""
git_hooks.py - Git workflow automation with cmdorc

This example demonstrates:
- Automating git-related workflows (pre-commit, pre-push)
- Command cancellation on specific events
- Orchestrating external tools (git, linters, tests)
- Error handling for failed checks

Use cases:
- Lint and format before commit
- Run tests before push
- Cancel long operations on user interrupt

Try it:
    python examples/workflows/git_hooks.py
"""

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Orchestrate git workflow commands."""

    # Step 1: Define git-related commands
    commands = [
        CommandConfig(
            name="PreCommitLint",
            command="echo '📝 Running pre-commit lint...'; sleep 0.3; echo '✓ Lint passed'",
            triggers=["pre-commit"],
            max_concurrent=1,
            timeout_secs=60,
        ),
        CommandConfig(
            name="PreCommitFormat",
            command="echo '✨ Formatting staged files...'; sleep 0.3; echo '✓ Formatted'",
            triggers=["command_success:PreCommitLint"],
            max_concurrent=1,
            timeout_secs=60,
        ),
        CommandConfig(
            name="PrePushTest",
            command="echo '🧪 Running tests before push...'; sleep 0.5; echo '✓ Tests passed'",
            triggers=["pre-push"],
            max_concurrent=1,
            timeout_secs=120,
        ),
        CommandConfig(
            name="ShowStats",
            command="echo '📊 Git stats: Changes ready to push'",
            triggers=["command_success:PrePushTest"],
            max_concurrent=1,
        ),
        # Cleanup on interruption
        CommandConfig(
            name="CleanupOnCancel",
            command="echo '⚠️  Operation cancelled'; echo 'Restoring state...'",
            triggers=["command_cancelled:PreCommitLint", "command_cancelled:PrePushTest"],
            max_concurrent=1,
        ),
    ]

    # Step 2: Create orchestrator
    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 3: Set up callbacks for workflow feedback
    async def on_started(handle, context):
        """Log when commands start."""
        print(f"  → {handle.command_name} started")

    async def on_success(handle, context):
        """Log successes."""
        print(f"  ✓ {handle.command_name} succeeded")

    async def on_failure(handle, context):
        """Log failures and suggest actions."""
        print(f"  ✗ {handle.command_name} failed")
        print(f"    Action: Check your code and try again")

    async def on_cancel(handle, context):
        """Log cancellations."""
        print(f"  ⊘ {handle.command_name} was cancelled")

    orchestrator.on_event("command_started:*", on_started)
    orchestrator.on_event("command_success:*", on_success)
    orchestrator.on_event("command_failed:*", on_failure)
    orchestrator.on_event("command_cancelled:*", on_cancel)

    # Step 4: Simulate pre-commit workflow
    print("=" * 50)
    print("Pre-Commit Workflow")
    print("=" * 50)
    await orchestrator.trigger("pre-commit")
    await asyncio.sleep(2.0)

    # Step 5: Show status
    print("\nWorkflow Status:")
    for cmd_name in orchestrator.list_commands():
        status = orchestrator.get_status(cmd_name)
        if status.state != "never_run":
            print(f"  {cmd_name}: {status.state}")

    # Step 6: Reset and simulate pre-push workflow
    print("\n" + "=" * 50)
    print("Pre-Push Workflow")
    print("=" * 50)
    await orchestrator.trigger("pre-push")
    await asyncio.sleep(2.0)

    # Step 7: Final status
    print("\nFinal Status:")
    for cmd_name in orchestrator.list_commands():
        status = orchestrator.get_status(cmd_name)
        if status.state != "never_run":
            symbol = "✓" if status.state == "success" else "✗"
            print(f"  {symbol} {cmd_name}: {status.state}")

    # Step 8: Wait before shutdown
    await asyncio.sleep(0.1)

    # Step 9: Clean up
    await orchestrator.shutdown()
    print("\n✅ Git workflows complete")


if __name__ == "__main__":
    asyncio.run(main())
