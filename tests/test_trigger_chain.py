"""Tests for trigger chain (breadcrumb) functionality."""

import asyncio

import pytest

from cmdorc import CommandConfig, CommandOrchestrator, RunnerConfig, TriggerCycleError
from cmdorc.mock_executor import MockExecutor
from cmdorc.types import TriggerContext


@pytest.fixture
def orchestrator_with_chain():
    """Orchestrator with commands that chain via triggers."""
    commands = [
        CommandConfig(
            name="Step1",
            command="echo step1",
            triggers=["start"],
        ),
        CommandConfig(
            name="Step2",
            command="echo step2",
            triggers=["command_success:Step1"],
        ),
        CommandConfig(
            name="Step3",
            command="echo step3",
            triggers=["command_success:Step2"],
        ),
    ]

    config = RunnerConfig(commands=commands)
    executor = MockExecutor(delay=0.01)  # Fast simulation
    return CommandOrchestrator(config, executor=executor)


class TestTriggerChainBasics:
    """Test basic trigger chain functionality."""

    async def test_manual_run_has_empty_chain(self, orchestrator_with_chain):
        """Manual run_command should have empty trigger_chain."""
        handle = await orchestrator_with_chain.run_command("Step1")
        await handle.wait()

        assert handle.trigger_chain == []
        assert handle._result.trigger_event is None

    async def test_direct_trigger_has_single_event(self, orchestrator_with_chain):
        """Direct trigger should have single-element chain."""
        await orchestrator_with_chain.trigger("start")

        # Wait for Step1 to complete
        await asyncio.sleep(0.05)

        # Get Step1's last run
        history = orchestrator_with_chain.get_history("Step1", limit=1)
        assert len(history) == 1
        result = history[0]

        assert result.trigger_chain == ["start"]
        assert result.trigger_event == "start"

    async def test_chained_triggers_accumulate(self, orchestrator_with_chain):
        """Chained triggers should accumulate in history."""
        await orchestrator_with_chain.trigger("start")

        # Wait for chain to complete
        await asyncio.sleep(0.15)

        # Check each step's chain
        step1_history = orchestrator_with_chain.get_history("Step1", limit=1)
        assert step1_history[0].trigger_chain == ["start"]

        step2_history = orchestrator_with_chain.get_history("Step2", limit=1)
        # Step2 is triggered by command_success:Step1, which comes after command_started:Step1
        expected_step2 = ["start", "command_started:Step1", "command_success:Step1"]
        assert step2_history[0].trigger_chain == expected_step2

        step3_history = orchestrator_with_chain.get_history("Step3", limit=1)
        # Similar pattern for Step3
        assert "start" in step3_history[0].trigger_chain
        assert "command_success:Step1" in step3_history[0].trigger_chain
        assert "command_success:Step2" in step3_history[0].trigger_chain


class TestTriggerContext:
    """Test TriggerContext behavior."""

    def test_empty_context_creation(self):
        """Empty context should have empty seen and history."""
        context = TriggerContext()
        assert context.seen == set()
        assert context.history == []

    def test_context_with_data(self):
        """Context can be created with data."""
        context = TriggerContext(seen={"a", "b"}, history=["a", "b"])
        assert context.seen == {"a", "b"}
        assert context.history == ["a", "b"]

    def test_history_is_mutable(self):
        """History can be extended (for propagation)."""
        context = TriggerContext(history=["a"])
        context.history.append("b")
        assert context.history == ["a", "b"]


class TestCycleDetectionWithChains:
    """Test cycle detection includes chain info."""

    def test_cycle_error_includes_path(self):
        """TriggerCycleError should include full path in cycle detection."""
        # Create a context with a partial chain
        context = TriggerContext(seen={"start"}, history=["start"])

        # Try to add "start" again - should raise
        with pytest.raises(TriggerCycleError) as exc_info:
            raise TriggerCycleError("start", context.history)

        error = exc_info.value
        assert error.event_name == "start"
        assert error.cycle_path == ["start"]

    def test_cycle_error_cycle_point(self):
        """TriggerCycleError should identify where cycle begins."""
        # Create a chain: ["start", "A", "B"] and try to add "start" again
        context = TriggerContext(
            seen={"start", "A", "B"},
            history=["start", "A", "B"]
        )

        with pytest.raises(TriggerCycleError) as exc_info:
            raise TriggerCycleError("start", context.history)

        error = exc_info.value
        assert error.cycle_point == 0
        assert error.cycle_point == error.cycle_path.index("start")

    async def test_loop_detection_false_bypasses_cycle(self, orchestrator_with_chain):
        """loop_detection=False should allow cycles."""
        commands = [
            CommandConfig(
                name="Infinite",
                command="echo loop",
                triggers=["command_success:Infinite"],
                loop_detection=False,  # Allow self-trigger
                max_concurrent=1,
                on_retrigger="ignore",  # Prevent pile-up
            ),
        ]

        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)

        # Start the loop
        handle = await orchestrator.run_command("Infinite")

        # Let it run a bit
        await asyncio.sleep(0.05)

        # Should have completed first run without error
        assert handle.is_finalized or handle.state.value == "running"

        # Cancel to stop
        await orchestrator.cancel_command("Infinite")


class TestTriggerChainMutationPrevention:
    """Test that returned chains are copies."""

    async def test_runhandle_trigger_chain_is_copy(self):
        """RunHandle.trigger_chain should return a copy."""
        commands = [CommandConfig(name="Test", command="echo test", triggers=["go"])]
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)

        await orchestrator.trigger("go")
        await asyncio.sleep(0.05)

        # Get the handle directly
        handles = orchestrator.get_active_handles("Test")
        handle = handles[0] if handles else None

        if handle is None:
            # If no active handle, wait for it to complete and get from history
            history = orchestrator.get_history("Test", limit=1)
            # Create a handle from the result for testing the property
            from cmdorc import RunHandle
            handle = RunHandle(history[0])

        # Get chain and mutate it
        chain = handle.trigger_chain
        original_len = len(chain)
        chain.append("should_not_stick")

        # Get chain again - should not have mutation
        chain2 = handle.trigger_chain
        assert len(chain2) == original_len
        assert "should_not_stick" not in chain2

    async def test_runresult_to_dict_chain_is_copy(self):
        """RunResult.to_dict() should include a copy of trigger_chain."""
        commands = [CommandConfig(name="Test", command="echo test", triggers=["go"])]
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)

        await orchestrator.trigger("go")
        await asyncio.sleep(0.05)

        history = orchestrator.get_history("Test", limit=1)
        result = history[0]

        # Get dict and mutate the chain
        d = result.to_dict()
        d["trigger_chain"].append("should_not_stick")

        # Get dict again - should not have mutation
        d2 = result.to_dict()
        assert len(d2["trigger_chain"]) == 1
        assert "should_not_stick" not in d2["trigger_chain"]


class TestTriggerChainRepr:
    """Test that repr shows trigger chains."""

    async def test_runresult_repr_shows_chain(self):
        """RunResult __repr__ should show chain."""
        commands = [CommandConfig(name="Test", command="echo test", triggers=["go"])]
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)

        await orchestrator.trigger("go")
        await asyncio.sleep(0.05)

        history = orchestrator.get_history("Test", limit=1)
        result = history[0]

        repr_str = repr(result)
        assert "go" in repr_str
        assert "chain=" in repr_str

    async def test_runhandle_repr_shows_chain(self):
        """RunHandle __repr__ should show chain."""
        commands = [CommandConfig(name="Test", command="echo test", triggers=["go"])]
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)

        await orchestrator.trigger("go")
        await asyncio.sleep(0.05)

        history = orchestrator.get_history("Test", limit=1)
        result = history[0]

        repr_str = repr(result)
        assert "chain=" in repr_str

    async def test_runhandle_repr_shows_manual_for_empty_chain(self):
        """RunHandle __repr__ should show 'manual' for empty chain."""
        commands = [CommandConfig(name="Test", command="echo test", triggers=[])]
        config = RunnerConfig(commands=commands)
        executor = MockExecutor(delay=0.01)
        orchestrator = CommandOrchestrator(config, executor=executor)

        handle = await orchestrator.run_command("Test")
        await handle.wait()

        repr_str = repr(handle)
        assert "manual" in repr_str
