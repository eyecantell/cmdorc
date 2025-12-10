"""
ci_pipeline/ci_runner.py - Complete CI/CD pipeline orchestration

This example demonstrates:
- Loading a complete CI pipeline from TOML
- Chained commands with lifecycle event triggers
- Error handling for failed commands
- Status tracking and result collection
- Graceful shutdown with timeout

Workflow:
  Start → Lint → Test → Build → Success notification
       ↓ (if error)
       → Failure notification

Try it:
    python examples/workflows/ci_pipeline/ci_runner.py
"""
# ruff: noqa: T201

import asyncio
from pathlib import Path

from cmdorc import CommandOrchestrator, load_config


async def main():
    """Run a complete CI pipeline."""

    # Step 1: Load CI configuration
    config_path = Path(__file__).parent / "ci.toml"
    print(f"Loading CI pipeline configuration from {config_path.name}...")
    config = load_config(config_path)
    orchestrator = CommandOrchestrator(config)

    # Step 2: Display pipeline configuration
    commands = orchestrator.list_commands()
    print(f"\nPipeline stages: {', '.join(commands)}")

    # Step 3: Set up failure notifications (error handling)
    # In a real CI system, you might send alerts or create tickets
    def on_pipeline_failure(handle, context):
        """Called when any critical stage fails."""
        print("\n⚠️  Pipeline failure notification triggered")

    orchestrator.on_event("command_failed:*", on_pipeline_failure)

    # Step 4: Start the pipeline
    print("\nStarting CI pipeline...")
    await orchestrator.trigger("start")

    # Step 5: Wait for pipeline to complete
    # Monitor status while pipeline runs
    max_wait = 10.0  # seconds
    elapsed = 0.0
    check_interval = 0.5

    while elapsed < max_wait:
        await asyncio.sleep(check_interval)
        elapsed += check_interval

        # Check if any stages are still running
        active_handles = orchestrator.get_all_active_handles()
        if not active_handles:
            break

        # Show progress
        if int(elapsed) % 2 == 0:
            print(f"  [{elapsed:.1f}s] {len(active_handles)} stage(s) running...")

    # Step 6: Collect final results
    print("\n" + "=" * 50)
    print("PIPELINE RESULTS")
    print("=" * 50)

    pipeline_success = True
    for stage_name in commands:
        status = orchestrator.get_status(stage_name)
        # Check if stage ran and succeeded
        ran = status.state != "never_run"
        success = status.state == "success"

        if ran:
            symbol = "✓" if success else "✗"
            state_display = status.state.upper()
            print(f"{symbol} {stage_name:15} {state_display}")

            if not success:
                pipeline_success = False

    # Step 7: Show execution history for debugging
    print("\n" + "=" * 50)
    print("DETAILED HISTORY")
    print("=" * 50)

    for stage_name in commands:
        history = orchestrator.get_history(stage_name, limit=1)
        if history:
            result = history[0]
            duration = (
                f"{result.end_time - result.start_time:.2f}s"
                if result.start_time and result.end_time
                else "N/A"
            )
            print(f"{stage_name:15} run_id={result.run_id[:8]}... duration={duration}")

    # Step 8: Final status
    print("\n" + "=" * 50)
    if pipeline_success:
        print("✅ Pipeline completed successfully")
    else:
        print("❌ Pipeline failed - check stages above")
    print("=" * 50)
    # Step Clean up
    await orchestrator.shutdown(timeout=5.0, cancel_running=True)


if __name__ == "__main__":
    asyncio.run(main())
