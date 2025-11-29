# cmdorc/command_runner.py
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Literal, Optional

from .command_config import CommandConfig
from .runner_config import RunnerConfig


@dataclass
class RunResult:
    """
    Immutable result of a single command run.
    Stored in history and returned by get_result().
    """
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trigger_event: Optional[str] = None
    output: str = ""
    success: bool = False
    error: Optional[str] = None
    duration_secs: float = 0.0
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)
    state: Literal["success", "failed", "cancelled"] = "cancelled"


class CommandRunner:
    """
    The core orchestrator class.
    Manages configuration snapshots, trigger dispatching, async execution,
    state tracking, history, and host callbacks.
    """
    def __init__(self, config: RunnerConfig | List[CommandConfig], base_directory: Optional[str] = None):
        """
        Initialize with a RunnerConfig or raw list of CommandConfigs.
        Snapshots everything for immutability.
        If base_directory is provided, it overrides any config default.
        """
        if isinstance(config, list):
            config = RunnerConfig(commands=config)
        
        # Snapshot configs (immutable dataclasses already frozen)
        self._command_configs: Dict[str, CommandConfig] = {c.name: c for c in config.commands}
        
        # Mutable vars (defaults from config + overrides)
        self.vars: Dict[str, str] = config.vars.copy()
        self.vars["base_directory"] = base_directory or self.vars.get("base_directory", os.getcwd())
        
        # Build trigger map for fast dispatch
        self._trigger_map: Dict[str, List[CommandConfig]] = self._build_trigger_map()
        
        # Callback registry (for hosts)
        self._callbacks: Dict[str, List[Callable[[Optional[Dict]], None]]] = defaultdict(list)
        
        # State tracking
        self._states: Dict[str, Literal["idle", "running", "success", "failed", "cancelled"]] = {name: "idle" for name in self._command_configs}
        
        # Active tasks (for cancellation and concurrency checks)
        self._tasks: Dict[str, List[asyncio.Task]] = {name: [] for name in self._command_configs}
        
        # Results history
        self._results: Dict[str, List[RunResult]] = {name: [] for name in self._command_configs}
        
        # Cycle detection for recursion safety
        self._local = threading.local()

    def _build_trigger_map(self) -> Dict[str, List[CommandConfig]]:
        trigger_map = defaultdict(list)
        for cmd in self._command_configs.values():
            for trigger in cmd.triggers:
                trigger_map[trigger].append(cmd)
        return trigger_map

    def on_trigger(self, trigger_name: str, callback: Callable[[Optional[Dict]], None]):
        """Register a callback for a specific trigger string."""
        self._callbacks[trigger_name].append(callback)

    def off_trigger(self, trigger_name: str, callback: Callable[[Optional[Dict]], None]):
        """Unregister a callback (optional cleanup)."""
        self._callbacks[trigger_name] = [cb for cb in self._callbacks.get(trigger_name, []) if cb != callback]

    async def trigger(self, event_name: str) -> None:
        """Fire a trigger event — dispatch to commands and callbacks."""
        if not self._trigger_map.get(event_name) and not self._callbacks.get(event_name):
            return  # Early exit if nothing subscribed
        
        # Cycle detection
        if not hasattr(self._local, "active_events"):
            self._local.active_events = set()
        if event_name in self._local.active_events:
            logging.warning(f"Cycle detected for trigger '{event_name}' — skipping.")
            return
        self._local.active_events.add(event_name)
        
        try:
            # Dispatch to commands
            for cmd in self._trigger_map.get(event_name, []):
                running_tasks = self._tasks[cmd.name]
                running_count = len(running_tasks)
                
                # Auto-cancel check
                if running_count > 0 and event_name in cmd.cancel_on_triggers:
                    self.cancel_command(cmd.name)
                
                # Retrigger / concurrency check
                if running_count >= cmd.max_concurrent and cmd.max_concurrent > 0:
                    if cmd.on_retrigger == "ignore":
                        continue
                    # else "cancel_and_restart"
                    self.cancel_command(cmd.name)
                
                # Start new run
                task = asyncio.create_task(self._execute(cmd, event_name))
                self._tasks[cmd.name].append(task)
                self._states[cmd.name] = "running"  # Simplified; for multiples, could track per-run
            
            # Fire callbacks (after commands for consistency)
            payload: Optional[Dict] = None  # None for now; add if needed (e.g., {"triggered_commands": [...names]})
            for cb in self._callbacks.get(event_name, []):
                try:
                    if asyncio.iscoroutinefunction(cb):
                        asyncio.create_task(cb(payload))
                    else:
                        cb(payload)
                except Exception as e:
                    logging.warning(f"Callback error for '{event_name}': {e}")
        finally:
            self._local.active_events.remove(event_name)

    async def _execute(self, cmd: CommandConfig, trigger_event: str) -> None:
        run_id = str(uuid.uuid4())
        result = RunResult(run_id=run_id, trigger_event=trigger_event)
        start_time = datetime.datetime.now()

        proc = None
        try:
            resolved_cmd = cmd.command.format_map(self.vars)
            proc = await asyncio.create_subprocess_shell(
                resolved_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.vars["base_directory"],
            )

            if cmd.timeout_secs:
                await asyncio.wait_for(proc.wait(), timeout=cmd.timeout_secs)

            stdout, stderr = await proc.communicate()
            # No need to await proc.wait() again — communicate() already waited

            result.output = (stdout + stderr).decode(errors="replace")
            result.success = proc.returncode == 0
            result.state = "success" if result.success else "failed"

        except asyncio.TimeoutError:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            result.error = "Timeout exceeded"
            result.state = "failed"
        except asyncio.CancelledError:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            result.state = "cancelled"
            raise
        except Exception as e:
            result.error = str(e)
            result.state = "failed"
        finally:
            end_time = datetime.datetime.now()
            result.duration_secs = (end_time - start_time).total_seconds()
            result.timestamp = end_time

            # Cleanup tasks
            self._tasks[cmd.name] = [t for t in self._tasks[cmd.name] if not t.done()]

            # Store result
            self._results[cmd.name].append(result)
            if cmd.keep_history > 0:
                self._results[cmd.name] = self._results[cmd.name][-cmd.keep_history:]

            # Update state only when no tasks left
            if not self._tasks[cmd.name]:
                self._states[cmd.name] = result.state

            # Auto-trigger
            auto_event = f"command_{result.state}:{cmd.name}"
            await self.trigger(auto_event)

    def cancel_command(self, name: str) -> None:
        """Cancel all running instances of a command."""
        for task in self._tasks.get(name, []):
            task.cancel()

    def cancel_all(self) -> None:
        """Cancel all running commands."""
        for name in self._command_configs:
            self.cancel_command(name)

    def get_status(self, name: str) -> Literal["idle", "running", "success", "failed", "cancelled"]:
        """Get the current state of a command."""
        if name not in self._command_configs:
            raise ValueError(f"Unknown command '{name}'")
        return self._states[name]

    def get_result(self, name: str, run_id: Optional[str] = None) -> Optional[RunResult]:
        """Get the result of a specific run (by id) or the latest."""
        if name not in self._command_configs:
            raise ValueError(f"Unknown command '{name}'")
        history = self._results[name]
        if not history:
            return None
        if run_id:
            for res in history:
                if res.run_id == run_id:
                    return res
            raise ValueError(f"No run with id '{run_id}' for '{name}'")
        return history[-1]  # Latest

    def get_history(self, name: str) -> List[RunResult]:
        """Get the full history list for a command (up to keep_history)."""
        if name not in self._command_configs:
            raise ValueError(f"Unknown command '{name}'")
        return self._results[name].copy()  # Shallow copy for safety

    def get_commands_by_trigger(self, trigger_name: str) -> List[CommandConfig]:
        """Get all commands subscribed to a trigger."""
        return self._trigger_map.get(trigger_name, []).copy()

    def has_trigger(self, trigger_name: str) -> bool:
        """True if any command is subscribed to this trigger."""
        return bool(self._trigger_map.get(trigger_name))

    def set_vars(self, vars_dict: Dict[str, str]) -> None:
        """Bulk set/override template vars."""
        self.vars.update(vars_dict)

    def add_var(self, key: str, value: str) -> None:
        """Set a single template var."""
        self.vars[key] = value

    def validate_templates(self, strict: bool = False) -> Dict[str, str]:
        """Dry-run template resolution for all commands. Returns dict of unresolved per command."""
        unresolved = {}
        for cmd in self._command_configs.values():
            try:
                cmd.command.format_map(self.vars)
            except KeyError as e:
                unresolved[cmd.name] = str(e)
        if unresolved and strict:
            raise ValueError(f"Unresolved templates: {unresolved}")
        elif unresolved:
            logging.warning(f"Unresolved templates: {unresolved}")
        return unresolved