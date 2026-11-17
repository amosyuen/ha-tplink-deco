"""Regression tests for secret-free logging of generic Deco API failures."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import TimeoutException

HOST = "http://192.0.2.1"
TOKEN = "synthetic-private-stok-123"
COOKIE = "sysauth=synthetic-private-cookie-456"
SECRET_CONTEXT = "Reboot Decos synthetic-private-client-mac"
SECRET_MESSAGE = "synthetic-private-router-error"


def _api() -> tuple[TplinkDecoApi, AsyncMock]:
    """Return an authenticated router client with a mocked HTTP transport."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=HOST,
        username="test-admin",
        password="synthetic-password",
        verify_ssl=True,
    )
    api._stok = TOKEN
    api._cookie = COOKIE
    api._seq = 9
    return api, session.post


def _assert_private_values_absent(caplog: pytest.LogCaptureFixture) -> None:
    """Reject logging untrusted context, token, cookie or upstream error."""
    for private_value in (TOKEN, COOKIE, SECRET_CONTEXT, SECRET_MESSAGE):
        assert private_value not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "form", "auth_invalidated"),
    [
        (400, "device_list", False),
        (401, "device_list", True),
        (502, "device_list", False),
        (503, "client_list", False),
    ],
)
async def test_generic_http_error_logs_status_without_private_request(
    status: int,
    form: str,
    auth_invalidated: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve HTTP response-error semantics but omit private log strings."""
    api, post = _api()
    response = MagicMock()
    request_info = MagicMock()
    request_info.real_url = f"{HOST}/cgi-bin/luci/;stok={TOKEN}/admin/device"
    request_info.url = request_info.real_url
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=SECRET_MESSAGE,
    )
    post.return_value = response

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(aiohttp.ClientResponseError) as failure:
            await api._async_post(
                SECRET_CONTEXT,
                f"{HOST}/cgi-bin/luci/;stok={TOKEN}/admin/device",
                params={"form": form},
                data="synthetic-data",
            )

    assert failure.value.status == status
    _assert_private_values_absent(caplog)
    expected_log = {
        400: "Deco API HTTP error: 400",
        401: "Deco API authentication HTTP error: 401",
        502: "Deco API HTTP error: 502",
        503: "Deco client-list server error: HTTP 503",
    }[status]
    assert expected_log in caplog.text
    assert (api._stok is None) is auth_invalidated
    assert (api._cookie is None) is auth_invalidated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_failure", "error_type"),
    [
        (
            aiohttp.ClientConnectorError(
                SimpleNamespace(host=SECRET_MESSAGE, port=80, ssl=False),
                OSError(SECRET_MESSAGE),
            ),
            aiohttp.ClientConnectorError,
        ),
        (aiohttp.ClientError(SECRET_MESSAGE), aiohttp.ClientError),
    ],
)
async def test_generic_client_error_logs_type_without_private_details(
    transport_failure: aiohttp.ClientError,
    error_type: type[aiohttp.ClientError],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retain transport-exception types and authentication after failures."""
    api, post = _api()
    post.side_effect = transport_failure

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(error_type):
            await api._async_post(
                SECRET_CONTEXT,
                f"{HOST}/cgi-bin/luci/;stok={TOKEN}/admin/device",
                params={"form": "device_list"},
                data="synthetic-data",
            )

    assert (api._stok, api._cookie, api._seq) == (TOKEN, COOKIE, 9)
    _assert_private_values_absent(caplog)
    assert type(transport_failure).__name__ in caplog.text


@pytest.mark.asyncio
async def test_timeout_logs_no_private_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep timeout classification without logging router identifiers."""
    api, post = _api()
    post.side_effect = asyncio.TimeoutError(SECRET_MESSAGE)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TimeoutException):
            await api._async_post(
                SECRET_CONTEXT,
                f"{HOST}/cgi-bin/luci/;stok={TOKEN}/admin/device",
                params={"form": "device_list"},
                data="synthetic-data",
            )

    assert (api._stok, api._cookie, api._seq) == (TOKEN, COOKIE, 9)
    _assert_private_values_absent(caplog)
    assert "Deco API request timed out" in caplog.text
