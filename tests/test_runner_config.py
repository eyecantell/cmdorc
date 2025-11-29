# tests/test_runner_config.py
import pytest
from cmdorc.runner_config import RunnerConfig

def test_runner_config_init(sample_runner_config):
    assert len(sample_runner_config.commands) == 1
    assert sample_runner_config.commands[0].name == "TestCmd"
    assert sample_runner_config.vars["message"] == "hello"
    assert sample_runner_config.vars["base_directory"] == "/tmp"

def test_runner_config_empty_commands():
    with pytest.raises(ValueError):  # Not enforced in class, but could add __post_init__
        RunnerConfig(commands=[])

def test_runner_config_vars_default():
    config = RunnerConfig(commands=[])
    assert config.vars == {}