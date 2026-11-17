"""Regression tests for the manual Deco plain-text system-log API."""

import asyncio
import logging
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco.api import SYSTEM_LOG_CONTEXT
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import ForbiddenException
from custom_components.tplink_deco.exceptions import UnexpectedApiException
from custom_components.tplink_deco.system_log import MAX_SYSTEM_LOG_BYTES
from custom_components.tplink_deco.system_log import SystemLogLevel

SECRET = "PRIVATE_ROUTER_TOKEN_123"


def _api_and_session() -> tuple[TplinkDecoApi, MagicMock]:
    """Create an authenticated API with a mocked HTTP session."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host="https://192.0.2.1",
        username="example",
        password="synthetic-secret",
        verify_ssl=True,
    )
    api._stok = SECRET
    api._cookie = "sysauth=PRIVATE_COOKIE"
    api._seq = 4
    api._encode_payload = MagicMock(return_value="encoded-data")
    api._async_post = AsyncMock(return_value={"data": "encrypted-placeholder"})
    api._decrypt_data = MagicMock(return_value={"error_code": 0})
    return api, session


def _response(
    body: bytes = b"first line\nsecond line\n",
    *,
    content_type: str = "text/plain",
    status: int = 200,
) -> MagicMock:
    """Return a simulated aiohttp response with bounded content reading."""
    response = MagicMock()
    response.content_type = content_type
    response.status = status
    response.history = ()
    response.content.read = AsyncMock(
        side_effect=[
            body[index : index + 65536] for index in range(0, len(body), 65536)
        ]
        + [b""]
    )
    response.release = MagicMock()
    response.raise_for_status = MagicMock()
    if status >= 400:
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=SimpleNamespace(real_url=f"https://router/;stok={SECRET}"),
            history=(),
            status=status,
            message=SECRET,
        )
    return response


@pytest.mark.asyncio
async def test_build_then_save_once_at_selected_level() -> None:
    """Build a filtered snapshot, then read its plain-text bytes one time."""
    api, session = _api_and_session()
    session.post.return_value = _response()

    result = await api.async_get_system_log(SystemLogLevel.WARNING)

    assert result == "first line\nsecond line\n"
    api._async_post.assert_awaited_once()
    assert api._async_post.await_args.args[0] == SYSTEM_LOG_CONTEXT
    assert api._async_post.await_args.kwargs["params"] == {"form": "feedback_log"}
    api._encode_payload.assert_called_once_with(
        {"operation": "build", "params": {"level": 4}}
    )
    assert session.post.await_args.kwargs["params"] == {"form": "save_log"}
    assert session.post.await_args.kwargs["cookies"] == {"sysauth": "PRIVATE_COOKIE"}
    assert session.post.return_value.content.read.await_count == 2
    session.post.return_value.content.read.assert_any_await(65536)
    session.post.return_value.release.assert_called_once()


@pytest.mark.asyncio
async def test_save_403_reauthenticates_once_with_fresh_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stale save token triggers one bounded rebuild and no secret logging."""
    api, session = _api_and_session()
    session.post.side_effect = [_response(status=403), _response(b"ok\n")]

    async def _login() -> None:
        """Provide a fresh synthetic login after invalidation."""
        api._stok = "new-token"
        api._cookie = "sysauth=new-cookie"
        api._seq = 3

    api.async_login = AsyncMock(side_effect=_login)
    with caplog.at_level(logging.DEBUG):
        result = await api.async_get_system_log()

    assert result == "ok\n"
    assert session.post.await_count == 2
    assert api._async_post.await_count == 2
    api.async_login.assert_awaited_once()
    assert SECRET not in caplog.text
    assert "PRIVATE_COOKIE" not in caplog.text


@pytest.mark.asyncio
async def test_repeated_403_stops_after_one_reauthentication() -> None:
    """Do not retry an expired log session without a finite limit."""
    api, session = _api_and_session()
    session.post.side_effect = [_response(status=403), _response(status=403)]

    async def _login() -> None:
        """Supply a second token for the one permitted retry."""
        api._stok = "fresh"
        api._cookie = "sysauth=fresh"
        api._seq = 3

    api.async_login = AsyncMock(side_effect=_login)
    with pytest.raises(ForbiddenException, match="System log authentication expired"):
        await api.async_get_system_log()

    assert session.post.await_count == 2
    api.async_login.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_json_response_reauthenticates_once() -> None:
    """Treat firmware timeout from save_log as an auth-expiry signal."""
    api, session = _api_and_session()
    session.post.side_effect = [
        _response(b'{"errorcode": "timeout"}', content_type="application/json"),
        _response(b"success\n"),
    ]

    async def _login() -> None:
        """Restore a fresh synthetic session."""
        api._stok = "fresh"
        api._cookie = "sysauth=fresh"
        api._seq = 3

    api.async_login = AsyncMock(side_effect=_login)
    assert await api.async_get_system_log() == "success\n"
    assert session.post.await_count == 2
    api.async_login.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response(b"bad", content_type="application/octet-stream"), "unsupported"),
        (_response(b"not-json", content_type="application/json"), "malformed"),
        (_response(b"\x1f\x8bcompressed"), "unsupported"),
        (_response(b"\x00" * 257 + b"ustar" + b"\x00"), "unsupported"),
        (_response(b"\xff\xfe"), "encoding"),
        (_response(b"Z" * (MAX_SYSTEM_LOG_BYTES + 1)), "size limit"),
        (
            _response(b'{"errorcode": "-42"}', content_type="application/json"),
            "rejected",
        ),
        (_response(status=502), "HTTP request failed"),
    ],
)
async def test_rejects_bad_save_responses_without_raw_data(
    response: MagicMock, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Reject unsupported, malformed, oversized and HTTP error responses."""
    api, session = _api_and_session()
    session.post.return_value = response

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException, match=message) as caught:
            await api.async_get_system_log()

    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text
    response.release.assert_called_once()


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    """Never convert cancellation into a router or service error."""
    api, session = _api_and_session()
    session.post.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await api.async_get_system_log()


@pytest.mark.asyncio
async def test_log_build_http_error_does_not_log_authenticated_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exercise the bound shared HTTP method, not a mocked build method."""
    api, session = _api_and_session()
    api._async_post = TplinkDecoApi._async_post.__get__(api)
    session.post.return_value = _response(status=503)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException, match="System log HTTP") as caught:
            await api._async_post(
                SYSTEM_LOG_CONTEXT,
                api._log_export_url(),
                params={"form": "feedback_log"},
                data="encoded",
            )

    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_log_build_decrypt_failure_does_not_log_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed private log-build ciphertext cannot enter DEBUG logs."""
    api, _session = _api_and_session()
    api._decrypt_data = TplinkDecoApi._decrypt_data.__get__(api)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException, match="System log response"):
            api._decrypt_data(SYSTEM_LOG_CONTEXT, "PRIVATE_CIPHERTEXT")

    assert "PRIVATE_CIPHERTEXT" not in caplog.text
