# cmdorc/execution_policy.py
"""
Pure decision logic for determining whether a new run should be allowed
and which existing runs (if any) need to be cancelled.

The policy enforces max_concurrent limits and on_retrigger behavior.
"""

from __future__ import annotations

import logging

from .command_config import CommandConfig
from .run_result import RunResult
from .types import NewRunDecision

logger = logging.getLogger(__name__)


class ExecutionPolicy:
    """
    Stateless policy engine that decides whether a new command run should start,
    and whether any existing runs should be cancelled first.
    
    The policy enforces:
    - max_concurrent limits (0 = unlimited, 1 = single instance, N = up to N concurrent)
    - on_retrigger behavior ("cancel_and_restart" or "ignore")
    """
    
    def decide(
        self,
        config: CommandConfig,
        active_runs: list[RunResult],
    ) -> NewRunDecision:
        """
        Decide whether a new run should be allowed and which (if any) runs to cancel.
        
        Args:
            config: The command configuration
            active_runs: Currently running instances of this command
            
        Returns:
            NewRunDecision with:
            - allow: True if new run should start
            - runs_to_cancel: List of active runs to cancel first
        """
        
        active_count = len(active_runs)
        
        # Case 1: Unlimited concurrency (max_concurrent = 0)
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
        if config.on_retrigger == "cancel_and_restart":
            logger.debug(
                f"Policy for '{config.name}': at limit ({active_count}/{config.max_concurrent}), "
                f"cancelling all active runs and starting new one"
            )
            return NewRunDecision(allow=True, runs_to_cancel=active_runs.copy())
        
        elif config.on_retrigger == "ignore":
            logger.debug(
                f"Policy for '{config.name}': at limit ({active_count}/{config.max_concurrent}), "
                f"ignoring new trigger"
            )
            return NewRunDecision(allow=False, runs_to_cancel=[])
        
        else:
            # This should never happen due to CommandConfig validation,
            # but handle it defensively
            logger.error(
                f"Policy for '{config.name}': unknown on_retrigger value '{config.on_retrigger}', "
                f"defaulting to 'ignore'"
            )
            return NewRunDecision(allow=False, runs_to_cancel=[])
    

    def should_run_on_trigger(
        self,
        config: CommandConfig,
        trigger_event: str,
    ) -> bool:
        """
        Check if a trigger event should cause a command to be run.
        
        Args:
            config: The command configuration
            trigger_event: The event that was triggered
            
        Returns:
            True if the trigger matches the command's triggers
        """
        should_run = trigger_event in config.triggers
        
        if should_run:
            logger.debug(
                f"Policy for '{config.name}': trigger '{trigger_event}' "
                f"matches triggers, will run command"
            )
        
        return should_run
    

    
    def should_cancel_on_trigger(
        self,
        config: CommandConfig,
        trigger_event: str,
    ) -> bool:
        """
        Check if a trigger event should cause cancellation of running instances.
        
        This is separate from on_retrigger behavior - it handles cancel_on_triggers.
        
        Args:
            config: The command configuration
            trigger_event: The event that was triggered
            
        Returns:
            True if all running instances of this command should be cancelled
        """
        should_cancel = trigger_event in config.cancel_on_triggers
        
        if should_cancel:
            logger.debug(
                f"Policy for '{config.name}': trigger '{trigger_event}' "
                f"matches cancel_on_triggers, will cancel active runs"
            )
        
        return should_cancel