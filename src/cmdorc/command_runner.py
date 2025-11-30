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

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """
    Single source of truth for a command execution.
    Created when a command starts, lives through running → completion,
    then moved to history.
    """
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    command_name: str = field(init=False)
    trigger_event: Optional[str] = None

    output: str = ""
    success: Optional[bool] = None
    error: Optional[str] = None
    duration_secs: float = 0.0
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)

    state: Literal["running", "success", "failed", "cancelled"] = "running"

    # Live execution tracking
    task: Optional[asyncio.Task] = None
    start_time: Optional[datetime.datetime] = None

    def mark_running(self) -> None:
        self.state = "running"
        self.start_time = datetime.datetime.now()
        self.timestamp = datetime.datetime.now()

    def mark_success(self) -> None:
        self.state = "success"
        self.success = True
        self._finalize()

    def mark_failed(self, error: str) -> None:
        self.state = "failed"
        self.success = False
        self.error = error
        self._finalize()

    def mark_cancelled(self) -> None:
        self.state = "cancelled"
        self.success = False
        self.error = "Command was cancelled"
        self._finalize()

    def _finalize(self) -> None:
        if self.start_time:
            self.duration_secs = (datetime.datetime.now() - self.start_time).total_seconds()
        self.timestamp = datetime.datetime.now()


class CommandRunner:
    """
    Lightweight, async-first command orchestrator.
    All state is centralized in RunResult objects.
    """

    def __init__(
        self,
        config: RunnerConfig | List[CommandConfig],
        base_directory: Optional[str] = None,
    ):
        if isinstance(config, list):
            config = RunnerConfig(commands=config)

        # Immutable config snapshot
        self._command_configs: Dict[str, CommandConfig] = {
            c.name: c for c in config.commands
        }

        # Template variables
        self.vars: Dict[str, str] = config.vars.copy()
        self.vars["base_directory"] = base_directory or self.vars.get(
            "base_directory", os.getcwd()
        )

        # Trigger → list of commands
        self._trigger_map: Dict[str, List[CommandConfig]] = self._build_trigger_map()

        # Callbacks for external triggers
        self._callbacks: Dict[str, List[Callable[[Optional[Dict]], None]]] = defaultdict(
            list
        )

        # Live + completed runs
        self._live_runs: Dict[str, List[RunResult]] = defaultdict(list)
        self._history: Dict[str, List[RunResult]] = defaultdict(list)

        # Cycle detection
        self._local = threading.local()

        logger.debug(
            f"CommandRunner initialized with commands: {list(self._command_configs.keys())}"
        )

    def _build_trigger_map(self) -> Dict[str, List[CommandConfig]]:
        trigger_map: Dict[str, List[CommandConfig]] = defaultdict(list)
        for cmd in self._command_configs.values():
            for trigger in cmd.triggers:
                trigger_map[trigger].append(cmd)
        return trigger_map

    # ------------------------------------------------------------------ #
    # Trigger registration
    # ------------------------------------------------------------------ #
    def on_trigger(self, trigger_name: str, callback: Callable[[Optional[Dict]], None]):
        self._callbacks[trigger_name].append(callback)

    def off_trigger(self, trigger_name: str, callback: Callable[[Optional[Dict]], None]):
        self._callbacks[trigger_name] = [
            cb for cb in self._callbacks[trigger_name] if cb != callback
        ]

    # ------------------------------------------------------------------ #
    # Core trigger dispatch
    # ------------------------------------------------------------------ #
    async def trigger(self, event_name: str) -> None:
        logger.debug(f"Trigger event: {event_name}")

        if not self._trigger_map.get(event_name) and not self._callbacks.get(event_name):
            logger.debug(f"No listeners for trigger '{event_name}'")
            return

        # Cycle detection
        if not hasattr(self._local, "active_events"):
            self._local.active_events = set()
        if event_name in self._local.active_events:
            logger.warning(f"Cycle detected on trigger '{event_name}' — skipping")
            return
        self._local.active_events.add(event_name)

        try:
            # Dispatch to commands
            for cmd in self._trigger_map.get(event_name, []):
                live = self._live_runs[cmd.name]

                # Auto-cancel policy
                if event_name in cmd.cancel_on_triggers and live:
                    logger.debug(
                        f"Auto-cancelling running '{cmd.name}' due to trigger '{event_name}'"
                    )
                    for run in live:
                        if run.task:
                            run.task.cancel()
                    continue  # skip starting new

                # Concurrency + retrigger policy
                if cmd.max_concurrent > 0 and len(live) >= cmd.max_concurrent:
                    if cmd.on_retrigger == "ignore":
                        logger.debug(
                            f"Ignoring retrigger of '{cmd.name}' (max_concurrent reached)"
                        )
                        continue
                    else:  # cancel_and_restart
                        logger.debug(
                            f"Cancelling old runs of '{cmd.name}' to allow restart"
                        )
                        for run in live:
                            if run.task:
                                run.task.cancel()

                # Start new run
                result = RunResult(trigger_event=event_name)
                result.command_name = cmd.name
                result.mark_running()

                task = asyncio.create_task(self._execute(cmd, result))
                result.task = task
                task.add_done_callback(
                    lambda t: self._task_completed(cmd.name, result)
                )

                self._live_runs[cmd.name].append(result)
                logger.debug(f"Started '{cmd.name}' (run_id={result.run_id})")

            # Fire callbacks (after command dispatch)
            payload: Optional[Dict] = None
            for cb in self._callbacks.get(event_name, []):
                try:
                    if asyncio.iscoroutinefunction(cb):
                        asyncio.create_task(cb(payload))
                    else:
                        cb(payload)
                except Exception as exc:
                    logger.warning(f"Callback error on '{event_name}': {exc}")

        finally:
            self._local.active_events.remove(event_name)

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    async def _execute(self, cmd: CommandConfig, result: RunResult) -> None:
        proc = None
        try:
            resolved_cmd = cmd.command.format_map(self.vars)
            logger.debug(f"Executing '{cmd.name}': {resolved_cmd}")

            proc = await asyncio.create_subprocess_shell(
                resolved_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.vars["base_directory"],
            )

            if cmd.timeout_secs:
                await asyncio.wait_for(proc.wait(), timeout=cmd.timeout_secs)

            stdout, stderr = await proc.communicate()
            combined = (stdout + stderr).decode(errors="replace")
            result.output = combined
            logger.debug(f"Command '{cmd.name}' completed normally")

            result.mark_success()

        except asyncio.TimeoutError:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            result.mark_failed("Timeout exceeded")

        except asyncio.CancelledError:
            logger.debug(f"Command '{cmd.name}' was cancelled")
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            result.mark_cancelled()
            raise  # let task be marked cancelled

        except Exception as exc:
            logger.exception(f"Unexpected error in '{cmd.name}'")
            result.mark_failed(str(exc))

    def _task_completed(self, cmd_name: str, result: RunResult) -> None:
        """Called via done callback — moves run from live → history."""
        # Remove from live runs
        self._live_runs[cmd_name] = [
            r for r in self._live_runs[cmd_name] if r.run_id != result.run_id
        ]

        # Add to history (with retention)
        cmd_cfg = self._command_configs[cmd_name]
        self._history[cmd_name].append(result)
        if cmd_cfg.keep_history > 0:
            self._history[cmd_name] = self._history[cmd_name][-cmd_cfg.keep_history :]

        # Auto-trigger completion events
        auto_event = f"command_{result.state}:{cmd_name}"
        asyncio.create_task(self.trigger(auto_event))

    # ------------------------------------------------------------------ #
    # Control
    # ------------------------------------------------------------------ #
    def cancel_command(self, name: str) -> None:
        """Cancel all running instances of a command."""
        for run in self._live_runs.get(name, []):
            if run.task and not run.task.done():
                run.task.cancel()
        logger.debug(f"Requested cancellation of all running '{name}'")

    def cancel_all(self) -> None:
        for runs in self._live_runs.values():
            for run in runs:
                if run.task and not run.task.done():
                    run.task.cancel()
        logger.debug("Requested cancellation of all running commands")

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def get_status(self, name: str) -> Literal["idle", "running", "success", "failed", "cancelled"]:
        if name not in self._command_configs:
            raise ValueError(f"Unknown command '{name}'")

        if self._live_runs[name]:
            return "running"

        hist = self._history[name]
        return hist[-1].state if hist else "idle"

    def get_result(
        self, name: str, run_id: Optional[str] = None
    ) -> Optional[RunResult]:
        if name not in self._command_configs:
            raise ValueError(f"Unknown command '{name}'")

        if run_id:
            # Search live first, then history
            for runs in (self._live_runs[name], self._history[name]):
                for r in runs:
                    if r.run_id == run_id:
                        return r
            raise ValueError(f"Run ID {run_id} not found for command '{name}'")

        # Latest run (live takes precedence)
        if self._live_runs[name]:
            return self._live_runs[name][-1]
        if self._history[name]:
            return self._history[name][-1]
        return None

    def get_history(self, name: str) -> List[RunResult]:
        if name not in self._command_configs:
            raise ValueError(f"Unknown command '{name}'")
        return self._history[name].copy()

    def get_live_runs(self, name: str) -> List[RunResult]:
        if name not in self._command_configs:
            raise ValueError(f"Unknown command '{name}'")
        return self._live_runs[name].copy()

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    def get_commands_by_trigger(self, trigger_name: str) -> List[CommandConfig]:
        return self._trigger_map.get(trigger_name, []).copy()

    def has_trigger(self, trigger_name: str) -> bool:
        return bool(self._trigger_map.get(trigger_name))

    # ------------------------------------------------------------------ #
    # Vars & validation
    # ------------------------------------------------------------------ #
    def set_vars(self, vars_dict: Dict[str, str]) -> None:
        self.vars.update(vars_dict)

    def add_var(self, key: str, value: str) -> None:
        self.vars[key] = value

    def validate_templates(self, strict: bool = False) -> Dict[str, str]:
        unresolved = {}
        for cmd in self._command_configs.values():
            try:
                cmd.command.format_map(self.vars)
            except KeyError as e:
                unresolved[cmd.name] = str(e)
        if unresolved and strict:
            raise ValueError(f"Unresolved template vars: {unresolved}")
        elif unresolved:
            logger.warning(f"Unresolved template vars: {unresolved}")
        return unresolved