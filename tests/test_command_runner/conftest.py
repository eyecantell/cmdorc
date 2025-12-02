# tests/test_command_runner/conftest.py
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def create_long_running_proc():
    """Mock subprocess that never finishes until killed."""
    proc = AsyncMock()
    proc.returncode = None
    killed = asyncio.Event()

    async def communicate_impl():
        await killed.wait()
        proc.returncode = -9
        return (b"", b"")

    def kill_sync():
        proc.returncode = -9
        killed.set()

    proc.kill = Mock(side_effect=kill_sync)
    proc.terminate = Mock(side_effect=kill_sync)
    proc.communicate = communicate_impl

    async def wait_impl():
        await killed.wait()
        return -9

    proc.wait = wait_impl
    return proc


@pytest.fixture
def mock_success_proc():
    proc = AsyncMock()
    proc.communicate.return_value = (b"ok\n", b"")
    proc.returncode = 0
    return proc


@pytest.fixture
def mock_failure_proc():
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"error\n")
    proc.returncode = 1
    return proc
