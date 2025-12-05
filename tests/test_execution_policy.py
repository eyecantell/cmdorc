# tests/test_execution_policy.py
"""
Tests for ConcurrencyPolicy - the pure decision logic component.
"""

import pytest

from cmdorc import CommandConfig, ConcurrencyPolicy, RunResult


@pytest.fixture
def policy():
    """Create a fresh ConcurrencyPolicy instance."""
    return ConcurrencyPolicy()


@pytest.fixture
def basic_config():
    """Basic command config with default settings."""
    return CommandConfig(
        name="test",
        command="echo hello",
        triggers=["manual"],
        max_concurrent=1,
        on_retrigger="cancel_and_restart",
    )


class TestUnlimitedConcurrency:
    """Test max_concurrent=0 (unlimited)."""

    def test_allows_first_run(self, policy):
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=0,  # Unlimited
        )

        decision = policy.decide(config, active_runs=[])

        assert decision.allow is True
        assert decision.runs_to_cancel == []

    def test_allows_concurrent_runs(self, policy):
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=0,  # Unlimited
        )

        # Simulate 5 active runs
        active_runs = [RunResult(command_name="test") for _ in range(5)]

        decision = policy.decide(config, active_runs)

        assert decision.allow is True
        assert decision.runs_to_cancel == []


class TestSingleInstance:
    """Test max_concurrent=1 (default behavior)."""

    def test_allows_first_run(self, policy, basic_config):
        decision = policy.decide(basic_config, active_runs=[])

        assert decision.allow is True
        assert decision.runs_to_cancel == []

    def test_cancel_and_restart_cancels_existing(self, policy):
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=1,
            on_retrigger="cancel_and_restart",
        )

        active_run = RunResult(run_id=1, command_name="test")
        active_runs = [active_run]

        decision = policy.decide(config, active_runs)

        assert decision.allow is True
        assert decision.runs_to_cancel == [active_run]

    def test_ignore_rejects_new_run(self, policy):
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=1,
            on_retrigger="ignore",
        )

        active_run = RunResult(command_name="test")
        active_runs = [active_run]

        decision = policy.decide(config, active_runs)

        assert decision.allow is False
        assert decision.runs_to_cancel == []


class TestMultipleInstances:
    """Test max_concurrent > 1."""

    def test_allows_up_to_limit(self, policy):
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=3,
            on_retrigger="cancel_and_restart",
        )

        # No active runs
        decision = policy.decide(config, active_runs=[])
        assert decision.allow is True
        assert decision.runs_to_cancel == []

        # 1 active run
        active_runs = [RunResult(command_name="test")]
        decision = policy.decide(config, active_runs)
        assert decision.allow is True
        assert decision.runs_to_cancel == []

        # 2 active runs
        active_runs = [RunResult(command_name="test") for _ in range(2)]
        decision = policy.decide(config, active_runs)
        assert decision.allow is True
        assert decision.runs_to_cancel == []

    def test_cancel_and_restart_at_limit(self, policy):
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=3,
            on_retrigger="cancel_and_restart",
        )

        # At limit (3 active runs)
        active_runs = [RunResult(command_name="test") for _ in range(3)]

        decision = policy.decide(config, active_runs)

        assert decision.allow is True
        assert len(decision.runs_to_cancel) == 3
        assert decision.runs_to_cancel == active_runs

    def test_ignore_at_limit(self, policy):
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=3,
            on_retrigger="ignore",
        )

        # At limit (3 active runs)
        active_runs = [RunResult(command_name="test") for _ in range(3)]

        decision = policy.decide(config, active_runs)

        assert decision.allow is False
        assert decision.runs_to_cancel == []

    def test_cancel_and_restart_over_limit(self, policy):
        """Edge case: more active runs than max_concurrent (shouldn't happen, but handle it)."""
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=2,
            on_retrigger="cancel_and_restart",
        )

        # Over limit (3 active when max is 2)
        active_runs = [RunResult(command_name="test") for _ in range(3)]

        decision = policy.decide(config, active_runs)

        assert decision.allow is True
        assert len(decision.runs_to_cancel) == 3
        assert decision.runs_to_cancel == active_runs


class TestEdgeCases:
    """Test edge cases and defensive behavior."""

    def test_invalid_on_retrigger_defaults_to_ignore(self, policy):
        """Policy should handle invalid on_retrigger gracefully."""
        # Note: This shouldn't happen due to CommandConfig validation,
        # but the policy handles it defensively
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=1,
            on_retrigger="cancel_and_restart",  # Valid in config
        )

        # Manually break it for testing
        config.__dict__["on_retrigger"] = "invalid_value"

        active_run = RunResult(command_name="test")
        decision = policy.decide(config, [active_run])

        # Should default to "ignore" behavior
        assert decision.allow is False
        assert decision.runs_to_cancel == []

    def test_empty_active_runs_list(self, policy, basic_config):
        """Should handle empty active runs gracefully."""
        decision = policy.decide(basic_config, active_runs=[])

        assert decision.allow is True
        assert decision.runs_to_cancel == []

    def test_runs_to_cancel_is_copy(self, policy):
        """Ensure runs_to_cancel doesn't share references with input."""
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=1,
            on_retrigger="cancel_and_restart",
        )

        active_runs = [RunResult(command_name="test")]
        decision = policy.decide(config, active_runs)

        # Modify the decision's list
        decision.runs_to_cancel.clear()

        # Original list should be unchanged
        assert len(active_runs) == 1


class TestPolicyStateless:
    """Verify ConcurrencyPolicy is truly stateless."""

    def test_multiple_calls_independent(self, policy):
        """Multiple decide() calls should not affect each other."""
        config = CommandConfig(
            name="test",
            command="echo hello",
            triggers=["manual"],
            max_concurrent=1,
            on_retrigger="cancel_and_restart",
        )

        run1 = RunResult(command_name="test")
        run2 = RunResult(command_name="test")

        decision1 = policy.decide(config, [run1])
        decision2 = policy.decide(config, [run2])

        # Each decision should be independent
        assert decision1.allow is True
        assert decision2.allow is True
        assert decision1.runs_to_cancel == [run1]
        assert decision2.runs_to_cancel == [run2]

    def test_different_configs_independent(self, policy):
        """Different configs should not affect each other."""
        config1 = CommandConfig(
            name="cmd1",
            command="echo 1",
            triggers=["manual"],
            max_concurrent=1,
            on_retrigger="ignore",
        )

        config2 = CommandConfig(
            name="cmd2",
            command="echo 2",
            triggers=["manual"],
            max_concurrent=0,  # Unlimited
        )

        run1 = RunResult(command_name="cmd1")
        run2 = RunResult(command_name="cmd2")

        decision1 = policy.decide(config1, [run1])
        decision2 = policy.decide(config2, [run2])

        # config1 should ignore (at limit)
        assert decision1.allow is False

        # config2 should allow (unlimited)
        assert decision2.allow is True
