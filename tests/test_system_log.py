"""Tests for downloading the Deco system log through build and save_log."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import UnexpectedApiException
from custom_components.tplink_deco.system_log import SystemLogLevel

LOG_TEXT = "Sat Nov  9 10:00:00 2026 user.err : first\nsecond line\n"


@pytest.fixture
def session():
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    return session


@pytest.fixture
def api(session):
    api = TplinkDecoApi(
        session=session,
        host="https://192.168.1.1",
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


class FakeRouter:
    """Answer "build" through _async_post and "save_log" through the session."""

    def __init__(self, api, session):
        self.api = api
        self.builds = []
        self.saves = []
        self.save_responses = []
        api._async_post = AsyncMock(side_effect=self.build)
        session.post.side_effect = self.save

    async def build(self, context, url, params, data):
        assert params == {"form": "feedback_log"}
        assert data["operation"] == "build"
        self.builds.append((self.api._stok, data["params"]["level"]))
        return {"data": {"error_code": 0}}

    async def save(self, url, params, data, cookies, ssl):
        assert params == {"form": "save_log"}
        self.saves.append((url, cookies))
        if self.save_responses:
            return self.save_responses.pop(0)
        return _text_response(LOG_TEXT)


def _text_response(text):
    response = MagicMock()
    response.content_type = "text/plain"
    response.raise_for_status = MagicMock()
    response.text = AsyncMock(return_value=text)
    return response


def _json_response(payload):
    response = MagicMock()
    response.content_type = "application/json"
    response.raise_for_status = MagicMock()
    response.json = AsyncMock(return_value=payload)
    return response


def _status_response(status):
    response = MagicMock()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=status
    )
    return response


def _relogin(api):
    async def login():
        _authenticate(api, "fresh-token")

    api.async_login = AsyncMock(side_effect=login)


@pytest.mark.asyncio
async def test_builds_at_level_then_saves_snapshot(api, session):
    router = FakeRouter(api, session)

    text = await api.async_get_system_log(SystemLogLevel.WARNING)

    assert text == LOG_TEXT
    assert router.builds == [("token", 4)]
    assert router.saves == [
        (
            "https://192.168.1.1/cgi-bin/luci/;stok=token/admin/log_export",
            {"sysauth": "abc"},
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expired",
    [
        lambda: _json_response({"success": False, "errorcode": "timeout"}),
        lambda: _status_response(403),
    ],
    ids=["errorcode-timeout", "http-403"],
)
async def test_expired_session_relogs_in_and_rebuilds(api, session, expired):
    router = FakeRouter(api, session)
    router.save_responses.append(expired())
    _relogin(api)

    text = await api.async_get_system_log()

    assert text == LOG_TEXT
    api.async_login.assert_awaited_once()
    assert router.builds == [("token", 8), ("fresh-token", 8)]


@pytest.mark.asyncio
async def test_other_error_is_not_retried_as_expired_session(api, session):
    router = FakeRouter(api, session)
    router.save_responses.append(_json_response({"errorcode": "-40401"}))
    _relogin(api)

    with pytest.raises(UnexpectedApiException, match="-40401"):
        await api.async_get_system_log()

    api.async_login.assert_not_awaited()
    assert len(router.builds) == 1


@pytest.mark.asyncio
async def test_outer_session_firmware_is_unsupported(api, session):
    router = FakeRouter(api, session)
    api._outer_id = "outer"

    with pytest.raises(UnexpectedApiException, match="not supported"):
        await api.async_get_system_log()

    assert router.builds == []
    assert router.saves == []
