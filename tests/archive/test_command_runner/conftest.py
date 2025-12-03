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


@pytest.fixture
def create_proc():
    """
    Factory fixture that returns properly configured asyncio subprocess mocks.
    Use it like:
        proc = create_proc(stdout=b"hello\n", returncode=0)
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            ...
    """
    def _make(stdout=b"", stderr=b"", returncode=0, delay=0.0):
        proc = AsyncMock()

        async def communicate():
            if delay:
                await asyncio.sleep(delay)
            return stdout, stderr

        proc.communicate = communicate
        proc.returncode = returncode
        proc.stdout.read = AsyncMock(return_value=stdout)
        proc.stderr.read = AsyncMock(return_value=stderr)
        proc.kill = lambda: setattr(proc, "returncode", -9)
        proc.terminate = lambda: setattr(proc, "returncode", -15)
        proc.wait = AsyncMock(return_value=returncode)

        return proc

    return _make