# tests/test_utils.py

from cmdorc import format_duration


def test_format_duration_milliseconds():
    assert format_duration(0.5) == "500ms"
    assert format_duration(0.001) == "1ms"
    assert format_duration(0.999) == "999ms"


def test_format_duration_seconds():
    assert format_duration(1.0) == "1.0s"
    assert format_duration(30.5) == "30.5s"
    assert format_duration(59.9) == "59.9s"


def test_format_duration_minutes():
    assert format_duration(60) == "1m 0s"
    assert format_duration(90) == "1m 30s"
    assert format_duration(3599) == "59m 59s"


def test_format_duration_hours():
    assert format_duration(3600) == "1h 0m"
    assert format_duration(5400) == "1h 30m"
    assert format_duration(86399) == "23h 59m"


def test_format_duration_days():
    assert format_duration(86400) == "1d 0h"
    assert format_duration(86400 * 2 + 3600 * 5) == "2d 5h"
    assert format_duration(86400 * 6 + 3600 * 23) == "6d 23h"


def test_format_duration_weeks():
    assert format_duration(86400 * 7) == "1w"
    assert format_duration(86400 * 10) == "1w 3d"
    assert format_duration(86400 * 14) == "2w"
    assert format_duration(86400 * 21 + 86400 * 2) == "3w 2d"
