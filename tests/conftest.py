# tests/conftest.py
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import pytest
import asyncio
from cmdorc.command_config import CommandConfig
from cmdorc.runner_config import RunnerConfig
from cmdorc.command_runner import CommandRunner


@pytest.fixture
def sample_command_config():
    return CommandConfig(
        name="TestCmd",
        command="echo {{ message }}",
        triggers=["test_trigger", "TestCmd"],
        cancel_on_triggers=["cancel_me"],
        max_concurrent=1,
        on_retrigger="cancel_and_restart",
        timeout_secs=30,
        keep_history=3
    )

@pytest.fixture
def sample_runner_config(sample_command_config):
    return RunnerConfig(
        commands=[sample_command_config],
        vars={"message": "hello", "base_directory": "/tmp"}
    )

@pytest.fixture
def sample_runner(sample_command_config):
    config = RunnerConfig(commands=[sample_command_config], vars={"message": "hello"})
    return CommandRunner(config)