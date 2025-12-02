# cmdorc/command_runner.py
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .command_config import CommandConfig
from .runner_config import RunnerConfig
from .load_config import resolve_double_brace_vars


logger = logging.getLogger(__name__)


class RunState(Enum):
    """State of a single command execution (RunResult)."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CommandStatus(Enum):
    """Effective status of a command in the runner."""

    IDLE = "idle"
    RUNNING = RunState.RUNNING.value
    SUCCESS = RunState.SUCCESS.value
    FAILED = RunState.FAILED.value
    CANCELLED = RunState.CANCELLED.value


@dataclass
class RunResult:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    command_name: str = field(init=False)
    trigger_event: str | None = None

    output: str = ""
    success: bool | None = None
    error: str | None = None

    state: RunState = RunState.RUNNING

    # Timing
    task: asyncio.Task | None = None
    start_time: datetime.datetime | None = None
    end_time: datetime.datetime | None = None

    # Cycle detection propagation
    _seen: list[str] | None = None

    # Timing helpers
    @property
    def duration_secs(self) -> float | None:
        """Exact duration in seconds (float) or None if not finished."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def duration_str(self) -> str:
        """Human-readable duration – e.g. '1m 23s', '2.4s', '1h 5m'."""
        secs = self.duration_secs
        if secs is None:
            return "–"

        if secs < 60:
            return f"{secs:.1f}s"

        mins, secs = divmod(secs, 60)
        if mins < 60:
            return f"{int(mins)}m {secs:.0f}s"

        hrs, mins = divmod(mins, 60)
        return f"{int(hrs)}h {int(mins)}m"

    def cancel(self) -> None:
        if self.task and not self.task.done():
            logger.debug(f"Cancelling run for command '{self.command_name}' ({self.run_id})")
            self.mark_cancelled()
            self.task.cancel()

    # State transition helpers
    def mark_running(self) -> None:
        self.state = RunState.RUNNING
        self.start_time = datetime.datetime.now()
        logger.debug(f"Command '{self.command_name}' ({self.run_id}) started at {self.start_time}")

    def mark_success(self) -> None:
        self.state = RunState.SUCCESS
        self.success = True
        self._finalize()
        logger.debug(f"Command '{self.command_name}' ({self.run_id}) succeeded at {self.end_time}")

    def mark_failed(self, error: str) -> None:
        self.state = RunState.FAILED
        self.success = False
        self.error = error
        self._finalize()
        logger.debug(
            f"Command '{self.command_name}' ({self.run_id}) failed at {self.end_time} with error: {error}"
        )

    def mark_cancelled(self) -> None:
        self.state = RunState.CANCELLED
        self.success = False
        self.error = "Command was cancelled"
        self._finalize()
        logger.debug(f"Command '{self.command_name}' ({self.run_id}) cancelled at {self.end_time}")

    def _finalize(self) -> None:
        self.end_time = datetime.datetime.now()

    def __repr__(self) -> str:
        dur = f"{self.duration_secs:.2f}s" if self.duration_secs is not None else "–"

        return (
            f"RunResult(id={self.run_id[:8]}, cmd='{self.command_name}', "
            f"state={self.state}, dur={dur}, success={self.success})"
        )


class CommandRunner:
    def __init__(
        self,
        config: RunnerConfig | list[CommandConfig],
        base_directory: str | None = None,
    ):
        if isinstance(config, list):
            config = RunnerConfig(commands=config)

        self._command_configs: dict[str, CommandConfig] = {c.name: c for c in config.commands}
        if len(self._command_configs) != len(config.commands):
            raise ValueError("Duplicate command names detected")

        self.vars: dict[str, str] = config.vars.copy()
        self.vars["base_directory"] = base_directory or self.vars.get("base_directory", os.getcwd())

        # Build both trigger maps
        self._trigger_map = self._build_trigger_map()
        self._cancel_trigger_map = self._build_cancel_trigger_map()

        self._callbacks: dict[str, list[Callable[[dict] | None, None]]] = defaultdict(list)

        self._live_runs: dict[str, list[RunResult]] = defaultdict(list)
        self._history: dict[str, list[RunResult]] = defaultdict(list)

        logger.debug(f"CommandRunner initialized with {len(self._command_configs)} commands")

    # Internal helpers
    def _build_trigger_map(self) -> dict[str, list[CommandConfig]]:
        mapping: dict[str, list[CommandConfig]] = defaultdict(list)
        for cmd in self._command_configs.values():
            for t in cmd.triggers:
                mapping[t].append(cmd)
        return mapping

    def _build_cancel_trigger_map(self) -> dict[str, list[CommandConfig]]:
        """Build map of trigger -> commands to cancel when that trigger fires."""
        mapping: dict[str, list[CommandConfig]] = defaultdict(list)
        for cmd in self._command_configs.values():
            for t in cmd.cancel_on_triggers:
                mapping[t].append(cmd)
        return mapping

    def _resolve_template(self, template: str, *, max_depth: int = 10) -> str:
        """
        Resolve double-brace {{ var }} templates using the same logic as load_config.
        Supports nested replacements up to `max_depth` to avoid infinite loops.
        """
        current = template
        for _ in range(max_depth):
            new = resolve_double_brace_vars(current, self.vars, max_depth=max_depth)
            if new == current:
                return new
            current = new

        raise RecursionError(
            f"Exceeded max template expansion depth ({max_depth}) "
            f"while resolving template: {template}"
        )


    # Trigger registration
    def on_trigger(self, trigger_name: str, callback: Callable[[dict | None], None]):
        logger.debug(f"Registering callback for trigger: '{trigger_name}'")
        self._callbacks[trigger_name].append(callback)

    def off_trigger(self, trigger_name: str, callback: Callable[[dict | None], None]):
        logger.debug(f"Unregistering callback for trigger: '{trigger_name}'")
        self._callbacks[trigger_name] = [
            cb for cb in self._callbacks[trigger_name] if cb != callback
        ]

    # Core trigger dispatch
    async def trigger(self, event_name: str, _seen: list[str] | None = None) -> None:
        logger.debug(f"Trigger: '{event_name}'")

        # Check if there's anything to do
        if not (
            self._trigger_map.get(event_name)
            or self._cancel_trigger_map.get(event_name)
            or self._callbacks.get(event_name)
        ):
            return

        # === True cycle detection across chained and auto-triggered events ===
        if _seen is None:
            _seen = []

        if event_name in _seen:
            # Show recent part of the cycle for debuggability
            recent = _seen[-8:]
            cycle_path = " → ".join(recent + [event_name])
            logger.warning(f"Trigger cycle detected! Preventing re-entry: {cycle_path}")
            return

        _seen.append(event_name)

        try:
            # ---- Cancel commands with this trigger in cancel_on_triggers ----
            for cmd in self._cancel_trigger_map.get(event_name, []):
                live = self._live_runs[cmd.name]
                if live:
                    for run in live:
                        logger.debug(
                            f"Cancelling command '{cmd.name}' ({run.run_id}) due to cancel_on_trigger '{event_name}'"
                        )
                        run.cancel()

            # ---- Command dispatch for matching triggers --------------------------------
            for cmd in self._trigger_map.get(event_name, []):
                live = self._live_runs[cmd.name]
                logger.debug(
                    f"Evaluating command '{cmd.name}' for trigger '{event_name}': {len(live)} live runs"
                )

                # Concurrency / retrigger policy
                if cmd.max_concurrent > 0 and len(live) >= cmd.max_concurrent:
                    if cmd.on_retrigger == "ignore":
                        continue
                    # cancel_and_restart
                    for run in live:
                        logger.debug(
                            f"Cancelling command '{cmd.name}' ({run.run_id}) due to retrigger policy 'cancel_and_restart'"
                        )
                        run.cancel()

                # ---- Start new run -------------------------------------------------
                result = RunResult(trigger_event=event_name)
                result.command_name = cmd.name
                result._seen = _seen.copy()  # Propagate cycle chain to auto-triggers
                result.mark_running()

                task = asyncio.create_task(self._execute(cmd, result))
                result.task = task
                task.add_done_callback(
                    lambda t, name=cmd.name, res=result: self._task_completed(name, res)
                )

                self._live_runs[cmd.name].append(result)

            # ---- External callbacks -----------------------------------------------
            for cb in self._callbacks.get(event_name, []):
                try:
                    if asyncio.iscoroutinefunction(cb):
                        asyncio.create_task(cb(None))
                    else:
                        cb(None)
                except Exception as exc:
                    logger.warning(f"Trigger callback error ({event_name}): {exc}")

        finally:
            _seen.pop()

    # Execution
    async def _execute(self, cmd: CommandConfig, result: RunResult) -> None:
        proc = None
        try:
            # --- Resolve command template ---
            resolved_cmd = self._resolve_template(cmd.command)
            logger.debug(f"Executing '{cmd.name}': {resolved_cmd}")

            # --- Start subprocess ---
            proc = await asyncio.create_subprocess_shell(
                resolved_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.vars["base_directory"],
            )

            # --- Communicate with timeout (this handles wait + I/O together) ---
            if cmd.timeout_secs:
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=cmd.timeout_secs,
                    )
                except asyncio.TimeoutError:
                    logger.info(
                        f"Command '{cmd.name}' ({result.run_id}) timed out after "
                        f"{cmd.timeout_secs}s"
                    )
                    result.mark_failed("Timeout exceeded")

                    # Kill process and wait for it to exit
                    if proc.returncode is None:
                        proc.kill()
                        try:
                            await proc.wait()
                        except Exception:
                            pass
                    return
            else:
                stdout, stderr = await proc.communicate()

            # --- Decode output safely ---
            result.output = (stdout + stderr).decode(errors="replace")

            # --- Check exit code ---
            if proc.returncode != 0:
                raise RuntimeError(f"Exit code {proc.returncode}")

            result.mark_success()

        except asyncio.CancelledError:
            logger.info(
                f"Command '{cmd.name}' ({result.run_id}) was cancelled in async context"
            )
            # Partial capture if any stdout available
            out = b""
            err = b""
            try:
                if proc and proc.stdout:
                    out = await proc.stdout.read()
                if proc and proc.stderr:
                    err = await proc.stderr.read()
            except Exception:
                pass

            if out or err:
                try:
                    result.output = (out + err).decode(errors="replace")
                except Exception:
                    result.output = ""

            result.mark_cancelled()
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
                if proc.returncode is None:
                    proc.kill()
                try:
                    await proc.wait()
                except Exception:
                    pass

            # Allow task to finish without re-raising
            return

        except Exception as exc:
            logger.exception(f"Command '{cmd.name}' failed")
            result.mark_failed(str(exc))

        finally:
            # Log stderr if failed or cancelled
            if result.state in (RunState.FAILED, RunState.CANCELLED) and result.output.strip():
                logger.error(f"Error output from '{cmd.name}':\n{result.output}")


    def _task_completed(self, cmd_name: str, result: RunResult) -> None:
        # Validate state transition
        if result.state == RunState.RUNNING:
            raise ValueError(
                f"Command '{cmd_name}' ({result.run_id}) completed but result state is still RUNNING - should have been changed before calling _task_completed"
            )

        # Remove from live runs - if not found, this is a duplicate callback
        initial_count = len(self._live_runs[cmd_name])
        self._live_runs[cmd_name] = [
            r for r in self._live_runs[cmd_name] if r.run_id != result.run_id
        ]

        if len(self._live_runs[cmd_name]) == initial_count:
            # Run wasn't in live_runs, must be duplicate callback
            logger.debug(
                f"Ignoring duplicate completion callback for '{cmd_name}' ({result.run_id})"
            )
            return

        # Store in history (with retention)
        cfg = self._command_configs[cmd_name]

        if cfg.keep_history > 0:
            self._history[cmd_name].append(result)

            if len(self._history[cmd_name]) > cfg.keep_history:
                # Retain only the most recent runs as per keep_history setting
                logger.debug(
                    f"Trimming history for command '{cmd_name}' to last {cfg.keep_history} runs"
                )
                self._history[cmd_name] = self._history[cmd_name][-cfg.keep_history :]

        # Auto-trigger completion events with propagated seen set
        trigger_name = f"command_{result.state.value}:{cmd_name}"
        if result._seen is not None:
            asyncio.create_task(self.trigger(trigger_name, _seen=result._seen.copy()))
        else:
            asyncio.create_task(self.trigger(trigger_name))

        logger.debug(
            f"Command '{cmd_name}' ({result.run_id}) completed with state: {result.state}. {len(self._live_runs[cmd_name])} runs live. {len(self._history[cmd_name])} runs in history."
        )
        logger.debug(
            f"Command '{cmd_name}' ({result.run_id}) history is {[i.run_id + ': ' + i.state.value for i in self._history[cmd_name]]}"
        )
        logger.debug(f"Auto-triggered '{trigger_name}' with inherited cycle detection")

    # Control
    def cancel_command(self, name: str) -> None:
        logger.debug(f"Cancelling command: {name}")
        for run in self._live_runs.get(name, []):
            run.cancel()

    def cancel_all(self) -> None:
        logger.debug("Cancelling all commands")
        for runs in self._live_runs.values():
            for run in runs:
                run.cancel()

    # Queries
    def get_status(self, name: str, run_id: str | None = None) -> CommandStatus:
        """Current status of the command (running → last run state → idle) or a specific run if run_id provided."""
        if name not in self._command_configs:
            raise ValueError(f"Unknown command: {name}")

        if run_id:
            result = self.get_result(name, run_id)
            if result is None:
                raise ValueError(f"Run not found: {run_id}")
            return CommandStatus(result.state.value)

        if self._live_runs[name]:
            return CommandStatus.RUNNING

        if self._history[name]:
            return CommandStatus(self._history[name][-1].state.value)
        return CommandStatus.IDLE

    def get_result(self, name: str, run_id: str | None = None) -> RunResult | None:
        if name not in self._command_configs:
            raise ValueError(f"Unknown command: {name}")

        if run_id:
            for runs in (self._live_runs[name], self._history[name]):
                for r in runs:
                    if r.run_id == run_id:
                        return r
            raise ValueError(f"Run not found: {run_id}")

        # latest = live first, then history
        if self._live_runs[name]:
            return self._live_runs[name][-1]
        if self._history[name]:
            return self._history[name][-1]
        return None

    def get_history(self, name: str) -> list[RunResult]:
        return self._history[name].copy()

    def get_live_runs(self, name: str) -> list[RunResult]:
        return self._live_runs[name].copy()

    # Introspection
    def get_commands_by_trigger(self, trigger_name: str) -> list[CommandConfig]:
        """Get commands that will START when this trigger fires."""
        return self._trigger_map.get(trigger_name, []).copy()

    def get_commands_by_cancel_trigger(self, trigger_name: str) -> list[CommandConfig]:
        """Get commands that will be CANCELLED when this trigger fires."""
        return self._cancel_trigger_map.get(trigger_name, []).copy()

    def has_trigger(self, trigger_name: str) -> bool:
        """Check if this trigger will START any commands."""
        return trigger_name in self._trigger_map

    def has_cancel_trigger(self, trigger_name: str) -> bool:
        """Check if this trigger will CANCEL any commands."""
        return trigger_name in self._cancel_trigger_map

    def has_callback(self, trigger_name: str) -> bool:
        """Check if this trigger has any registered callbacks."""
        return trigger_name in self._callbacks

    def has_any_handler(self, trigger_name: str) -> bool:
        """Check if this trigger will do ANYTHING (start commands, cancel commands, or invoke callbacks)."""
        return (
            self.has_trigger(trigger_name)
            or self.has_cancel_trigger(trigger_name)
            or self.has_callback(trigger_name)
        )

    # Variable handling
    def set_vars(self, vars_dict: dict[str, str]) -> None:
        self.vars.update(vars_dict)

    def add_var(self, key: str, value: str) -> None:
        self.vars[key] = value

    def validate_templates(self, strict: bool = False) -> dict[str, list[str]]:
        """Validate all command templates – returns dict of command → list of errors."""
        unresolved: dict[str, list[str]] = {}
        for cmd in self._command_configs.values():
            try:
                self._resolve_template(cmd.command)
            except Exception as exc:
                unresolved.setdefault(cmd.name, []).append(str(exc))

        if unresolved and strict:
            raise ValueError(f"Unresolved templates: {unresolved}")
        return unresolved

    async def wait_for_status(
        self,
        name: str,
        status: CommandStatus | list[CommandStatus],
        timeout: float = 5.0,
    ) -> bool:
        """
        Wait until a command reaches one of the desired statuses.
        Returns True if reached, False if timeout.
        """
        if isinstance(status, CommandStatus):
            status = [status]

        start = asyncio.get_running_loop().time()
        deadline = start + timeout
        while asyncio.get_running_loop().time() < deadline:
            current = self.get_status(name)
            if current in status:
                logger.debug(
                    f"Command '{name}' ({self.get_result(name).run_id if self.get_result(name) else 'unknown'}) reached status: {current} after {asyncio.get_event_loop().time() - start:.2f}s"
                )
                return True
            await asyncio.sleep(0.01)  # 10ms polling – fast and responsive
        return False

    async def wait_for_running(self, name: str, timeout: float = 5.0) -> bool:
        return await self.wait_for_status(name, CommandStatus.RUNNING, timeout)

    async def wait_for_idle(self, name: str, timeout: float = 5.0) -> bool:
        return await self.wait_for_status(name, CommandStatus.IDLE, timeout)

    async def wait_for_cancelled(self, name: str, timeout: float = 5.0) -> bool:
        return await self.wait_for_status(name, CommandStatus.CANCELLED, timeout)
