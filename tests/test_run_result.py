# tests/test_run_result.py

import asyncio
import time
from cmdorc import RunResult, RunState, ResolvedCommand


def test_initial_state():
    r = RunResult(command_name="build")
    assert r.state == RunState.PENDING
    assert r.success is None
    assert r.error is None
    assert r.output == ""
    assert r.start_time is None
    assert r.end_time is None
    assert not r.is_finished
    assert r.resolved_command is None
    assert isinstance(r.future, asyncio.Future)


def test_mark_running_sets_start_time_and_state():
    r = RunResult(command_name="test")
    r.mark_running()
    assert r.state == RunState.RUNNING
    assert r.start_time is not None
    assert not r.is_finished


def test_mark_success_transitions_state_and_finishes_future():
    r = RunResult(command_name="lint")
    r.mark_running()
    r.mark_success()

    assert r.state == RunState.SUCCESS
    assert r.success is True
    assert r.is_finished
    assert r.future.done()
    assert r.future.result() is r
    assert r.duration is not None


def test_mark_failed_sets_error_and_finishes_future():
    r = RunResult(command_name="compile")
    r.mark_running()
    r.mark_failed("Syntax error")

    assert r.state == RunState.FAILED
    assert r.success is False
    assert r.error == "Syntax error"
    assert r.is_finished
    assert r.future.done()


def test_mark_cancelled_sets_error_and_finishes_future():
    r = RunResult(command_name="deploy")
    r.mark_running()
    r.mark_cancelled("User interrupt")

    assert r.state == RunState.CANCELLED
    assert r.success is None
    assert r.error == "User interrupt"
    assert r.is_finished
    assert r.future.done()


def test_duration_ms_and_secs():
    r = RunResult(command_name="build")
    r.mark_running()
    time.sleep(0.01)  # ~10ms
    r.mark_success()

    assert r.duration_secs > 0
    assert r.duration_ms > 0
    assert "ms" in r.duration_str or "s" in r.duration_str


def test_repr_contains_key_fields():
    r = RunResult(command_name="test")
    rep = repr(r)
    assert "RunResult" in rep
    assert "cmd='test'" in rep


def test_resolved_command_round_trip():
    resolved = ResolvedCommand(
        command="echo hi",
        cwd="/tmp",
        env={"A": "1"},
        timeout_secs=5,
        vars={"x": "y"},
    )

    d = resolved.to_dict()

    assert d["command"] == "echo hi"
    assert d["cwd"] == "/tmp"
    assert d["env"] == {"A": "1"}
    assert d["timeout_secs"] == 5
    assert d["vars"] == {"x": "y"}


def test_to_dict_without_resolved_command():
    r = RunResult(command_name="t1")
    d = r.to_dict()

    assert d["command_name"] == "t1"
    assert d["resolved_command"] is None


def test_to_dict_with_resolved_command():
    r = RunResult(command_name="t2")
    r.resolved_command = ResolvedCommand(
        command="build",
        cwd="/home",
        env={"X": "2"},
        timeout_secs=None,
        vars={"v": "val"},
    )

    d = r.to_dict()
    rc = d["resolved_command"]
    assert rc["command"] == "build"
    assert rc["cwd"] == "/home"
    assert rc["env"] == {"X": "2"}
    assert rc["vars"] == {"v": "val"}
    assert rc["timeout_secs"] is None
