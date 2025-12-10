"""
05_status_and_history.py - State tracking, status, and history

This example demonstrates:
- Getting command status with get_status()
- Retrieving execution history with get_history()
- RunHandle properties (command_name, run_id, state, success, etc.)
- CommandStatus fields (state, active_count, last_run)
- Tracking multiple runs and state transitions

Try it:
    python examples/basic/05_status_and_history.py
"""

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Demonstrate status tracking and history."""

    # Step 1: Create a command that we'll run multiple times
    count_config = CommandConfig(
        name="Counter",
        command="echo 'Run count'",
        triggers=["counter"],
        keep_history=5,  # Keep last 5 runs
    )

    config = RunnerConfig(commands=[count_config], vars={})
    orchestrator = CommandOrchestrator(config)

    # Step 2: Check initial status (before any runs)
    print("Initial Status (before any runs):")
    status = orchestrator.get_status("Counter")
    print(f"  State: {status.state}")
    print(f"  Active runs: {status.active_count}")
    print(f"  Last run: {status.last_run}")
    print()

    # Step 3: Run the command multiple times
    print("Running command 3 times...")
    handles = []
    for i in range(3):
        handle = await orchestrator.run_command("Counter")
        handles.append(handle)
        print(f"  Run {i + 1}: run_id={handle.run_id}")

    # Step 4: Wait for all runs to complete
    print("\nWaiting for all runs to complete...")
    await asyncio.gather(*[h.wait(timeout=5.0) for h in handles])
    await asyncio.sleep(0.2)  # Give time for state updates

    # Step 5: Check status after runs
    print("\nStatus After Runs:")
    status = orchestrator.get_status("Counter")
    print(f"  State: {status.state}")
    print(f"  Active runs: {status.active_count}")
    print(f"  Last run: {status.last_run}")
    print()

    # Step 6: Inspect RunHandle properties
    print("RunHandle Properties (first run):")
    handle = handles[0]
    print(f"  command_name: {handle.command_name}")
    print(f"  run_id: {handle.run_id}")
    print(f"  state: {handle.state}")
    print(f"  success: {handle.success}")
    print(f"  is_finalized: {handle.is_finalized}")
    if handle.start_time:
        print(f"  start_time: {handle.start_time}")
    if handle.end_time:
        print(f"  end_time: {handle.end_time}")
    if handle.duration_str:
        print(f"  duration: {handle.duration_str}")
    if handle.output:
        print(f"  output: {handle.output.strip()}")
    print()

    # Step 7: Get command history
    print("Command History (last 5 runs):")
    history = orchestrator.get_history("Counter", limit=5)
    print(f"  Total in history: {len(history)}")
    for i, result in enumerate(history, 1):
        print(f"  {i}. run_id={result.run_id}, state={result.state}, success={result.success}")
    print()

    # Step 8: Get active handles
    print("Active Handles:")
    active_handles = orchestrator.get_active_handles("Counter")
    print(f"  Count: {len(active_handles)}")
    # Should be 0 since all runs completed
    for handle in active_handles:
        print(f"    - {handle.run_id}: {handle.state}")
    print()

    # Step 9: Demonstrate all-active-handles query
    print("All Active Handles (across all commands):")
    all_active = orchestrator.get_all_active_handles()
    print(f"  Total: {len(all_active)}")

    # Step 10: Wait before shutdown
    await asyncio.sleep(0.1)

    # Step 11: Clean up
    await orchestrator.shutdown()
    print("\nShutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
