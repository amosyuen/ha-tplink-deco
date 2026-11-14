"""Regression tests for authenticated Deco session expiry error -5002."""

import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import EmptyDataException
from custom_components.tplink_deco.exceptions import UnexpectedApiException

HOST = "http://192.0.2.1"
OLD_TOKEN = "synthetic-old-session"
NEW_TOKEN = "synthetic-new-session"
OLD_COOKIE = "sysauth=deadbeef"
NEW_COOKIE = "sysauth=feedface"


def _api() -> tuple[TplinkDecoApi, AsyncMock]:
    """Construct an authenticated API with a mocked aiohttp transport."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=HOST,
        username="admin",
        password="unused-test-password",
        verify_ssl=True,
    )
    api._stok = OLD_TOKEN
    api._cookie = OLD_COOKIE
    api._seq = 17
    api._encode_payload = MagicMock(return_value="synthetic-payload")
    return api, session.post


def _response(payload: dict[str, object]) -> MagicMock:
    """Provide a successful HTTP response with a mocked JSON body."""
    response = MagicMock()
    response.history = ()
    response.headers.getall.return_value = []
    response.raise_for_status = MagicMock()
    response.json = AsyncMock(return_value=payload)
    return response


async def _relogin(api: TplinkDecoApi) -> None:
    """Simulate one successful new router login after auth invalidation."""
    assert (api._stok, api._cookie, api._seq) == (None, None, None)
    api._stok = NEW_TOKEN
    api._cookie = NEW_COOKIE
    api._seq = 29


def _assert_auth_cleared(api: TplinkDecoApi) -> None:
    """Assert the expired local session has been fully invalidated."""
    assert (api._stok, api._cookie, api._seq) == (None, None, None)


@pytest.mark.asyncio
async def test_authenticated_top_level_5002_invalidates_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Turn an authenticated top-level expiry into a relogin-triggering error."""
    api, post = _api()
    post.return_value = _response({"error_code": -5002})
    authenticated_url = f"{HOST}/cgi-bin/luci/;stok={OLD_TOKEN}/admin/device"

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(EmptyDataException, match="-5002"):
            await api._async_post(
                "List Devices", authenticated_url, params={}, data="payload"
            )

    _assert_auth_cleared(api)
    assert OLD_TOKEN not in caplog.text
    assert OLD_COOKIE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("request_url", [
    f"{HOST}/cgi-bin/luci/;stok=/login",
    f"{HOST}/cgi-bin/luci/;stok={OLD_TOKEN}/login",
    "http://other.example/cgi-bin/luci/;stok=synthetic-old-session/admin/device",
])
async def test_non_authenticated_5002_does_not_invalidate_existing_auth(
    request_url: str,
) -> None:
    """Avoid treating login or other-router error codes as stale Deco sessions."""
    api, post = _api()
    post.return_value = _response({"error_code": -5002})

    with pytest.raises(UnexpectedApiException, match="-5002"):
        await api._async_post("Login", request_url, params={}, data="payload")

    assert (api._stok, api._cookie, api._seq) == (OLD_TOKEN, OLD_COOKIE, 17)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_field", ["error_code", "errorcode"])
async def test_decrypted_5002_invalidates_auth_for_both_firmware_keys(
    error_field: str,
) -> None:
    """Handle the supported encrypted error-code keys without leaking payloads."""
    api, _ = _api()

    with pytest.raises(EmptyDataException, match="-5002"):
        api._check_authenticated_data_error_code(
            "List Devices", {error_field: -5002, "result": {}}
        )

    _assert_auth_cleared(api)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "args", "successful_result", "expected_result"),
    [
        ("async_list_devices", (), {"result": {"device_list": []}}, []),
        ("async_list_clients", ("default",), {"result": {"client_list": []}}, []),
        (
            "async_get_performance",
            (),
            {"result": {"cpu_usage": 0.25}},
            {"error_code": 0, "result": {"cpu_usage": 0.25}},
        ),
        ("async_reboot_decos", (["AA:BB:CC:DD:EE:01"],), {"result": {}}, None),
    ],
)
async def test_encrypted_5002_relogs_in_once_for_authenticated_actions(
    method_name: str,
    args: tuple[object, ...],
    successful_result: dict[str, object],
    expected_result: object,
) -> None:
    """Reuse the existing one-time auth retry across all authenticated APIs."""
    api, _ = _api()
    api._async_post = AsyncMock(return_value={"data": "synthetic-ciphertext"})
    api._decrypt_data = MagicMock(
        side_effect=[
            {"error_code": -5002, "result": {}},
            {"error_code": 0, **successful_result},
        ]
    )
    api.async_login = AsyncMock(side_effect=lambda: _relogin(api))

    result = await getattr(api, method_name)(*args)

    assert result == expected_result
    api.async_login.assert_awaited_once()
    assert api._async_post.await_count == 2
    assert f";stok={OLD_TOKEN}/" in api._async_post.await_args_list[0].args[1]
    assert f";stok={NEW_TOKEN}/" in api._async_post.await_args_list[1].args[1]
    assert (api._stok, api._cookie, api._seq) == (NEW_TOKEN, NEW_COOKIE, 29)


@pytest.mark.asyncio
async def test_second_decrypted_5002_stops_after_one_relogin() -> None:
    """Never loop forever or create more than one replacement session."""
    api, _ = _api()
    api._async_post = AsyncMock(return_value={"data": "synthetic-ciphertext"})
    api._decrypt_data = MagicMock(return_value={"error_code": -5002})
    api.async_login = AsyncMock(side_effect=lambda: _relogin(api))

    with pytest.raises(EmptyDataException, match="-5002"):
        await api.async_list_devices()

    api.async_login.assert_awaited_once()
    assert api._async_post.await_count == 2
    _assert_auth_cleared(api)


@pytest.mark.asyncio
async def test_top_level_5002_recovers_on_the_next_authenticated_attempt() -> None:
    """Check end-to-end retry through real _async_post and fake aiohttp responses."""
    api, post = _api()
    post.side_effect = [
        _response({"error_code": -5002}),
        _response({"data": "synthetic-ciphertext"}),
    ]
    api._decrypt_data = MagicMock(
        return_value={"error_code": 0, "result": {"device_list": []}}
    )
    api.async_login = AsyncMock(side_effect=lambda: _relogin(api))

    assert await api.async_list_devices() == []
    api.async_login.assert_awaited_once()
    assert post.await_count == 2
    assert post.await_args_list[0].kwargs["cookies"] == {"sysauth": "deadbeef"}
    assert post.await_args_list[1].kwargs["cookies"] == {"sysauth": "feedface"}


@pytest.mark.asyncio
async def test_non_expiry_encrypted_errors_keep_original_error_handling() -> None:
    """Continue to surface other API errors without clearing valid sessions."""
    api, _ = _api()
    with pytest.raises(UnexpectedApiException, match="error_code=-6001"):
        api._check_authenticated_data_error_code(
            "List Devices", {"error_code": -6001}
        )
    assert (api._stok, api._cookie, api._seq) == (OLD_TOKEN, OLD_COOKIE, 17)


@pytest.mark.asyncio
async def test_http_500_still_does_not_invalidate_auth() -> None:
    """Keep ordinary server errors distinct from an explicit expiry code."""
    api, post = _api()
    response = _response({})
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=500, message="server failure"
    )
    post.return_value = response

    with pytest.raises(aiohttp.ClientResponseError):
        await api._async_post(
            "List Devices",
            f"{HOST}/cgi-bin/luci/;stok={OLD_TOKEN}/admin/device",
            params={},
            data="payload",
        )

    assert (api._stok, api._cookie, api._seq) == (OLD_TOKEN, OLD_COOKIE, 17)
