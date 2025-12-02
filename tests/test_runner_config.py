# tests/test_runner_config.py
import pytest

from cmdorc import CommandConfig, RunnerConfig


def test_runner_config_init(sample_runner_config):
    assert len(sample_runner_config.commands) == 1
    assert sample_runner_config.commands[0].name == "TestCmd"
    assert sample_runner_config.vars["message"] == "hello"
    assert sample_runner_config.vars["base_directory"] == "/tmp"


def test_runner_config_empty_commands():
    with pytest.raises(ValueError, match="At least one command is required"):
        RunnerConfig(commands=[])


def test_runner_config_vars_default():
    dummy_cmd = CommandConfig(name="Dummy", command="echo", triggers=[])
    config = RunnerConfig(commands=[dummy_cmd])
    assert config.vars == {}
