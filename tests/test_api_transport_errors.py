"""Regression tests for auth retention on transient transport errors."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
from aiohttp.client_reqrep import ConnectionKey
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.api import aes_encrypt
from custom_components.tplink_deco.exceptions import EmptyDataException
from custom_components.tplink_deco.exceptions import TransientConnectionException
from custom_components.tplink_deco.exceptions import UnexpectedApiException


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


def _authenticate_outer(api):
    api._use_outer_session = True
    api._outer_id = "stale-id"
    api._outer_aes_key = "0123456789abcdef"
    api._outer_aes_key_bytes = api._outer_aes_key.encode()
    api._outer_aes_iv = "abcdef0123456789"
    api._outer_aes_iv_bytes = api._outer_aes_iv.encode()
    api._outer_rsa_n = 123
    api._outer_rsa_e = 65537
    api._outer_seq = 0
    api._seq = 0
    api._stok = ""
    api._cookie = "outer=1"
    api._encode_outer_payload = MagicMock(return_value="payload")


def _outer_response(text, status=200):
    response = _response({})
    response.status = status
    response.text = AsyncMock(return_value=text)
    return response


def _encrypted_outer_response(key, iv):
    payload = json.dumps({"result": {"device_list": []}, "error_code": 0}).encode()
    encrypted = aes_encrypt(key.encode(), iv.encode(), payload)
    return base64.b64encode(encrypted).decode()


def _setup_outer_recovery(api, mock_session, stale_response):
    _authenticate_outer(api)
    fresh_key = "fedcba9876543210"
    fresh_iv = "0011223344556677"
    state = {"outer_logins": 0, "post_count": 0}
    fresh_response = _encrypted_outer_response(fresh_key, fresh_iv)

    async def fresh_login():
        state["outer_logins"] += 1
        api._outer_id = "fresh-id"
        api._outer_aes_key = fresh_key
        api._outer_aes_key_bytes = fresh_key.encode()
        api._outer_aes_iv = fresh_iv
        api._outer_aes_iv_bytes = fresh_iv.encode()
        api._outer_rsa_n = 123
        api._outer_rsa_e = 65537
        api._outer_seq = 0

    async def post(url, params=None, **kwargs):
        if state["post_count"] == 0:
            state["post_count"] += 1
            raise _connector_error()
        if params["id"] == "fresh-id":
            return _outer_response(fresh_response)
        assert params["id"] == "stale-id"
        return stale_response()

    api._async_outer_login = AsyncMock(side_effect=fresh_login)
    mock_session.post.side_effect = post
    return state


@pytest.mark.asyncio
async def test_outer_session_empty_response_after_reboot_relogs_in(api, mock_session):
    state = _setup_outer_recovery(
        api,
        mock_session,
        stale_response=lambda: _outer_response(""),
    )

    with pytest.raises(aiohttp.ClientConnectorError):
        await api.async_list_devices()
    assert api._outer_id == "stale-id"

    result = await api.async_list_devices()

    assert result == []
    assert state["outer_logins"] == 1
    assert api._outer_id == "fresh-id"


@pytest.mark.asyncio
async def test_outer_session_undecodable_response_after_reboot_relogs_in(
    api, mock_session
):
    stale_response = base64.b64encode(
        aes_encrypt(
            b"fedcba9876543210",
            b"1234567890abcdef",
            json.dumps({"result": {"device_list": []}, "error_code": 0}).encode(),
        )
    ).decode()
    state = _setup_outer_recovery(
        api,
        mock_session,
        stale_response=lambda: _outer_response(stale_response),
    )

    with pytest.raises(aiohttp.ClientConnectorError):
        await api.async_list_devices()
    assert api._outer_id == "stale-id"

    result = await api.async_list_devices()

    assert result == []
    assert state["outer_logins"] == 1
    assert api._outer_id == "fresh-id"


@pytest.mark.asyncio
async def test_outer_session_401_after_reboot_relogs_in_on_next_call(api, mock_session):
    def unauthorized_response():
        response = _outer_response("", status=401)
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=401,
        )
        return response

    state = _setup_outer_recovery(
        api,
        mock_session,
        stale_response=unauthorized_response,
    )

    with pytest.raises(aiohttp.ClientConnectorError):
        await api.async_list_devices()
    assert api._outer_id == "stale-id"

    with pytest.raises(aiohttp.ClientResponseError):
        await api.async_list_devices()
    assert api._outer_id is None

    result = await api.async_list_devices()

    assert result == []
    assert state["outer_logins"] == 1
    assert api._outer_id == "fresh-id"


@pytest.mark.asyncio
async def test_authenticated_top_level_5002_clears_auth(api, mock_session):
    _authenticate(api)
    mock_session.post.return_value = _response({"error_code": -5002})

    with pytest.raises(EmptyDataException):
        await api._async_post(
            "List Devices",
            f"{api._host}/cgi-bin/luci/;stok={api._stok}/admin/device",
            params={"form": "device_list"},
            data="payload",
        )

    assert api._stok is None
    assert api._cookie is None
    assert api._seq is None


@pytest.mark.asyncio
async def test_login_top_level_5002_is_not_treated_as_expired_session(
    api, mock_session
):
    mock_session.post.return_value = _response({"error_code": -5002})

    with pytest.raises(UnexpectedApiException):
        await api._async_post(
            "Login",
            f"{api._host}/cgi-bin/luci/;stok=/login",
            params={"form": "login"},
            data="payload",
        )


@pytest.mark.asyncio
async def test_encrypted_5002_relogs_in_once(api):
    _authenticate(api)
    api._encode_payload = MagicMock(return_value="payload")
    api._async_post = AsyncMock(return_value={"data": "encrypted"})
    api._decrypt_data = MagicMock(
        side_effect=[
            {"error_code": -5002},
            {"error_code": 0, "result": {"device_list": []}},
        ]
    )

    async def login():
        _authenticate(api)

    api.async_login = AsyncMock(side_effect=login)

    assert await api.async_list_devices() == []
    api.async_login.assert_awaited_once()


@pytest.mark.asyncio
async def test_outer_top_level_5002_relogs_in_once(api, mock_session):
    stale_response = base64.b64encode(
        aes_encrypt(
            b"0123456789abcdef",
            b"abcdef0123456789",
            json.dumps({"result": {}, "error_code": -5002}).encode(),
        )
    ).decode()
    state = _setup_outer_recovery(
        api, mock_session, stale_response=lambda: _outer_response(stale_response)
    )

    with pytest.raises(aiohttp.ClientConnectorError):
        await api.async_list_devices()

    assert await api.async_list_devices() == []
    assert state["outer_logins"] == 1
    assert api._outer_id == "fresh-id"
