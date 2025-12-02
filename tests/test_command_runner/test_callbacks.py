# tests/test_command_runner/test_callbacks.py
import asyncio

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner
import logging
logging.getLogger("cmdorc").setLevel(logging.DEBUG)

@pytest.mark.asyncio
async def test_on_trigger_and_off_trigger():
    dummy_cfg = CommandConfig(name="Dummy", command="echo ok", triggers=[])
    runner = CommandRunner([dummy_cfg])

    called = asyncio.Event()

    def cb(_):
        called.set()

    runner.on_trigger("test", cb)
    await runner.trigger("test")
    await asyncio.wait_for(called.wait(), timeout=0.1)

    called.clear()
    runner.off_trigger("test", cb)
    await runner.trigger("test")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(called.wait(), timeout=0.1)
