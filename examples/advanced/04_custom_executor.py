"""
04_custom_executor.py - Implementing a custom executor

This example demonstrates:
- Subclassing CommandExecutor ABC
- Implementing start_run() and cancel_run()
- Logging/monitoring wrapper pattern
- Testing with custom executors

Try it:
    python examples/advanced/04_custom_executor.py
"""

import asyncio
from typing import Any

from cmdorc import (
    CommandConfig,
    CommandExecutor,
    CommandOrchestrator,
    LocalSubprocessExecutor,
    ResolvedCommand,
    RunResult,
    RunnerConfig,
)


class LoggingExecutor(CommandExecutor):
    """Custom executor that logs all operations."""

    def __init__(self, base_executor: CommandExecutor | None = None):
        """Initialize with optional base executor."""
        self.base_executor = base_executor or LocalSubprocessExecutor()
        self.run_count = 0
        self.log = []

    async def start_run(self, result: RunResult, resolved: ResolvedCommand) -> None:
        """Start a run with logging."""
        self.run_count += 1
        log_entry = f"[{self.run_count}] Starting: {result.command_name}"
        self.log.append(log_entry)
        print(f"  🔹 {log_entry}")

        # Delegate to base executor
        await self.base_executor.start_run(result, resolved)

    async def cancel_run(self, result: RunResult, comment: str) -> None:
        """Cancel a run with logging."""
        log_entry = f"Cancelling {result.command_name}: {comment}"
        self.log.append(log_entry)
        print(f"  🔹 {log_entry}")

        # Delegate to base executor
        await self.base_executor.cancel_run(result, comment)

    async def cleanup(self) -> None:
        """Cleanup with summary."""
        print(f"  🔹 Cleanup (processed {self.run_count} runs)")
        await self.base_executor.cleanup()

    def get_log(self) -> list[str]:
        """Get execution log."""
        return self.log.copy()


class CountingExecutor(CommandExecutor):
    """Custom executor that counts execution time."""

    def __init__(self, base_executor: CommandExecutor | None = None):
        """Initialize with optional base executor."""
        self.base_executor = base_executor or LocalSubprocessExecutor()
        self.total_time = 0.0
        self.run_times = {}

    async def start_run(self, result: RunResult, resolved: ResolvedCommand) -> None:
        """Start and measure execution."""
        import time

        result._custom_start = time.time()
        await self.base_executor.start_run(result, resolved)

    async def cancel_run(self, result: RunResult, comment: str) -> None:
        """Cancel with measurement."""
        await self.base_executor.cancel_run(result, comment)

    async def cleanup(self) -> None:
        """Cleanup."""
        await self.base_executor.cleanup()


async def main():
    """Demonstrate custom executors."""

    # Step 1: Create commands
    commands = [
        CommandConfig(
            name="Task1",
            command="echo 'Task 1'",
            triggers=["task1"],
        ),
        CommandConfig(
            name="Task2",
            command="echo 'Task 2'",
            triggers=["task2"],
        ),
    ]

    # Step 2: Create custom executor
    logging_executor = LoggingExecutor()

    # Step 3: Create orchestrator with custom executor
    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config, executor=logging_executor)

    # Step 4: Run commands
    print("Running with custom logging executor:")
    print()

    handle1 = await orchestrator.run_command("Task1")
    await handle1.wait(timeout=5.0)

    handle2 = await orchestrator.run_command("Task2")
    await handle2.wait(timeout=5.0)

    # Step 5: Show execution log
    print("\nExecution Log:")
    for entry in logging_executor.get_log():
        print(f"  {entry}")

    # Step 6: Wait before shutdown
    await asyncio.sleep(0.1)

    # Step 7: Clean up
    await orchestrator.shutdown()
    print("\n✅ Custom executor demonstration complete")


if __name__ == "__main__":
    asyncio.run(main())
