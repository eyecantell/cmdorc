# tests/test_command_runner/test_history.py
import logging
from unittest.mock import patch

import pytest

from cmdorc.command_runner import CommandConfig, CommandRunner, CommandStatus
import logging

logging.getLogger("cmdorc").setLevel(logging.DEBUG)


@pytest.mark.asyncio
async def test_history_retention(mock_success_proc):
    cfg = CommandConfig(name="H", command="echo x", triggers=["run"], keep_history=2)
    runner = CommandRunner([cfg])

    with patch("asyncio.create_subprocess_shell", return_value=mock_success_proc):
        for _ in range(5):
            await runner.trigger("run")
            assert await runner.wait_for_status("H", CommandStatus.SUCCESS, timeout=1.0)
        assert len(runner.get_history("H")) == 2
