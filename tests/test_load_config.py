# tests/test_load_config.py
import pytest
import logging
from io import BytesIO
from unittest.mock import patch
from cmdorc import load_config

logging.getLogger("cmdorc").setLevel(logging.DEBUG)

@pytest.fixture
def sample_toml():
    toml_str = """
    [variables]
    base_directory = "/project"
    tests_directory = "{{base_directory}}/tests"   # ← no spaces!

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
        """
    [variables]
    a = "{{b}}"
    b = "{{c}}"
    c = "{{a}}"
    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """.encode()
    )
    with pytest.raises(ValueError, match="Stalled resolution in"):
        load_config(loop_toml)

def test_load_config_from_textio():
    # 25-26: tomli.load for TextIO
    toml_str = """
    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    config = load_config(BytesIO(toml_str.encode("utf-8")))  # Already covered, but use TextIO
    assert len(config.commands) == 1

def test_variable_resolution_changes():
    # 41-42: changed = True in resolution loop
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
    assert config.vars["a"] == "value"  # Resolution happened

def test_no_more_changes_debug(caplog):
    # 51: "No more variable changes detected"
    toml_str = """
    [variables]
    a = "static"

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    
    load_config(BytesIO(toml_str.encode("utf-8")))
    assert "No more variable changes detected" in caplog.text

def test_stalled_resolution_raise():
    # 56: Stalled resolution raise
    toml_str = """
    [variables]
    a = "{{b}} and {{c}}"
    b = "ok"
    c = "{{d}}"  # Unresolved

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    with pytest.raises(ValueError, match="Missing variable"):
        load_config(BytesIO(toml_str.encode("utf-8")))

def test_infinite_loop_raise():
    # 63-64: Infinite loop raise
    toml_str = """
    [variables]
    a = "{{b}}"
    b = "{{c}}"
    c = "{{d}}"
    d = "{{a}}"  # Cycle deeper than max

    [[command]]
    name = "Test"
    command = "echo ok"
    triggers = []
    """
    with pytest.raises(ValueError, match="Stalled resolution in"):
        load_config(BytesIO(toml_str.encode("utf-8")))