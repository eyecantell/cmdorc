# tests/test_load_config.py

import io
import logging
from pathlib import Path

import pytest

from cmdorc import load_config

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


def test_variables_resolution():
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
    assert config.vars["root"] == "/app"
    assert config.vars["src"] == "/app/src"
    assert config.vars["bin"] == "/app/src/bin"
    assert config.commands[0].command == "make -C /app/src/bin"


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
    with pytest.raises(ValueError, match="Invalid trigger name.*bad\\*trigger"):
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
    with pytest.raises(ValueError, match="Invalid trigger name.*invalid\\*"):
        load_config(toml)


def test_empty_command_list():
    with pytest.raises(ValueError, match="At least one.*required"):
        load_config(io.BytesIO(b""))


def test_missing_command_name():
    toml = io.BytesIO(
        b"""
[[command]]
command = "echo ok"
triggers = []
"""
    )
    with pytest.raises(ValueError, match="Command name cannot be empty"):
        load_config(toml)


def test_missing_command_field():
    toml = io.BytesIO(
        b"""
[[command]]
name = "Missing"
triggers = []
"""
    )
    with pytest.raises(ValueError, match="Command for 'Missing' cannot be empty"):
        load_config(toml)


def test_variable_missing_reference():
    toml = io.BytesIO(
        b"""
[variables]
a = "{{undefined}}"

[[command]]
name = "X"
command = "echo"
triggers = []
"""
    )
    with pytest.raises(ValueError, match="Missing variable: 'undefined'"):
        load_config(toml)


def test_nested_variable_cycle():
    toml = io.BytesIO(
        b"""
[variables]
a = "{{b}}"
b = "{{a}}"

[[command]]
name = "X"
command = "echo"
triggers = []
"""
    )
    with pytest.raises(ValueError, match="Unresolved nested variables remain"):
        load_config(toml)


def test_deep_nesting_exceeds_max_depth():
    # 11 levels → exceeds default max_nested_depth=10
    levels = [f"x{i} = '{{{chr(97 + i + 1)}}}'" for i in range(10)]
    levels.append("x10 = 'final'")
    vars_section = "\n".join(levels)

    toml = io.BytesIO(
        f"""
[variables]
{vars_section}

[[command]]
name = "Deep"
command = "echo {{x0}}"
triggers = []
""".encode()
    )
    with pytest.raises(ValueError, match="Unresolved nested variables remain"):
        load_config(toml, max_nested_depth=10)


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


def test_debug_log_on_stable_resolution(caplog):
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
    assert "All variables resolved successfully" in caplog.text


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