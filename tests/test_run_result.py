# tests/test_run_result.py

import datetime
import time

from cmdorc import ResolvedCommand, RunResult, RunState
from cmdorc.run_result import _format_relative_time


def test_initial_state():
    r = RunResult(command_name="build")
    assert r.state == RunState.PENDING
    assert r.success is None
    assert r.error is None
    assert r.output == ""
    assert r.start_time is None
    assert r.end_time is None
    assert not r.is_finalized
    assert r.resolved_command is None


def test_mark_running_sets_start_time_and_state():
    r = RunResult(command_name="test")
    r.mark_running()
    assert r.state == RunState.RUNNING
    assert r.start_time is not None
    assert not r.is_finalized


def test_mark_success_transitions_state():
    r = RunResult(command_name="lint")
    r.mark_running()
    r.mark_success()

    assert r.state == RunState.SUCCESS
    assert r.success is True
    assert r.is_finalized
    assert r.duration is not None


def test_mark_failed_sets_error():
    r = RunResult(command_name="compile")
    r.mark_running()
    r.mark_failed("Syntax error")

    assert r.state == RunState.FAILED
    assert r.success is False
    assert r.error == "Syntax error"
    assert r.is_finalized


def test_mark_cancelled_sets_error():
    r = RunResult(command_name="deploy")
    r.mark_running()
    r.mark_cancelled()

    assert r.state == RunState.CANCELLED
    assert r.success is None
    assert r.is_finalized


def test_duration_secs():
    r = RunResult(command_name="build")
    r.mark_running()
    time.sleep(0.01)  # ~10ms
    r.mark_success()

    assert r.duration_secs > 0
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


def test_mark_with_comment():
    r = RunResult(command_name="example")
    r.mark_running(comment="Starting run")
    assert r.comment == "Starting run"
    r.mark_success(comment="Run succeeded")
    assert r.comment == "Run succeeded"
    r.mark_failed("Error occurred", comment="Run failed")
    assert r.comment == "Run failed"
    r.mark_cancelled(comment="Run cancelled")
    assert r.comment == "Run cancelled"


def test_mark_without_comment():
    r = RunResult(command_name="example2")
    r.mark_running()
    assert r.comment == ""
    r.mark_success()
    assert r.comment == ""
    r.mark_failed("Some error")
    assert r.comment == ""
    r.mark_cancelled()
    assert r.comment == ""


def test_mark_with_none_comment():
    r = RunResult(command_name="example3")
    r.mark_running(comment=None)
    assert r.comment == ""
    r.mark_success(comment=None)
    assert r.comment == ""
    r.mark_failed("Another error", comment=None)
    assert r.comment == ""
    r.mark_cancelled(comment=None)
    assert r.comment == ""


def test_duration_without_start_time():
    r = RunResult(command_name="no_start")
    assert r.duration is None
    assert r.duration_secs is None
    assert r.duration_str == "-"

    r.mark_cancelled()
    assert r.duration == datetime.timedelta(0)


def test_duration_str_formatting():
    r = RunResult(command_name="format_test")
    r.start_time = datetime.datetime.now() - datetime.timedelta(seconds=1.5)
    r.mark_success()
    assert "s" in r.duration_str
    assert float(r.duration_str.replace("s", "")) >= 1.5

    r.start_time = datetime.datetime.now() - datetime.timedelta(minutes=1.5)
    r.mark_success()
    assert "s" in r.duration_str
    assert "m" in r.duration_str
    assert float(r.duration_str.replace("m", "").replace("s", "").replace(" ", "")) >= 130

    r.start_time = datetime.datetime.now() - datetime.timedelta(hours=1.5)
    r.mark_success()
    assert "h" in r.duration_str
    assert "m" in r.duration_str
    assert float(r.duration_str.replace("h", "").replace("m", "").replace(" ", "")) >= 130


# ============================================================================
# Tests for _format_relative_time helper
# ============================================================================


def test_format_relative_time_milliseconds():
    assert _format_relative_time(0.5) == "500ms"
    assert _format_relative_time(0.001) == "1ms"
    assert _format_relative_time(0.999) == "999ms"


def test_format_relative_time_seconds():
    assert _format_relative_time(1.0) == "1.0s"
    assert _format_relative_time(30.5) == "30.5s"
    assert _format_relative_time(59.9) == "59.9s"


def test_format_relative_time_minutes():
    assert _format_relative_time(60) == "1m 0s"
    assert _format_relative_time(90) == "1m 30s"
    assert _format_relative_time(3599) == "59m 59s"


def test_format_relative_time_hours():
    assert _format_relative_time(3600) == "1h 0m"
    assert _format_relative_time(5400) == "1h 30m"
    assert _format_relative_time(86399) == "23h 59m"


def test_format_relative_time_days():
    assert _format_relative_time(86400) == "1d 0h"
    assert _format_relative_time(86400 * 2 + 3600 * 5) == "2d 5h"
    assert _format_relative_time(86400 * 6 + 3600 * 23) == "6d 23h"


def test_format_relative_time_weeks():
    assert _format_relative_time(86400 * 7) == "1w"
    assert _format_relative_time(86400 * 10) == "1w 3d"
    assert _format_relative_time(86400 * 14) == "2w"
    assert _format_relative_time(86400 * 21 + 86400 * 2) == "3w 2d"


def test_format_relative_time_with_suffix():
    assert _format_relative_time(0.5, suffix=" ago") == "500ms ago"
    assert _format_relative_time(5.0, suffix=" ago") == "5.0s ago"
    assert _format_relative_time(120, suffix=" ago") == "2m 0s ago"
    assert _format_relative_time(7200, suffix=" ago") == "2h 0m ago"
    assert _format_relative_time(86400, suffix=" ago") == "1d 0h ago"
    assert _format_relative_time(86400 * 7, suffix=" ago") == "1w ago"
    assert _format_relative_time(86400 * 10, suffix=" ago") == "1w 3d ago"


# ============================================================================
# Tests for time_ago_str property
# ============================================================================


def test_time_ago_str_not_finalized():
    r = RunResult(command_name="test")
    assert r.time_ago_str == "-"

    r.mark_running()
    assert r.time_ago_str == "-"


def test_time_ago_str_just_completed():
    r = RunResult(command_name="test")
    r.mark_running()
    r.mark_success()
    # Just completed, should be milliseconds or seconds ago
    assert "ms ago" in r.time_ago_str or "s ago" in r.time_ago_str


def test_time_ago_str_with_past_end_time():
    r = RunResult(command_name="test")
    r.mark_running()
    # Manually set end_time to 2 hours ago
    r.end_time = datetime.datetime.now() - datetime.timedelta(hours=2)
    assert r.time_ago_str == "2h 0m ago"


def test_time_ago_str_days_ago():
    r = RunResult(command_name="test")
    r.mark_running()
    r.end_time = datetime.datetime.now() - datetime.timedelta(days=3, hours=5)
    assert r.time_ago_str == "3d 5h ago"


def test_time_ago_str_weeks_ago():
    r = RunResult(command_name="test")
    r.mark_running()
    r.end_time = datetime.datetime.now() - datetime.timedelta(weeks=2)
    assert r.time_ago_str == "2w ago"


def test_time_ago_str_weeks_and_days_ago():
    r = RunResult(command_name="test")
    r.mark_running()
    r.end_time = datetime.datetime.now() - datetime.timedelta(weeks=1, days=3)
    assert r.time_ago_str == "1w 3d ago"
