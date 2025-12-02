# tests/test_command_runner/test_callbacks.py
import asyncio

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner


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

@pytest.mark.asyncio
async def test_async_callback_with_error(caplog):
    dummy_cfg = CommandConfig(name="Dummy", command="echo ok", triggers=[])
    runner = CommandRunner([dummy_cfg])
    called = asyncio.Event()

    async def good_async_cb(_):
        called.set()

    async def bad_async_cb(_):
        raise ValueError("boom")

    def bad_sync_cb(_):
        raise ValueError("sync boom")

    runner.on_trigger("test", good_async_cb)
    runner.on_trigger("test", bad_async_cb)
    runner.on_trigger("test", bad_sync_cb)

    await runner.trigger("test")
    await asyncio.wait_for(called.wait(), timeout=0.1)
    assert "Trigger callback error (test): boom" in caplog.text
    assert "Trigger callback error (test): sync boom" in caplog.text
