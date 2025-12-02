# tests/test_command_runner/test_templates.py
from unittest.mock import AsyncMock, patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus


@pytest.mark.asyncio
async def test_nested_template_resolution():
    runner = CommandRunner([
        CommandConfig(name="T", command="cd {{dir}} && ls {{sub}}", triggers=["run"])
    ])
    runner.set_vars({"base": "/home", "dir": "{{base}}/proj", "sub": "src"})
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    with patch("asyncio.create_subprocess_shell", return_value=proc):
        await runner.trigger("run")
        assert await runner.wait_for_status("T", CommandStatus.SUCCESS, timeout=1.0)


@pytest.mark.asyncio
async def test_template_cycle_detection():
    runner = CommandRunner([CommandConfig(name="Boom", command="{{a}}", triggers=["boom"])])
    runner.set_vars({"a": "{{b}}", "b": "{{a}}"})
    await runner.trigger("boom")
    assert await runner.wait_for_status("Boom", CommandStatus.FAILED, timeout=1.0)
    assert "cycle" in runner.get_result("Boom").error.lower()


def test_unresolvable_template_raises_keyerror():
    dummy_cfg = CommandConfig(name="Dummy", command="echo ok", triggers=[])
    runner = CommandRunner([dummy_cfg])
    with pytest.raises(KeyError):
        runner._resolve_template("hello {{missing}}")
