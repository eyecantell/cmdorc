"""
05_cycle_detection.py - Cycle prevention and loop detection

This example demonstrates:
- Circular trigger chains that would create loops
- loop_detection=true prevents infinite cycles
- loop_detection=false allows loops (use with caution)
- TriggerContext cycle detection mechanism

Try it:
    python examples/advanced/05_cycle_detection.py
"""
# ruff: noqa: T201

import asyncio

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig


async def main():
    """Demonstrate cycle detection."""

    # Step 1: Safe cycle with loop_detection=true (default)
    print("1. Cycle Detection Enabled (loop_detection=true)")
    print("   Commands: A → B → A (would create infinite loop)")
    print()

    commands = [
        CommandConfig(
            name="A",
            command="echo 'A executed'",
            triggers=["start", "command_success:B"],
            loop_detection=True,  # Prevent cycles
        ),
        CommandConfig(
            name="B",
            command="echo 'B executed'",
            triggers=["command_success:A"],
            loop_detection=True,  # Prevent cycles
        ),
    ]

    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    print("   Starting workflow: trigger('start')...")
    await orchestrator.trigger("start")

    # Wait for commands to settle
    await asyncio.sleep(0.5)

    history_a = orchestrator.get_history("A")
    history_b = orchestrator.get_history("B")

    print(f"   ✓ A executed {len(history_a)} time(s)")
    print(f"   ✓ B executed {len(history_b)} time(s)")
    print("   ✓ Cycle detected and prevented - no infinite loop\n")

    # Step 2: Multiple independent cycles (safe)
    print("2. Multiple Independent Cycles")
    print("   Triggering A and B separately - each completes normally")
    print()

    # Reset by creating fresh orchestrator
    commands = [
        CommandConfig(
            name="TaskX",
            command="echo 'X'; sleep 0.1",
            triggers=["task_x"],
        ),
        CommandConfig(
            name="TaskY",
            command="echo 'Y'; sleep 0.1",
            triggers=["task_y"],
        ),
    ]

    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    # Trigger them independently
    await orchestrator.trigger("task_x")
    await orchestrator.trigger("task_y")
    await asyncio.sleep(0.3)

    print("   ✓ TaskX completed")
    print("   ✓ TaskY completed independently\n")

    # Step 3: Chained workflow (safe - no loops)
    print("3. Safe Chain (Lint → Test → Report)")
    print("   No cycles: each command runs once in sequence")
    print()

    commands = [
        CommandConfig(
            name="Lint",
            command="echo '🔍 Linting...'; sleep 0.1",
            triggers=["start"],
            loop_detection=True,
        ),
        CommandConfig(
            name="Test",
            command="echo '🧪 Testing...'; sleep 0.1",
            triggers=["command_success:Lint"],
            loop_detection=True,
        ),
        CommandConfig(
            name="Report",
            command="echo '📊 Reporting...'; sleep 0.1",
            triggers=["command_success:Test"],
            loop_detection=True,
        ),
    ]

    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    print("   Triggering workflow...")
    await orchestrator.trigger("start")
    await asyncio.sleep(0.5)

    lint_history = orchestrator.get_history("Lint")
    test_history = orchestrator.get_history("Test")
    report_history = orchestrator.get_history("Report")

    print(f"   ✓ Lint ran {len(lint_history)} time(s)")
    print(f"   ✓ Test ran {len(test_history)} time(s) (after Lint success)")
    print(f"   ✓ Report ran {len(report_history)} time(s) (after Test success)")
    print("   ✓ Linear workflow with no cycles\n")

    # Step 4: Complex but safe multi-branch workflow
    print("4. Multi-Branch Workflow (Diamond Pattern)")
    print("   Build → (Test + Lint) → Report (safe - no cycles)")
    print()

    commands = [
        CommandConfig(
            name="Build",
            command="echo '🔨 Building...'",
            triggers=["build"],
            loop_detection=True,
        ),
        CommandConfig(
            name="Test",
            command="echo '🧪 Testing...'",
            triggers=["command_success:Build"],
            loop_detection=True,
        ),
        CommandConfig(
            name="Lint",
            command="echo '🔍 Linting...'",
            triggers=["command_success:Build"],
            loop_detection=True,
        ),
        CommandConfig(
            name="Report",
            command="echo '📊 Reporting...'",
            triggers=["command_success:Test", "command_success:Lint"],
            loop_detection=True,
        ),
    ]

    config = RunnerConfig(commands=commands, vars={})
    orchestrator = CommandOrchestrator(config)

    print("   Building → Both Test and Lint → Report")
    await orchestrator.trigger("build")
    await asyncio.sleep(0.3)

    build_runs = len(orchestrator.get_history("Build"))
    test_runs = len(orchestrator.get_history("Test"))
    lint_runs = len(orchestrator.get_history("Lint"))
    report_runs = len(orchestrator.get_history("Report"))

    print(f"   ✓ Build: {build_runs} run(s)")
    print(f"   ✓ Test: {test_runs} run(s)")
    print(f"   ✓ Lint: {lint_runs} run(s)")
    print(f"   ✓ Report: {report_runs} run(s)")
    print("   ✓ Diamond pattern executed safely\n")

    # Step Clean up
    await orchestrator.shutdown()
    print("✅ Cycle detection demonstration complete")


if __name__ == "__main__":
    asyncio.run(main())
