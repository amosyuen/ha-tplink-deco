"""Regression coverage for preserving Deco sessions on transport failures."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import ForbiddenException
from custom_components.tplink_deco.exceptions import TransientConnectionException

HOST = "http://192.0.2.1"
STOK = "test-stok"
COOKIE = "sysauth=deadbeef"
SEQUENCE = 42


def _authenticated_api() -> tuple[TplinkDecoApi, AsyncMock]:
    """Build an authenticated Deco API using an isolated aiohttp mock."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=HOST,
        username="admin",
        password="test-placeholder",
        verify_ssl=True,
    )
    api._stok = STOK
    api._cookie = COOKIE
    api._seq = SEQUENCE
    return api, session.post


def _connector_error() -> aiohttp.ClientConnectorError:
    """Create a real aiohttp connection error without a live connection."""
    connection_key = SimpleNamespace(host="192.0.2.1", port=80, ssl=False)
    return aiohttp.ClientConnectorError(connection_key, OSError("offline"))


def _successful_response() -> MagicMock:
    """Return an HTTP response with a valid encrypted-payload placeholder."""
    response = MagicMock()
    response.status = 200
    response.headers.getall.return_value = []
    response.raise_for_status = MagicMock()
    response.json = AsyncMock(return_value={"data": "test-payload"})
    return response


def _assert_session_retained(api: TplinkDecoApi) -> None:
    """Verify the session token, cookie and sequence remain unchanged."""
    assert api._stok == STOK
    assert api._cookie == COOKIE
    assert api._seq == SEQUENCE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "error_type"),
    [
        (aiohttp.ServerDisconnectedError(), TransientConnectionException),
        (_connector_error(), aiohttp.ClientConnectorError),
        (aiohttp.ClientPayloadError("incomplete body"), TransientConnectionException),
    ],
)
async def test_transport_failure_keeps_existing_authentication(
    transport_error: aiohttp.ClientError,
    error_type: type[aiohttp.ClientError],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not discard valid auth merely because the network connection failed."""
    api, post = _authenticated_api()
    post.side_effect = transport_error

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(error_type):
            await api._async_post(
                "List Devices", f"{HOST}/admin/device", params={}, data="test-data"
            )

    _assert_session_retained(api)
    assert STOK not in caplog.text
    assert COOKIE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "should_clear"),
    [(401, True), (403, True), (500, False)],
)
async def test_response_status_preserves_existing_auth_expiry_policy(
    status: int, should_clear: bool
) -> None:
    """401/403 still invalidate auth, while other HTTP errors do not."""
    api, post = _authenticated_api()
    response = _successful_response()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=status,
        message="status",
    )
    post.return_value = response

    expected_error = (
        ForbiddenException if status == 403 else aiohttp.ClientResponseError
    )
    with pytest.raises(expected_error):
        await api._async_post(
            "List Devices", f"{HOST}/admin/device", params={}, data="test-data"
        )

    if should_clear:
        assert api._stok is None
        assert api._cookie is None
        assert api._seq is None
    else:
        _assert_session_retained(api)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [
        aiohttp.ServerDisconnectedError(),
        aiohttp.ClientPayloadError("incomplete payload"),
        _connector_error(),
    ],
)
async def test_next_device_update_reuses_session_without_login(
    transport_error: aiohttp.ClientError,
) -> None:
    """Use the retained cookie and token on the next successful device poll."""
    api, post = _authenticated_api()
    api._encode_payload = MagicMock(return_value="encoded-placeholder")
    api._decrypt_data = MagicMock(return_value={"result": {"device_list": []}})
    api.async_login = AsyncMock()
    post.side_effect = [transport_error, _successful_response()]

    if isinstance(transport_error, aiohttp.ClientConnectorError):
        # Unrelated connector failures still propagate without an auto-retry.
        with pytest.raises(aiohttp.ClientConnectorError):
            await api.async_list_devices()
        assert await api.async_list_devices() == []
    else:
        # Disconnects and incomplete bodies now recover within one poll.
        assert await api.async_list_devices() == []

    _assert_session_retained(api)
    assert post.await_count == 2
    assert post.await_args_list[0].kwargs["cookies"] == {"sysauth": "deadbeef"}
    assert post.await_args_list[1].kwargs["cookies"] == {"sysauth": "deadbeef"}
    api.async_login.assert_not_awaited()


@pytest.mark.asyncio
async def test_unauthenticated_transport_failure_does_not_invent_session() -> None:
    """Preserve the absence of credentials before a first successful login."""
    api, post = _authenticated_api()
    api.clear_auth()
    post.side_effect = aiohttp.ServerDisconnectedError()

    with pytest.raises(TransientConnectionException):
        await api._async_post("List Devices", f"{HOST}/path", params={}, data="x")

    assert api._stok is None
    assert api._cookie is None
    assert api._seq is None
