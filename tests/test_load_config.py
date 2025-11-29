# tests/test_load_config.py
import pytest
from io import BytesIO
from cmdorc.load_config import load_config

@pytest.fixture
def sample_toml():
    toml_str = """
    [variables]
    base_directory = "/project"
    tests_directory = "{{ base_directory }}/tests"

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
    config = load_config(sample_toml)  # BytesIO acts as file
    assert len(config.commands) == 2
    assert config.commands[0].name == "Tests"
    assert config.commands[0].command == "pytest {{ tests_directory }}"
    assert config.commands[1].name == "Lint"
    
    assert config.vars["base_directory"] == "/project"
    assert config.vars["tests_directory"] == "/project/tests"  # Resolved nested

def test_load_config_missing_sections(sample_toml):
    bad_toml = BytesIO(b"")  # Empty
    with pytest.raises(ValueError, match="At least one [[command]]"):
        load_config(bad_toml)

def test_load_config_invalid_command(sample_toml):
    bad_toml_str = """
    [[command]]
    name = ""
    command = "echo"
    triggers = []
    """
    bad_toml = BytesIO(bad_toml_str.encode())
    with pytest.raises(ValueError, match="name cannot be empty"):
        load_config(bad_toml)

def test_load_config_nested_resolution_loop():
    loop_toml_str = """
    [variables]
    a = "{{ b }}"
    b = "{{ a }}"
    [[command]]
    name = "Test"
    command = "echo"
    triggers = []
    """
    loop_toml = BytesIO(loop_toml_str.encode())
    with pytest.raises(ValueError, match="Infinite loop"):
        load_config(loop_toml)