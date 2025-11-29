# tests/test_command_config.py
import pytest
from cmdorc.command_config import CommandConfig

def test_command_config_init(sample_command_config):
    assert sample_command_config.name == "TestCmd"
    assert sample_command_config.command == "echo {{ message }}"
    assert "test_trigger" in sample_command_config.triggers
    assert "cancel_me" in sample_command_config.cancel_on_triggers
    assert sample_command_config.max_concurrent == 1
    assert sample_command_config.timeout_secs == 30
    assert sample_command_config.on_retrigger == "cancel_and_restart"
    assert sample_command_config.keep_history == 3

def test_command_config_validation_errors():
    with pytest.raises(ValueError, match="name cannot be empty"):
        CommandConfig(name="", command="echo", triggers=[])
    
    with pytest.raises(ValueError, match="Command.*cannot be empty"):
        CommandConfig(name="Test", command=" ", triggers=[])
    
    with pytest.raises(ValueError, match="max_concurrent cannot be negative"):
        CommandConfig(name="Test", command="echo", triggers=[], max_concurrent=-1)
    
    with pytest.raises(ValueError, match="timeout_secs must be positive"):
        CommandConfig(name="Test", command="echo", triggers=[], timeout_secs=0)
    
    # Invalid on_retrigger (type checked by Literal)
    with pytest.raises(ValueError, match="unexpected keyword argument"):
        CommandConfig(name="Test", command="echo", triggers=[], on_retrigger="invalid")  # pydantic/dataclass doesn't auto-validate Literal, but we can add if needed