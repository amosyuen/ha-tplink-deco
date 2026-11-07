"""Tests for paging through the Deco system log."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import TransientConnectionException


@pytest.fixture
def api():
    api = TplinkDecoApi(
        session=MagicMock(spec=aiohttp.ClientSession),
        host="http://192.168.1.1",
        username="admin",
        password="password",
        verify_ssl=False,
    )
    _authenticate(api, "token")
    api._encode_payload = lambda payload: payload
    return api


def _authenticate(api, stok):
    api._stok = stok
    api._cookie = "sysauth=abc"
    api._seq = 1


class FakeLogRouter:
    """Serve a log snapshot in pages, recording each request."""

    def __init__(self, pages):
        self.pages = pages
        self.builds = []
        self.reads = []
        self.page_responses = {}

    async def post(self, context, url, params, data):
        if data["operation"] == "build":
            self.builds.append(data["params"]["level"])
            return {"data": {"error_code": 0}}

        index = data["params"]["index"]
        self.reads.append(index)
        responses = self.page_responses.get(index)
        if responses:
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            if callable(response):
                return await response()
            return response
        return {
            "data": {
                "error_code": 0,
                "result": {
                    "totalNum": len(self.pages),
                    "logList": [{"content": line} for line in self.pages[index]],
                },
            }
        }


def _serve(api, pages):
    router = FakeLogRouter(pages)
    api._async_post = AsyncMock(side_effect=router.post)
    return router


async def _hang():
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_pages_are_read_newest_first_and_assembled_oldest_first(api):
    router = _serve(api, [["a1", "a2"], ["b1"], ["c1", "c2"], ["d1"]])

    system_log = await api.async_get_system_log(level=4)

    assert system_log.lines == ["a1", "a2", "b1", "c1", "c2", "d1"]
    assert system_log.complete is True
    assert router.builds == [4]
    assert router.reads == [0, 3, 2, 1]


@pytest.mark.asyncio
async def test_deadline_keeps_newest_unbroken_pages(api):
    router = _serve(api, [["a"], ["b"], ["c"], ["d"], ["e"]])
    router.page_responses[2] = [_hang]

    system_log = await api.async_get_system_log(deadline_seconds=0.05)

    # Page 0 was read for the page count but is not contiguous with 3 and 4.
    assert router.reads == [0, 4, 3, 2]
    assert system_log.lines == ["d", "e"]
    assert system_log.complete is False


@pytest.mark.asyncio
async def test_deadline_releases_lock_for_waiting_poller(api):
    router = _serve(api, [["a"], ["b"]])
    router.page_responses[1] = [_hang]

    download = asyncio.create_task(api.async_get_system_log(deadline_seconds=0.05))
    await asyncio.sleep(0)
    assert api._operation_lock.locked()

    async def poll():
        async with api._operation_lock:
            return "polled"

    async with asyncio.timeout(1):
        assert await poll() == "polled"
    system_log = await download
    assert system_log.complete is False
    assert not api._operation_lock.locked()


@pytest.mark.asyncio
async def test_deadline_includes_waiting_for_lock(api):
    router = _serve(api, [["a"]])

    async with api._operation_lock:
        system_log = await api.async_get_system_log(deadline_seconds=0.05)

    assert system_log.lines == []
    assert system_log.complete is False
    assert router.builds == []


@pytest.mark.asyncio
async def test_empty_page_is_retried_without_relogin(api):
    router = _serve(api, [["a"], ["b"]])
    router.page_responses[1] = [{"data": ""}, {"data": ""}]
    api.async_login = AsyncMock()

    system_log = await api.async_get_system_log()

    assert system_log.lines == ["a", "b"]
    assert router.reads == [0, 1, 1, 1]
    assert router.builds == [8]
    api.async_login.assert_not_awaited()
    assert api._stok == "token"


@pytest.mark.asyncio
async def test_retry_in_same_session_resumes_from_checkpoint(api):
    router = _serve(api, [["a"], ["b"], ["c"]])
    router.page_responses[1] = [TransientConnectionException("reset")]

    system_log = await api.async_get_system_log()

    assert system_log.lines == ["a", "b", "c"]
    assert router.builds == [8]
    assert router.reads == [0, 2, 1, 1]


@pytest.mark.asyncio
async def test_relogin_takes_new_snapshot(api):
    router = _serve(api, [["a"], ["b"], ["c"]])
    router.page_responses[1] = [{"data": ""}] * 3

    async def login():
        _authenticate(api, "fresh-token")

    api.async_login = AsyncMock(side_effect=login)

    system_log = await api.async_get_system_log()

    assert system_log.lines == ["a", "b", "c"]
    assert router.builds == [8, 8]
    assert router.reads == [0, 2, 1, 1, 1, 0, 2, 1]


@pytest.mark.asyncio
async def test_deadline_during_login_releases_lock(api):
    _serve(api, [["a"]])
    api.clear_auth()
    api._async_login = AsyncMock(side_effect=_hang)

    async with asyncio.timeout(1):
        system_log = await api.async_get_system_log(deadline_seconds=0.05)

    assert system_log.complete is False
    assert not api._operation_lock.locked()
    assert api._login_future is None
