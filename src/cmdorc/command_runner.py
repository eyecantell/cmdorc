# cmdorc/command_runner.py
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from collections.abc import Callable

from .command_config import CommandConfig
from .command_status import CommandStatus
from .load_config import resolve_double_brace_vars
from .run_result import RunResult, RunState
from .runner_config import RunnerConfig

logger = logging.getLogger(__name__)


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

        self._callbacks: dict[str, list[Callable[[dict | None], None]]] = defaultdict(list)

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
        """Build map of trigger str -> commands to cancel when that trigger fires."""
        mapping: dict[str, list[CommandConfig]] = defaultdict(list)
        for cmd in self._command_configs.values():
            for t in cmd.cancel_on_triggers:
                mapping[t].append(cmd)
        return mapping

    def _trigger_with_cycle_detection(
        self,
        event_name: str,
        result: RunResult | None = None,
    ) -> None:
        """
        Trigger an event, propagating cycle detection context if available.
        Args:
            event_name: The trigger string to fire
            result: Optional RunResult with _seen list for cycle detection
        """
        if result and result._seen is not None:
            asyncio.create_task(self.trigger(event_name, _seen=result._seen.copy()))
        else:
            asyncio.create_task(self.trigger(event_name))

    def _resolve_template(self, template: str, *, max_nested_depth: int = 10) -> str:
        """
        Resolve double-brace {{ var }} templates using the runner's vars.
        Supports nested replacements up to `max_depth` to avoid infinite loops.
        """
        return self._resolve_template_with_vars(template, self.vars, max_nested_depth=max_nested_depth)
    
    def _resolve_template_with_vars(self, template: str, vars_dict: dict[str, str], *, max_nested_depth: int = 10) -> str:
        """
        Resolve double-brace {{ var }} templates using provided vars dict.
        Supports nested replacements up to `max_depth` to avoid infinite loops.
        """
        current = template
        for _ in range(max_nested_depth):
            new = resolve_double_brace_vars(current, vars_dict, max_depth=max_nested_depth)
            if new == current:
                return new
            current = new

        raise RecursionError(
            f"Exceeded max template expansion depth ({max_nested_depth}) "
            f"while resolving template: {template}"
        )
    
    def _should_start_new_run(self, cmd: CommandConfig) -> bool:
        """
        Check if a new run should start based on the command's retrigger policy.
        Side effect: Cancels existing runs if policy is 'cancel_and_restart'.
        
        Returns:
            True  → proceed with starting the new run
            False → do NOT start new run (policy was 'ignore')
        """
        live = self._live_runs[cmd.name]
        
        if cmd.max_concurrent <= 0 or len(live) < cmd.max_concurrent:
            return True  # No conflict

        if cmd.on_retrigger == "ignore":
            logger.debug(
                f"Command '{cmd.name}' already has {len(live)}/{cmd.max_concurrent} runs → ignoring new request"
            )
            return False

        # on_retrigger == "cancel_and_restart"
        logger.debug(
            f"Command '{cmd.name}' has {len(live)} live runs → cancelling due to 'cancel_and_restart'"
        )
        for run in live:
            run.cancel()
        
        return True

    def run_command(
        self, 
        name: str, 
        *,
        trigger_event: str | None = None,
        _seen: list[str] | None = None,
        **override_vars: str
    ) -> RunResult:
        """
        Start a command execution and return immediately with the RunResult.

        This is fire-and-forget — the command runs in the background.
        To wait for completion: `result = runner.run_command('test'); await result.task`

        All safety features remain active:
        - concurrency limits / retrigger policy
        - cancel_on_triggers
        - timeout
        - history tracking
        - command_started / command_success / etc. auto-events (with full cycle detection)
        - template variable resolution

        Args:
            name: Exact command name.
            trigger_event: Optional trigger that caused this run (for debugging).
            _seen: Internal cycle detection chain (do not use directly).
            **override_vars: One-shot template variable overrides for this run only.

        Returns:
            RunResult with a .task you can await if needed.

        Raises:
            ValueError: If command doesn't exist or retrigger policy prevents start.
        """
        if name not in self._command_configs:
            known = ", ".join(sorted(self._command_configs.keys()))
            raise ValueError(
                f"Command '{name}' not found. Available: {known or '(none)'}"
            )

        cmd = self._command_configs[name]
        
        # Check retrigger policy
        if not self._should_start_new_run(cmd):
            raise ValueError(
                f"Command '{name}' is already running and on_retrigger='ignore'."
            )

        # Create result with merged variables (runner vars + overrides)
        result = RunResult(trigger_event=trigger_event or f"run_command:{name}")
        result.command_name = name
        result._seen = _seen.copy() if _seen else None
        result.vars = {**self.vars, **override_vars}  # Snapshot variables for this run
        result.mark_running()

        # Emit command_started (cycle detection starts here)
        self._trigger_with_cycle_detection(f"command_started:{name}", result)

        # Start execution task
        task = asyncio.create_task(self._execute(cmd, result))
        result.task = task
        task.add_done_callback(
            lambda t, n=name, r=result: self._task_completed(n, r)
        )

        self._live_runs[name].append(result)
        
        return result

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
            cycle_path = " -> ".join(recent + [event_name])
            logger.warning(f"Trigger cycle detected! Preventing re-entry: {cycle_path}")
            return

        _seen.append(event_name)

        try:
            # ---- Cancel commands that have this trigger in cancel_on_triggers ----
            for cmd in self._cancel_trigger_map.get(event_name, []):
                for run in self._live_runs[cmd.name]:
                    run.cancel()

            # ---- Command dispatch for matching triggers ----
            for cmd in self._trigger_map.get(event_name, []):
                try:
                    self.run_command(
                        cmd.name,
                        trigger_event=event_name,
                        _seen=_seen
                    )
                except ValueError as e:
                    # Command couldn't start (e.g., on_retrigger='ignore')
                    logger.debug(f"Skipping command '{cmd.name}': {e}")

            # ---- External callbacks ----
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
    async def _execute(
        self, 
        cmd: CommandConfig, 
        result: RunResult,
        max_nested_depth: int = 10
    ) -> None:
        proc = None
        try:
            # --- Resolve command template using result's vars ---
            resolved_cmd = self._resolve_template_with_vars(
                cmd.command, 
                result.vars,
                max_nested_depth=max_nested_depth
            )
            logger.debug(f"Executing '{cmd.name}': {resolved_cmd}")

            # --- Start subprocess ---
            proc = await asyncio.create_subprocess_shell(
                resolved_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=result.vars["base_directory"],
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
                    result.output = await self._read_partial_output(proc)
                    await self._terminate_process(proc)
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
            logger.info(f"Command '{cmd.name}' ({result.run_id}) was cancelled in async context")
            result.output = await self._read_partial_output(proc)
            result.mark_cancelled()
            await self._terminate_process(proc)
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
                f"Command '{cmd_name}' ({result.run_id}) completed but result state is still RUNNING"
            )

        # Remove from live runs
        initial_count = len(self._live_runs[cmd_name])
        self._live_runs[cmd_name] = [
            r for r in self._live_runs[cmd_name] if r.run_id != result.run_id
        ]

        if len(self._live_runs[cmd_name]) == initial_count:
            logger.debug(
                f"Ignoring duplicate completion callback for '{cmd_name}' ({result.run_id})"
            )
            return

        # Store in history
        cfg = self._command_configs[cmd_name]
        if cfg.keep_history > 0:
            self._history[cmd_name].append(result)
            if len(self._history[cmd_name]) > cfg.keep_history:
                logger.debug(
                    f"Trimming history for command '{cmd_name}' to last {cfg.keep_history} runs"
                )
                self._history[cmd_name] = self._history[cmd_name][-cfg.keep_history :]

        # Auto-trigger completion events
        trigger_name = f"command_{result.state.value}:{cmd_name}"
        self._trigger_with_cycle_detection(trigger_name, result)

        if result.state in (RunState.SUCCESS, RunState.FAILED):
            finish_trigger = f"command_finished:{cmd_name}"
            self._trigger_with_cycle_detection(finish_trigger, result)

        logger.debug(
            f"Command '{cmd_name}' ({result.run_id}) completed with state: {result.state}. "
            f"{len(self._live_runs[cmd_name])} runs live. {len(self._history[cmd_name])} runs in history."
        )

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
        """Current status of the command (running → last run state → never_run) or a specific run if run_id provided."""
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
        return CommandStatus.NEVER_RUN

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
        if name not in self._command_configs:
            raise ValueError(f"Unknown command: {name}")
        return self._history[name].copy()

    def get_live_runs(self, name: str) -> list[RunResult]:
        if name not in self._command_configs:
            raise ValueError(f"Unknown command: {name}")
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

    def validate_templates(
        self, strict: bool = False, max_nested_depth: int = 10
    ) -> dict[str, list[str]]:
        """Validate all command templates — returns dict of command → list of errors."""
        unresolved: dict[str, list[str]] = {}
        for cmd in self._command_configs.values():
            try:
                self._resolve_template(cmd.command, max_nested_depth=max_nested_depth)
            except Exception as exc:
                logger.exception(f"Template validation error in command '{cmd.name}': {exc}")
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
                    f"Command '{name}' reached status: {current} after "
                    f"{asyncio.get_event_loop().time() - start:.2f}s"
                )
                return True
            await asyncio.sleep(0.01)
        return False

    async def wait_for_running(self, name: str, timeout: float = 5.0) -> bool:
        return await self.wait_for_status(name, CommandStatus.RUNNING, timeout)

    async def wait_for_not_running(self, name: str, timeout: float = 5.0) -> bool:
        return await self.wait_for_status(
            name,
            [CommandStatus.SUCCESS, CommandStatus.FAILED, CommandStatus.CANCELLED, CommandStatus.NEVER_RUN],
            timeout,
        )
    
    async def wait_for_cancelled(self, name: str, timeout: float = 5.0) -> bool:
        return await self.wait_for_status(name, CommandStatus.CANCELLED, timeout)

    async def _terminate_process(
        self,
        proc: asyncio.subprocess.Process,
        *,
        grace: float = 0.2,
    ) -> None:
        """
        Gracefully terminate a subprocess:
        - send SIGTERM
        - wait `grace` seconds
        - if still alive, send SIGKILL
        - always wait for the process to exit
        Never raises.
        """
        if proc is None:
            return

        try:
            if proc.returncode is None:
                proc.terminate()
                await asyncio.sleep(grace)
        except Exception:
            pass

        try:
            if proc.returncode is None:
                proc.kill()
        except Exception:
            pass

        try:
            await proc.wait()
        except Exception:
            pass

    async def _read_partial_output(self, proc):
        out = b""
        err = b""
        try:
            if proc and proc.stdout:
                out = await proc.stdout.read()
            if proc and proc.stderr:
                err = await proc.stderr.read()
        except Exception:
            pass

        return (out + err).decode(errors="replace")