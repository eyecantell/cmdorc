# cmdorc/concurrency_policy.py
"""
Pure decision logic for determining whether a new run should be allowed
and which existing runs (if any) need to be cancelled first.

Pure decision logic for concurrency, retrigger policies, and debounce.

This module contains stateless functions to decide whether to start new command runs,
which existing runs to cancel, and whether debounce prevents a start.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .command_config import CommandConfig
from .run_result import RunResult
from .types import NewRunDecision

logger = logging.getLogger(__name__)


class ConcurrencyPolicy:
    """
    Stateless policy engine that decides whether a new command run should start,
    and whether any existing runs should be cancelled first.

    The policy enforces:
    - max_concurrent limits (0 = unlimited, 1 = single instance, N = up to N concurrent)
    - on_retrigger behavior ("cancel_and_restart" or "ignore")
    """

    @staticmethod
    def decide(
        config: CommandConfig,
        active_runs: list[RunResult],
        last_start_time: datetime | None = None,
    ) -> NewRunDecision:
        """
        Decide if a new run should start, considering debounce, max_concurrent, and on_retrigger.

        This is a pure function: deterministic based on inputs, no side effects.

        Debounce is checked first (from last start time, regardless of outcome).
        If debounced, immediately deny without considering concurrency.

        Then, evaluate concurrency:
        - If under max_concurrent (or unlimited), allow.
        - If at/above limit:
          - "ignore": deny new run.
          - "cancel_and_restart": allow, but cancel all active runs.

        Args:
            config: The command configuration with policy settings.
            active_runs: List of currently RUNNING RunResults (filtered by caller).
            last_start_time: Timestamp of the last run start, or None if never run.

        Returns:
            NewRunDecision indicating if allowed and which runs to cancel.

        Raises:
            ValueError: If on_retrigger is invalid.
        """
        # Check debounce first: prevent rapid starts regardless of concurrency
        if config.debounce_in_ms > 0 and last_start_time is not None:
            elapsed_ms = int((datetime.now() - last_start_time).total_seconds() * 1000)
            if elapsed_ms < config.debounce_in_ms:
                logger.debug(
                    f"Policy for '{config.name}': debounced ({elapsed_ms:.0f}ms < {config.debounce_in_ms}ms)"
                )
                return NewRunDecision(
                    allow=False,
                    disallow_reason="debounce",
                    elapsed_ms=elapsed_ms,
                    runs_to_cancel=[],
                )

        active_count = len(active_runs)

        # Case 1: Unlimited concurrency: always allow
        if config.max_concurrent == 0:
            logger.debug(
                f"Policy for '{config.name}': unlimited concurrency, "
                f"allowing new run ({active_count} already active)"
            )
            return NewRunDecision(allow=True, runs_to_cancel=[])

        # Case 2: Under the limit - always allow
        if active_count < config.max_concurrent:
            logger.debug(
                f"Policy for '{config.name}': under limit "
                f"({active_count}/{config.max_concurrent}), allowing new run"
            )
            return NewRunDecision(allow=True, runs_to_cancel=[])

        # Case 3: At or over limit - check on_retrigger policy
        if config.on_retrigger == "ignore":
            logger.debug(
                f"Policy for '{config.name}': at limit ({active_count}/{config.max_concurrent}), "
                f"ignoring new trigger"
            )
            return NewRunDecision(
                allow=False, disallow_reason="concurrency_limit", runs_to_cancel=[]
            )
        elif config.on_retrigger == "cancel_and_restart":
            logger.debug(
                f"Policy for '{config.name}': at limit ({active_count}/{config.max_concurrent}), "
                f"cancelling all active runs and starting new one"
            )
            return NewRunDecision(allow=True, runs_to_cancel=active_runs.copy())
        else:
            raise ValueError(f"Invalid on_retrigger value: {config.on_retrigger}")
