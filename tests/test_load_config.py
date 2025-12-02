# tests/test_load_config.py

import logging
from io import BytesIO
import io
import pytest

from cmdorc import load_config

logging.getLogger("cmdorc").setLevel(logging.DEBUG)


@pytest.fixture
def sample_toml():
    toml_str = """
    [variables]
    base_directory = "/project"
    tests_directory = "{{base_directory}}/tests"   # no spaces allowed

    [[command]]
    name = "Tests"
    command = "pytest {{ tests_directory }}"
    triggers = ["changes_applied", "Tests"]
    cancel_on_triggers = ["prompt_send"]
    max_concurrent = 1
    on_retrigger = "cancel_and_restart"
    timeout_secs = 300
    keep_history = 2

    [[command]]
    name = "Lint"
    command = "ruff check {{ base_directory }}"
    triggers = ["changes_applied"]
    """
    return BytesIO(toml_str.encode("utf-8"))


def test_load_config(sample_toml):
    sample_toml.seek(0)
    config = load_config(sample_toml)
    assert len(config.commands) == 2
    assert config.vars["tests_directory"] == "/project/tests"


def test_load_config_missing_sections():
    empty = BytesIO(b"")
    with pytest.raises(ValueError, match="At least one.*required"):
        load_config(empty)


def test_load_config_nested_resolution_loop():
    loop_toml = BytesIO(
        b"""
    [variables]
    a = "{{b}}"
    b = "{{c}}"
    c = "{{a}}"

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    )
    with pytest.raises(ValueError, match="Unresolved nested variables remain"):
        load_config(loop_toml)


def test_load_config_from_textio():
    toml_str = """
    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    config = load_config(BytesIO(toml_str.encode("utf-8")))
    assert len(config.commands) == 1


def test_variable_resolution_changes():
    toml_str = """
    [variables]
    a = "{{b}}"
    b = "value"

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    config = load_config(BytesIO(toml_str.encode("utf-8")))
    assert config.vars["a"] == "value"


def test_no_more_changes_debug(caplog):
    toml_str = """
    [variables]
    a = "static"

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """

    load_config(BytesIO(toml_str.encode("utf-8")))
    assert "Variable resolution stabilized" in caplog.text


def test_missing_variable_raises():
    toml_str = """
    [variables]
    a = "{{b}} and stuff"
    # b missing

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    with pytest.raises(ValueError, match="Missing variable"):
        load_config(BytesIO(toml_str.encode("utf-8")))


def test_infinite_loop_deeper():
    toml_str = """
    [variables]
    a = "{{b}}"
    b = "{{c}}"
    c = "{{d}}"
    d = "{{a}}"  # Cycle

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    with pytest.raises(ValueError, match="Unresolved nested variables remain"):
        load_config(BytesIO(toml_str.encode("utf-8")))


def test_load_config_from_str_path(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("""
[[command]]
name = "Test"
command = "echo ok"
triggers = []
    """)
    config = load_config(str(toml_path))
    assert len(config.commands) == 1
    assert config.commands[0].name == "Test"


def test_deep_nesting_exceeds_max():
    toml_str = """
[variables]
a = "{{b}}"
b = "{{c}}"
c = "{{d}}"
d = "{{e}}"
e = "{{f}}"
f = "{{g}}"
g = "value"

[[command]]
name = "Test"
command = "echo ok"
triggers = []
    """
    # Exceeds 5 iterations → infinite loop
    with pytest.raises(ValueError, match="Unresolved nested variables remain"):
        load_config(io.BytesIO(toml_str.encode("utf-8")))
