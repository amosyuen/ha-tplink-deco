"""Test privacy-safe Deco HTTP 403 handling and bounded session recovery."""

import logging
import traceback
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import ForbiddenException

HOST = "http://192.0.2.1"
OLD_TOKEN = "synthetic-old-stok-private"
NEW_TOKEN = "synthetic-new-stok-private"
OLD_COOKIE = "sysauth=old-private-cookie"
NEW_COOKIE = "sysauth=new-private-cookie"
FORM_DATA = "synthetic-form-data"
DEVICE_FORM = {"form": "device_list"}


def _api() -> tuple[TplinkDecoApi, AsyncMock]:
    """Build an authenticated Deco API with no actual router connection."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=HOST,
        username="test-admin",
        password="synthetic-password",
        verify_ssl=True,
    )
    api._stok = OLD_TOKEN
    api._cookie = OLD_COOKIE
    api._seq = 7
    api._encode_payload = MagicMock(return_value=FORM_DATA)
    api._decrypt_data = MagicMock(
        return_value={"error_code": 0, "result": {"device_list": []}}
    )
    return api, session.post


def _response(token: str, *, forbidden: bool) -> MagicMock:
    """Return a mocked aiohttp response with a token-bearing 403 exception."""
    response = MagicMock()
    response.status = 403 if forbidden else 200
    response.history = ()
    response.headers.getall.return_value = []
    response.json = AsyncMock(return_value={"data": "synthetic-ciphertext"})
    if forbidden:
        request_info = MagicMock()
        request_info.real_url = f"{HOST}/cgi-bin/luci/;stok={token}/admin/device"
        request_info.url = request_info.real_url
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=request_info,
            history=(),
            status=403,
            message=f"Forbidden while using {token}",
        )
    return response


async def _relogin(api: TplinkDecoApi) -> None:
    """Install new mock credentials after the expired session is cleared."""
    assert (api._stok, api._cookie, api._seq) == (None, None, None)
    api._stok = NEW_TOKEN
    api._cookie = NEW_COOKIE
    api._seq = 11


def _mock_relogin(api: TplinkDecoApi) -> AsyncMock:
    """Build an awaited login mock that rotates the synthetic credentials."""

    async def _perform_login() -> None:
        """Complete the mocked authentication before the retry starts."""
        await _relogin(api)

    return AsyncMock(side_effect=_perform_login)


def _assert_device_request(request: Any, *, token: str, cookie: str) -> None:
    """Verify the exact token-bearing URL, form, payload and request cookie."""
    assert request.args == (f"{HOST}/cgi-bin/luci/;stok={token}/admin/device",)
    assert request.kwargs["params"] == DEVICE_FORM
    assert request.kwargs["data"] == FORM_DATA
    assert request.kwargs["cookies"] == {"sysauth": cookie}


@pytest.mark.asyncio
async def test_http_403_raises_privacy_safe_exception_without_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject 403 without leaking its URL, raw message, MAC or traceback."""
    api, post = _api()
    post.return_value = _response(OLD_TOKEN, forbidden=True)
    private_context = "Reboot Decos synthetic-secret-device-mac"

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ForbiddenException) as error:
            await api._async_post(
                private_context,
                f"{HOST}/cgi-bin/luci/;stok={OLD_TOKEN}/admin/device",
                params=DEVICE_FORM,
                data=FORM_DATA,
            )

    assert str(error.value) == "Deco API authentication forbidden (HTTP 403)"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert error.value.__suppress_context__
    assert (api._stok, api._cookie, api._seq) == (None, None, None)
    rendered_error = "".join(traceback.format_exception(error.value))
    for private_value in (OLD_TOKEN, OLD_COOKIE, private_context):
        assert private_value not in str(error.value)
        assert private_value not in rendered_error
        assert private_value not in caplog.text
    _assert_device_request(
        post.await_args, token=OLD_TOKEN, cookie="old-private-cookie"
    )


@pytest.mark.asyncio
async def test_device_list_403_relogs_in_with_fresh_token_and_cookie(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retry once after a 403 with a newly authenticated URL and cookie."""
    api, post = _api()
    post.side_effect = [
        _response(OLD_TOKEN, forbidden=True),
        _response(NEW_TOKEN, forbidden=False),
    ]
    api.async_login = _mock_relogin(api)

    with caplog.at_level(logging.DEBUG):
        result = await api.async_list_devices()

    assert result == []
    api.async_login.assert_awaited_once_with()
    assert post.await_count == 2
    _assert_device_request(
        post.await_args_list[0], token=OLD_TOKEN, cookie="old-private-cookie"
    )
    _assert_device_request(
        post.await_args_list[1], token=NEW_TOKEN, cookie="new-private-cookie"
    )
    assert (api._stok, api._cookie, api._seq) == (NEW_TOKEN, NEW_COOKIE, 11)
    for private_value in (OLD_TOKEN, NEW_TOKEN, OLD_COOKIE, NEW_COOKIE):
        assert private_value not in caplog.text


@pytest.mark.asyncio
async def test_repeated_device_list_403_stops_after_one_reauthentication(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not enter an unbounded auth-retry loop when replacement auth fails."""
    api, post = _api()
    post.side_effect = [
        _response(OLD_TOKEN, forbidden=True),
        _response(NEW_TOKEN, forbidden=True),
    ]
    api.async_login = _mock_relogin(api)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ForbiddenException) as error:
            await api.async_list_devices()

    assert str(error.value) == "Deco API authentication forbidden (HTTP 403)"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert error.value.__suppress_context__
    api.async_login.assert_awaited_once_with()
    assert post.await_count == 2
    _assert_device_request(
        post.await_args_list[0], token=OLD_TOKEN, cookie="old-private-cookie"
    )
    _assert_device_request(
        post.await_args_list[1], token=NEW_TOKEN, cookie="new-private-cookie"
    )
    assert (api._stok, api._cookie, api._seq) == (None, None, None)
    for private_value in (OLD_TOKEN, NEW_TOKEN, OLD_COOKIE, NEW_COOKIE):
        assert private_value not in caplog.text
