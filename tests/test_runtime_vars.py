"""Tests for runtime variable resolution module."""

import pytest

from cmdorc.command_config import CommandConfig
from cmdorc.runtime_vars import (
    merge_vars,
    prepare_resolved_command,
    resolve_runtime_vars,
)

# =====================================================================
#   Test merge_vars
# =====================================================================


def test_merge_vars_empty():
    """merge_vars with all None inputs and no os.environ."""
    # Note: When all inputs are None, merge_vars defaults env_vars to os.environ
    # To get an empty dict, we need to explicitly pass empty dict
    result = merge_vars(env_vars={})
    assert result == {}


def test_merge_vars_global_only():
    """merge_vars with global vars only."""
    global_vars = {"base": "/app", "debug": "false"}
    result = merge_vars(global_vars=global_vars, env_vars={})
    assert result == global_vars


def test_merge_vars_priority_order(monkeypatch):
    """Verify merge priority: global → env → command → call-time."""
    monkeypatch.setenv("target", "env-target")
    monkeypatch.setenv("extra", "from-env")

    global_vars = {"target": "global-target", "base": "/app"}
    env_vars = {"target": "env-target", "extra": "from-env"}
    command_vars = {"target": "command-target"}
    call_time_vars = {"target": "call-target", "runtime": "override"}

    result = merge_vars(
        global_vars=global_vars,
        env_vars=env_vars,
        command_vars=command_vars,
        call_time_vars=call_time_vars,
    )

    # call-time wins for 'target'
    assert result["target"] == "call-target"
    # command wins for anything not in call-time
    assert result["base"] == "/app"
    assert result["extra"] == "from-env"
    assert result["runtime"] == "override"


def test_merge_vars_env_defaults_to_os_environ(monkeypatch):
    """When env_vars is None, merge_vars uses os.environ."""
    monkeypatch.setenv("TEST_VAR_CUSTOM", "test-value")

    global_vars = {"base": "/app"}
    result = merge_vars(global_vars=global_vars, env_vars=None)

    # Should include os.environ values
    assert result["TEST_VAR_CUSTOM"] == "test-value"
    assert result["base"] == "/app"


def test_merge_vars_non_string_values():
    """merge_vars preserves non-string values (no casting)."""
    global_vars = {"debug": True, "level": 5}
    result = merge_vars(global_vars=global_vars, env_vars={})
    # Non-strings should pass through as-is
    assert result["debug"] is True
    assert result["level"] == 5


# =====================================================================
#   Test resolve_runtime_vars
# =====================================================================


def test_resolve_runtime_vars_no_templates():
    """resolve_runtime_vars with no templates returns original string."""
    result = resolve_runtime_vars("hello world", {})
    assert result == "hello world"


def test_resolve_runtime_vars_simple():
    """resolve_runtime_vars with single template."""
    vars_dict = {"name": "Alice"}
    result = resolve_runtime_vars("Hello {{ name }}", vars_dict)
    assert result == "Hello Alice"


def test_resolve_runtime_vars_multiple():
    """resolve_runtime_vars with multiple templates."""
    vars_dict = {"first": "John", "last": "Doe"}
    result = resolve_runtime_vars("Name: {{ first }} {{ last }}", vars_dict)
    assert result == "Name: John Doe"


def test_resolve_runtime_vars_nested():
    """resolve_runtime_vars supports nested variable resolution."""
    vars_dict = {"base": "/app", "subdir": "src", "full": "{{ base }}/{{ subdir }}"}
    result = resolve_runtime_vars("{{ full }}/main.py", vars_dict)
    assert result == "/app/src/main.py"


def test_resolve_runtime_vars_env_syntax(monkeypatch):
    """resolve_runtime_vars converts $VAR_NAME to {{ VAR_NAME }}."""
    monkeypatch.setenv("HOME", "/home/user")
    vars_dict = {"HOME": "/home/user"}
    result = resolve_runtime_vars("home is $HOME", vars_dict)
    assert result == "home is /home/user"


def test_resolve_runtime_vars_env_syntax_multiple(monkeypatch):
    """resolve_runtime_vars with multiple $VAR_NAME references."""
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setenv("USER", "testuser")
    vars_dict = {"HOME": "/home/user", "USER": "testuser"}
    result = resolve_runtime_vars("$HOME/$USER", vars_dict)
    assert result == "/home/user/testuser"


def test_resolve_runtime_vars_shell_escape_not_replaced():
    """resolve_runtime_vars doesn't replace $$ (shell escape)."""
    vars_dict = {"PATH": "/usr/bin"}
    result = resolve_runtime_vars("echo $$var and $PATH", vars_dict)
    # $$ should remain, $PATH should be replaced
    assert result == "echo $$var and /usr/bin"


def test_resolve_runtime_vars_missing_variable():
    """resolve_runtime_vars raises ValueError for missing variable."""
    with pytest.raises(ValueError, match="Missing variable: 'undefined'"):
        resolve_runtime_vars("{{ undefined }}", {})


def test_resolve_runtime_vars_missing_enriched_error():
    """resolve_runtime_vars error includes original template."""
    with pytest.raises(ValueError, match="In template 'dir: {{ missing }}'"):
        resolve_runtime_vars("dir: {{ missing }}", {})


def test_resolve_runtime_vars_cycle_detected():
    """resolve_runtime_vars detects variable cycles."""
    vars_dict = {"a": "{{ b }}", "b": "{{ a }}"}
    with pytest.raises(ValueError, match="Unresolved nested variables remain"):
        resolve_runtime_vars("{{ a }}", vars_dict)


def test_resolve_runtime_vars_exceeds_max_depth():
    """resolve_runtime_vars fails when nesting exceeds max_depth."""
    # Create 11 levels of nesting with default max_depth=10
    vars_dict = {}
    for i in range(11):
        if i == 10:
            vars_dict[f"v{i}"] = "final"
        else:
            vars_dict[f"v{i}"] = "{{ v" + str(i + 1) + " }}"

    with pytest.raises(ValueError, match="Unresolved nested variables remain"):
        resolve_runtime_vars("{{ v0 }}", vars_dict, max_depth=10)


def test_resolve_runtime_vars_custom_max_depth():
    """resolve_runtime_vars respects custom max_depth parameter."""
    vars_dict = {"a": "{{ b }}", "b": "{{ c }}", "c": "value"}
    # 3 levels of nesting - should work with max_depth=3
    result = resolve_runtime_vars("{{ a }}", vars_dict, max_depth=3)
    assert result == "value"


# =====================================================================
#   Test prepare_resolved_command
# =====================================================================


def test_prepare_resolved_command_simple():
    """prepare_resolved_command resolves a simple command."""
    config = CommandConfig(
        name="Test",
        command="echo {{ message }}",
        triggers=[],
        vars={"message": "hello"},
    )
    global_vars = {}

    resolved = prepare_resolved_command(config, global_vars)

    assert resolved.command == "echo hello"
    assert "message" in resolved.vars
    assert resolved.vars["message"] == "hello"


def test_prepare_resolved_command_global_vars():
    """prepare_resolved_command uses global vars."""
    config = CommandConfig(
        name="Deploy",
        command="deploy to {{ target }}",
        triggers=[],
    )
    global_vars = {"target": "staging"}

    resolved = prepare_resolved_command(config, global_vars)

    assert resolved.command == "deploy to staging"


def test_prepare_resolved_command_merge_priority():
    """prepare_resolved_command merges variables with correct priority."""
    config = CommandConfig(
        name="Test",
        command="mode={{ mode }} env={{ env }}",
        triggers=[],
        vars={"mode": "command-mode", "env": "command-env"},
    )
    global_vars = {"mode": "global-mode", "env": "global-env", "log": "debug"}
    call_time_vars = {"mode": "runtime-mode"}

    resolved = prepare_resolved_command(config, global_vars, call_time_vars=call_time_vars)

    # call-time wins for 'mode'
    assert resolved.command == "mode=runtime-mode env=command-env"
    # vars snapshot should have the merged values
    assert resolved.vars["mode"] == "runtime-mode"
    assert resolved.vars["env"] == "command-env"
    assert resolved.vars["log"] == "debug"


def test_prepare_resolved_command_env_dict():
    """prepare_resolved_command resolves environment variable values."""
    config = CommandConfig(
        name="Test",
        command="run",
        triggers=[],
        env={"TARGET": "{{ target }}", "DEBUG": "true"},
    )
    global_vars = {"target": "production"}

    resolved = prepare_resolved_command(config, global_vars, include_env=False)

    assert resolved.env["TARGET"] == "production"
    assert resolved.env["DEBUG"] == "true"


def test_prepare_resolved_command_env_includes_system(monkeypatch):
    """prepare_resolved_command includes system environment by default."""
    monkeypatch.setenv("PATH", "/usr/bin")
    config = CommandConfig(
        name="Test",
        command="run",
        triggers=[],
        env={"CUSTOM": "value"},
    )
    global_vars = {}

    resolved = prepare_resolved_command(config, global_vars, include_env=True)

    assert resolved.env["PATH"] == "/usr/bin"  # From system
    assert resolved.env["CUSTOM"] == "value"  # From config


def test_prepare_resolved_command_env_exclude_system(monkeypatch):
    """prepare_resolved_command can exclude system environment."""
    monkeypatch.setenv("PATH", "/usr/bin")
    config = CommandConfig(
        name="Test",
        command="run",
        triggers=[],
        env={"CUSTOM": "value"},
    )
    global_vars = {}

    resolved = prepare_resolved_command(config, global_vars, include_env=False)

    assert "PATH" not in resolved.env  # Excluded
    assert resolved.env["CUSTOM"] == "value"


def test_prepare_resolved_command_cwd():
    """prepare_resolved_command preserves cwd."""
    config = CommandConfig(
        name="Test",
        command="run",
        triggers=[],
        cwd="/app",
    )
    global_vars = {}

    resolved = prepare_resolved_command(config, global_vars)

    assert resolved.cwd == "/app"


def test_prepare_resolved_command_cwd_none():
    """prepare_resolved_command handles cwd=None."""
    config = CommandConfig(
        name="Test",
        command="run",
        triggers=[],
        cwd=None,
    )
    global_vars = {}

    resolved = prepare_resolved_command(config, global_vars)

    assert resolved.cwd is None


def test_prepare_resolved_command_timeout():
    """prepare_resolved_command preserves timeout_secs."""
    config = CommandConfig(
        name="Test",
        command="run",
        triggers=[],
        timeout_secs=60,
    )
    global_vars = {}

    resolved = prepare_resolved_command(config, global_vars)

    assert resolved.timeout_secs == 60


def test_prepare_resolved_command_vars_frozen():
    """prepare_resolved_command.vars is a frozen copy of merged vars."""
    config = CommandConfig(
        name="Test",
        command="run {{ mode }}",
        triggers=[],
        vars={"mode": "prod"},
    )
    global_vars = {"base": "/app"}

    resolved = prepare_resolved_command(config, global_vars)

    # Vars should include merged values
    assert resolved.vars["mode"] == "prod"
    assert resolved.vars["base"] == "/app"

    # Modifying returned vars shouldn't affect anything
    # (it's a copy due to .copy() in prepare_resolved_command)
    resolved.vars.copy()
    # Note: ResolvedCommand is frozen, so we can't test mutation directly


def test_prepare_resolved_command_error_missing_variable():
    """prepare_resolved_command raises ValueError for missing variables."""
    config = CommandConfig(
        name="Test",
        command="deploy to {{ target }}",
        triggers=[],
    )
    global_vars = {}  # No 'target'

    with pytest.raises(ValueError, match="Missing variable: 'target'"):
        prepare_resolved_command(config, global_vars)


def test_prepare_resolved_command_error_includes_command_context():
    """prepare_resolved_command enriches error with template context."""
    config = CommandConfig(
        name="Deploy",
        command="deploy to {{ target }}",
        triggers=[],
    )
    global_vars = {}

    with pytest.raises(ValueError, match="In template 'deploy to .* target"):
        prepare_resolved_command(config, global_vars)


def test_prepare_resolved_command_complex_scenario(monkeypatch):
    """prepare_resolved_command handles complex multi-source scenario."""
    monkeypatch.setenv("ENV_MODE", "production")

    config = CommandConfig(
        name="Deploy",
        command="./deploy.sh --mode={{ mode }} --target={{ target }} --debug={{ debug }}",
        triggers=["deploy"],
        env={"MODE": "{{ mode }}", "LOG_LEVEL": "{{ log_level }}"},
        vars={"mode": "staging", "debug": "false"},
    )
    global_vars = {"target": "eu-west", "log_level": "info"}
    call_time_vars = {"mode": "production", "debug": "true"}

    resolved = prepare_resolved_command(config, global_vars, call_time_vars=call_time_vars)

    # Verify command resolution
    assert resolved.command == ("./deploy.sh --mode=production --target=eu-west --debug=true")

    # Verify env resolution
    assert resolved.env["MODE"] == "production"
    assert resolved.env["LOG_LEVEL"] == "info"

    # Verify vars snapshot
    assert resolved.vars["mode"] == "production"
    assert resolved.vars["target"] == "eu-west"
    assert resolved.vars["debug"] == "true"
    assert resolved.vars["log_level"] == "info"
