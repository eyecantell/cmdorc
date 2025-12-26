# tests/test_load_config.py

import io
import logging
from pathlib import Path

import pytest

from cmdorc import ConfigValidationError, load_config

logging.getLogger("cmdorc").setLevel(logging.DEBUG)


@pytest.fixture
def minimal_toml():
    return io.BytesIO(
        b"""
[[command]]
name = "Hello"
command = "echo hello"
triggers = ["start"]
"""
    )


def test_load_minimal_config(minimal_toml):
    config = load_config(minimal_toml)
    assert len(config.commands) == 1
    cmd = config.commands[0]
    assert cmd.name == "Hello"
    assert cmd.command == "echo hello"
    assert cmd.triggers == ["start"]


def test_variables_stored_as_templates():
    """Variables in config are stored as templates, not pre-resolved."""
    toml = io.BytesIO(
        b"""
[variables]
root = "/app"
src = "{{root}}/src"
bin = "{{src}}/bin"

[[command]]
name = "Build"
command = "make -C {{bin}}"
triggers = ["build"]
"""
    )
    config = load_config(toml)
    # Variables are stored as templates (Phase 1 resolution removed)
    assert config.vars["root"] == "/app"
    assert config.vars["src"] == "{{root}}/src"  # Template, not resolved
    assert config.vars["bin"] == "{{src}}/bin"  # Template, not resolved
    # Command string also contains template
    assert config.commands[0].command == "make -C {{bin}}"


def test_relative_cwd_resolution(tmp_path: Path):
    config_file = tmp_path / "cmdorc.toml"
    config_file.write_text(
        """
[[command]]
name = "Test"
command = "pwd"
cwd = "./sub/dir"
triggers = []

[[command]]
name = "TestAbs"
command = "pwd"
cwd = "/absolute/path"
triggers = []
"""
    )

    config = load_config(str(config_file))
    assert len(config.commands) == 2

    rel_cmd = config.commands[0]
    abs_cmd = config.commands[1]

    expected_rel = str((tmp_path / "sub" / "dir").resolve())
    assert rel_cmd.cwd == expected_rel
    assert abs_cmd.cwd == "/absolute/path"


def test_invalid_trigger_characters():
    toml = io.BytesIO(
        b"""
[[command]]
name = "Bad"
command = "echo ok"
triggers = ["good", "bad*trigger", "spaces bad"]
"""
    )
    with pytest.raises(ConfigValidationError, match="Invalid trigger name.*bad\\*trigger"):
        load_config(toml)


def test_cancel_on_triggers_validation():
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "sleep 10"
triggers = ["run"]
cancel_on_triggers = ["stop", "invalid*"]
"""
    )
    with pytest.raises(ConfigValidationError, match="Invalid trigger name.*invalid\\*"):
        load_config(toml)


def test_empty_command_list():
    with pytest.raises(ConfigValidationError, match="At least one.*required"):
        load_config(io.BytesIO(b""))


def test_missing_command_name():
    toml = io.BytesIO(
        b"""
[[command]]
command = "echo ok"
triggers = []
"""
    )
    with pytest.raises(ConfigValidationError, match="Invalid config in \\[\\[command\\]\\]"):
        load_config(toml)


def test_missing_command_field():
    toml = io.BytesIO(
        b"""
[[command]]
name = "Missing"
triggers = []
"""
    )
    with pytest.raises(ConfigValidationError, match="Invalid config in \\[\\[command\\]\\]"):
        load_config(toml)


def test_non_string_variable_skipped():
    toml = io.BytesIO(
        b"""
[variables]
debug = true
path = "/app"

[[command]]
name = "Test"
command = "run"
triggers = []
"""
    )
    config = load_config(toml)
    assert config.vars["debug"] is True
    assert config.vars["path"] == "/app"


def test_debug_log_on_variable_load(caplog):
    caplog.set_level(logging.DEBUG)
    load_config(
        io.BytesIO(
            b"""
[variables]
a = "fixed"

[[command]]
name = "X"
command = "echo"
triggers = []
"""
        )
    )
    assert "Loaded 1 variables as templates" in caplog.text


def test_from_pathlib_path(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[[command]]
name = "Path"
command = "echo ok"
triggers = []
"""
    )
    config = load_config(config_file)
    assert len(config.commands) == 1
    assert config.commands[0].name == "Path"


# ================================================================
# CommandConfig Validation Tests
# ================================================================


def test_empty_trigger_name_in_list():
    """Empty trigger name in triggers list should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "echo"
triggers = ["valid", ""]
"""
    )
    with pytest.raises(ConfigValidationError, match="Trigger name cannot be empty"):
        load_config(toml)


def test_negative_max_concurrent():
    """Negative max_concurrent should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "echo"
triggers = []
max_concurrent = -1
"""
    )
    with pytest.raises(ConfigValidationError, match="max_concurrent cannot be negative"):
        load_config(toml)


def test_zero_timeout_secs():
    """Zero timeout_secs should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "echo"
triggers = []
timeout_secs = 0
"""
    )
    with pytest.raises(ConfigValidationError, match="timeout_secs must be positive"):
        load_config(toml)


def test_negative_timeout_secs():
    """Negative timeout_secs should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "echo"
triggers = []
timeout_secs = -10
"""
    )
    with pytest.raises(ConfigValidationError, match="timeout_secs must be positive"):
        load_config(toml)


def test_invalid_on_retrigger_value():
    """Invalid on_retrigger value should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "echo"
triggers = []
on_retrigger = "restart"
"""
    )
    with pytest.raises(ConfigValidationError, match="on_retrigger must be"):
        load_config(toml)


def test_invalid_keep_in_memory():
    """keep_in_memory less than -1 should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "echo"
triggers = []
keep_in_memory = -2
"""
    )
    with pytest.raises(ConfigValidationError, match="keep_in_memory must be"):
        load_config(toml)


def test_invalid_debounce_mode():
    """Invalid debounce_mode should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "echo"
triggers = []
debounce_mode = "invalid"
"""
    )
    with pytest.raises(ConfigValidationError, match="debounce_mode must be"):
        load_config(toml)


def test_whitespace_only_command():
    """Command with only whitespace should fail validation."""
    toml = io.BytesIO(
        b"""
[[command]]
name = "Test"
command = "   "
triggers = []
"""
    )
    with pytest.raises(ConfigValidationError, match="Command.*cannot be empty"):
        load_config(toml)
