"""
03_concurrency_policies.py - Concurrency control and retrigger policies

This example demonstrates:
- max_concurrent: 0 (unlimited), 1 (single), N (explicit limit)
- on_retrigger: "cancel_and_restart" vs "ignore"
- debounce_in_ms: Preventing rapid re-runs
- Race condition mitigation

Try it:
    python examples/advanced/03_concurrency_policies.py
"""
# ruff: noqa: T201

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, ConcurrencyLimitError, RunnerConfig


async def main():
    """Demonstrate concurrency policies."""

    # Step 1: Command with unlimited concurrency
    print("1. Unlimited Concurrency (max_concurrent=0)")
    print("   Running 5 instances in parallel...")

    unlimited_config = CommandConfig(
        name="Unlimited",
        command="echo 'Running'; sleep 0.3; echo 'Done'",
        triggers=["unlimited"],
        max_concurrent=0,  # Unlimited
    )

    config = RunnerConfig(commands=[unlimited_config], vars={})
    orchestrator = CommandOrchestrator(config)

    handles = []
    for i in range(5):
        h = await orchestrator.run_command("Unlimited")
        handles.append(h)
        print(f"   Started run {i + 1}")

    await asyncio.gather(*[h.wait(timeout=5.0) for h in handles])
    print("   ✓ All 5 runs completed\n")

    # Step 2: Single concurrency (max_concurrent=1)
    print("2. Single Concurrency (max_concurrent=1)")
    print("   Attempting 2 concurrent runs...")

    single_config = CommandConfig(
        name="Single",
        command="echo 'Task'; sleep 0.5; echo 'Done'",
        triggers=["single"],
        max_concurrent=1,
        on_retrigger="ignore",
    )

    config = RunnerConfig(commands=[single_config], vars={})
    orchestrator = CommandOrchestrator(config)

    try:
        h1 = await orchestrator.run_command("Single")
        print("   ✓ First run started")
        await asyncio.sleep(0.1)

        # Try second run - should fail
        h2 = await orchestrator.run_command("Single")
        print("   ✓ Second run started (unexpected!)")
    except ConcurrencyLimitError:
        print("   ✓ Second run rejected: limit exceeded\n")

    await h1.wait(timeout=5.0)

    # Step 3: cancel_and_restart policy
    print("3. cancel_and_restart Policy")
    print("   Restarting command when retriggered...")

    restart_config = CommandConfig(
        name="RestartTask",
        command="echo 'Starting'; sleep 2; echo 'Done'",
        triggers=["restart"],
        max_concurrent=1,
        on_retrigger="cancel_and_restart",
    )

    config = RunnerConfig(commands=[restart_config], vars={})
    orchestrator = CommandOrchestrator(config)

    h1 = await orchestrator.run_command("RestartTask")
    print(f"   Started: {h1.run_id[:8]}...")
    await asyncio.sleep(0.3)

    # Retrigger - should cancel first and start second
    h2 = await orchestrator.run_command("RestartTask")
    print(f"   Restarted: {h2.run_id[:8]}...")

    await h2.wait(timeout=5.0)
    await asyncio.sleep(0.1)

    print(f"   First run state: {h1.state}")
    print(f"   Second run state: {h2.state}")
    print("   ✓ First cancelled, second completed\n")

    # Step 4: Debounce demonstration
    print("4. Debounce (debounce_in_ms=1000)")
    print("   Preventing rapid re-runs...")

    debounce_config = CommandConfig(
        name="Debounced",
        command="echo 'Run'",
        triggers=["debounced"],
        debounce_in_ms=1000,
    )

    config = RunnerConfig(commands=[debounce_config], vars={})
    orchestrator = CommandOrchestrator(config)

    h1 = await orchestrator.run_command("Debounced")
    await h1.wait(timeout=5.0)
    print("   ✓ First run completed")

    try:
        # Immediate retrigger - should fail
        h2 = await orchestrator.run_command("Debounced")
        print("   ✓ Second run started (unexpected!)")
    except Exception:
        print("   ✓ Second run blocked by debounce\n")
    # Step Clean up
    await orchestrator.shutdown()
    print("✅ Concurrency policies demonstration complete")


if __name__ == "__main__":
    asyncio.run(main())
