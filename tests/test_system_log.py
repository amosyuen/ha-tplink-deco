"""Tests for downloading the Deco system log through build and save_log."""

from __future__ import annotations

import asyncio
import gzip
import io
import tarfile
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.tplink_deco import api as api_module
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.api import _decode_system_log
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
    return _bytes_response(text.encode())


def _bytes_response(body):
    response = MagicMock()
    response.content_type = "text/plain"
    response.raise_for_status = MagicMock()
    response.read = AsyncMock(return_value=body)
    return response


def _tar(*files, links=False):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        directory = tarfile.TarInfo("./")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        if links:
            link = tarfile.TarInfo("syslog.log")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            archive.addfile(link)
        for name, payload in files:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


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
    ("body", "expected"),
    [
        (LOG_TEXT.encode(), LOG_TEXT),
        (gzip.compress(LOG_TEXT.encode()), LOG_TEXT),
        (_tar(("./syslog.log", LOG_TEXT.encode())), LOG_TEXT),
        (gzip.compress(_tar(("./syslog.log", LOG_TEXT.encode()))), LOG_TEXT),
        (gzip.compress(_tar(("deco.log", LOG_TEXT.encode()))), LOG_TEXT),
        (
            _tar(("not-syslog.log", b"wrong"), ("logs/syslog.log", LOG_TEXT.encode())),
            LOG_TEXT,
        ),
        (_tar(("first.log", LOG_TEXT.encode()), ("second.log", b"wrong")), LOG_TEXT),
        (_tar(("deco.log", LOG_TEXT.encode()), links=True), LOG_TEXT),
        (_tar(links=True), ""),
        (_tar(), ""),
        (gzip.compress(_tar()), ""),
        (_tar(("syslog.log", b"")), ""),
        (b"", ""),
        (b"first\xff\n", "first\ufffd\n"),
    ],
    ids=[
        "plain",
        "gzip",
        "tar",
        "gzip-tar",
        "gzip-tar-fallback",
        "exact-basename",
        "first-regular-file",
        "ignore-symlink",
        "links-only",
        "empty-tar",
        "empty-gzip-tar",
        "empty-member",
        "empty-text",
        "invalid-utf8",
    ],
)
async def test_decodes_save_log_bodies(api, session, body, expected):
    router = FakeRouter(api, session)
    router.save_responses.append(_bytes_response(body))

    assert await api.async_get_system_log() == expected
    assert len(router.saves) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"\x1f\x8bnot-gzip", gzip.compress(b"log")[:-5]])
async def test_corrupt_gzip_raises_clear_error_without_relogin(api, session, body):
    router = FakeRouter(api, session)
    router.save_responses.append(_bytes_response(body))
    _relogin(api)

    with pytest.raises(UnexpectedApiException, match="invalid gzip data"):
        await api.async_get_system_log()

    api.async_login.assert_not_awaited()
    assert len(router.saves) == 1


@pytest.mark.asyncio
async def test_truncated_tar_raises_clear_error(api, session):
    router = FakeRouter(api, session)
    body = _tar(("syslog.log", LOG_TEXT.encode()))[: 1024 + 5]
    router.save_responses.append(_bytes_response(body))

    with pytest.raises(UnexpectedApiException, match="invalid tar archive"):
        await api.async_get_system_log()


@pytest.mark.asyncio
async def test_snapshot_decoding_runs_outside_event_loop(api, session):
    FakeRouter(api, session)
    decode = _decode_system_log

    def check_thread(body):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        return decode(body)

    with patch.object(
        api_module, "_decode_system_log", side_effect=check_thread
    ) as worker:
        assert await api.async_get_system_log() == LOG_TEXT

    worker.assert_called_once_with(LOG_TEXT.encode())


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
