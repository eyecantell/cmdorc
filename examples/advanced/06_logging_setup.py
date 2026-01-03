"""
Example: Logging Configuration for cmdorc

This example demonstrates various logging configurations for cmdorc,
including console logging, file logging, custom formats, and propagation control.
"""

import asyncio
import logging

from cmdorc import (
    CommandConfig,
    CommandOrchestrator,
    disable_logging,
    get_log_file_path,
    setup_logging,
)


async def main():
    # Example 1: Basic console + file logging
    print("=== Example 1: Console + File Logging ===")
    setup_logging(level="DEBUG", file=True)

    commands = [
        CommandConfig(
            name="Test",
            command="echo 'Hello from cmdorc!'",
            triggers=["test"],
        )
    ]

    async with CommandOrchestrator(commands=commands) as orch:
        handle = await orch.run_command("Test")
        await handle.wait()
        print(f"Result: {handle.state.value}")

    print(f"Log file: {get_log_file_path()}\n")

    # Example 2: Custom format
    print("=== Example 2: Custom Format ===")
    setup_logging(level="INFO", format_string="[%(levelname)s] %(message)s")

    async with CommandOrchestrator(commands=commands) as orch:
        await (await orch.run_command("Test")).wait()

    # Example 3: Prevent double-logging (if you have root configured)
    print("\n=== Example 3: With propagate=False ===")
    # Simulate user's root logger config
    logging.basicConfig(level=logging.DEBUG, format="ROOT: %(levelname)s - %(name)s - %(message)s")

    # Without propagate=False, logs would appear twice (once from our handler, once from root)
    # With propagate=False, only our handler outputs
    setup_logging(level="DEBUG", propagate=False)

    async with CommandOrchestrator(commands=commands) as orch:
        await (await orch.run_command("Test")).wait()

    # Example 4: Detailed format (includes file:line)
    print("\n=== Example 4: Detailed Format ===")
    setup_logging(level="INFO", format="detailed")

    async with CommandOrchestrator(commands=commands) as orch:
        await (await orch.run_command("Test")).wait()

    # Example 5: File only (no console)
    print("\n=== Example 5: File Only (No Console) ===")
    setup_logging(level="DEBUG", console=False, file=True)
    print("Logging to file only - no console output from cmdorc")

    async with CommandOrchestrator(commands=commands) as orch:
        await (await orch.run_command("Test")).wait()

    print(f"Check {get_log_file_path()} for logs")

    # Example 6: Disable logging (useful for tests)
    print("\n=== Example 6: Disable Logging ===")
    disable_logging()
    print("Logging disabled - no cmdorc output will appear")

    async with CommandOrchestrator(commands=commands) as orch:
        await (await orch.run_command("Test")).wait()

    print("Command ran but no logs appeared")

    # Example 7: Integration with existing logging
    print("\n=== Example 7: Integration with Your App Logging ===")

    # Your app's logger
    app_logger = logging.getLogger("myapp")
    app_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("APP: %(name)s - %(message)s"))
    app_logger.addHandler(handler)

    # cmdorc logs will propagate to root and appear alongside your app logs
    setup_logging(level="INFO", console=False)  # Rely on propagation

    app_logger.info("Application starting")

    async with CommandOrchestrator(commands=commands) as orch:
        await (await orch.run_command("Test")).wait()

    app_logger.info("Application finished")


if __name__ == "__main__":
    asyncio.run(main())
