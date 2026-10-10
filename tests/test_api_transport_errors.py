"""Regression tests for auth retention on transient transport errors."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
from aiohttp.client_reqrep import ConnectionKey
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import TransientConnectionException


@pytest.fixture
def mock_session():
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    return session


@pytest.fixture
def api(mock_session):
    return TplinkDecoApi(
        session=mock_session,
        host="http://192.168.1.1",
        username="admin",
        password="password",
        verify_ssl=False,
    )


def _authenticate(api):
    api._stok = "token"
    api._cookie = "sysauth=abc"
    api._seq = 1


def _assert_authenticated(api):
    assert api._stok == "token"
    assert api._cookie == "sysauth=abc"
    assert api._seq == 1


def _connector_error():
    connection_key = ConnectionKey(
        host="192.168.1.1",
        port=80,
        is_ssl=False,
        ssl=None,
        proxy=None,
        proxy_auth=None,
        proxy_headers_hash=None,
    )
    return aiohttp.ClientConnectorError(connection_key, OSError("connection refused"))


def _response(payload):
    response = MagicMock()
    response.status = 200
    response.history = ()
    response.headers.getall.return_value = []
    response.json = AsyncMock(return_value=payload)
    response.raise_for_status = MagicMock()
    return response


def _setup_device_list_call(api):
    api._encode_payload = MagicMock(return_value="payload")
    api._decrypt_data = MagicMock(return_value={"result": {"device_list": []}})


@pytest.mark.asyncio
async def test_async_post_server_disconnected_keeps_auth(api, mock_session):
    _authenticate(api)
    mock_session.post.side_effect = aiohttp.ServerDisconnectedError()

    with pytest.raises(TransientConnectionException):
        await api._async_post("List Devices", f"{api._host}/path", params={}, data="x")

    _assert_authenticated(api)


@pytest.mark.asyncio
async def test_async_post_client_connector_error_keeps_auth(api, mock_session):
    _authenticate(api)
    mock_session.post.side_effect = _connector_error()

    with pytest.raises(aiohttp.ClientConnectorError):
        await api._async_post("List Devices", f"{api._host}/path", params={}, data="x")

    _assert_authenticated(api)


@pytest.mark.asyncio
async def test_async_post_payload_error_keeps_auth(api, mock_session):
    _authenticate(api)
    mock_session.post.side_effect = aiohttp.ClientPayloadError("truncated")

    with pytest.raises(TransientConnectionException):
        await api._async_post("List Devices", f"{api._host}/path", params={}, data="x")

    _assert_authenticated(api)


@pytest.mark.asyncio
async def test_async_list_devices_retry_after_disconnect_does_not_relogin(
    api, mock_session
):
    _authenticate(api)
    _setup_device_list_call(api)
    device_posts = 0
    login_posts = []

    async def post(url, params=None, **kwargs):
        nonlocal device_posts
        if params.get("form") == "login":
            login_posts.append((url, params))
            return _response({})

        device_posts += 1
        if device_posts == 1:
            raise aiohttp.ServerDisconnectedError()
        return _response({"data": "encrypted"})

    async def login():
        await mock_session.post(
            f"{api._host}/cgi-bin/luci/;stok=/login",
            params={"form": "login"},
            data="payload",
        )
        _authenticate(api)

    mock_session.post.side_effect = post
    api.async_login = AsyncMock(side_effect=login)

    with patch(
        "custom_components.tplink_deco.api.asyncio.sleep", new_callable=AsyncMock
    ):
        result = await api.async_list_devices()

    assert result == []
    assert device_posts == 2
    assert login_posts == []


@pytest.mark.asyncio
async def test_async_list_devices_403_relogs_in(api, mock_session):
    _authenticate(api)
    _setup_device_list_call(api)
    device_posts = 0
    login_posts = []

    async def post(url, params=None, **kwargs):
        nonlocal device_posts
        if params.get("form") == "login":
            login_posts.append((url, params))
            return _response({})

        device_posts += 1
        if device_posts == 1:
            response = _response({})
            response.raise_for_status.side_effect = aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=403,
                message="Forbidden",
            )
            return response
        return _response({"data": "encrypted"})

    async def login():
        await mock_session.post(
            f"{api._host}/cgi-bin/luci/;stok=/login",
            params={"form": "login"},
            data="payload",
        )
        _authenticate(api)

    mock_session.post.side_effect = post
    api.async_login = AsyncMock(side_effect=login)

    result = await api.async_list_devices()

    assert result == []
    assert device_posts == 2
    assert len(login_posts) == 1
    assert login_posts[0][1]["form"] == "login"
    _assert_authenticated(api)
