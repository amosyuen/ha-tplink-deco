"""Regressions for privacy-safe LuCI payload errors and diagnostic logging."""

import base64
import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.api import check_data_error_code
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.exceptions import UnexpectedApiException

SECRET = "synthetic-private-router-payload"
HOST = "http://192.0.2.1"
SECRET_CONTEXT = f"List Clients {SECRET}"


def _api() -> tuple[TplinkDecoApi, AsyncMock]:
    """Create a Deco client with no network access and fake authentication."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=HOST,
        username="test-admin",
        password="synthetic-test-password",
        verify_ssl=True,
    )
    api._stok = "synthetic-session-token"
    api._cookie = "sysauth=synthetic-test-cookie"
    api._seq = 7
    return api, session.post


def _assert_redacted(caplog: pytest.LogCaptureFixture) -> None:
    """Ensure neither the firmware payload nor its caller context was logged."""
    assert SECRET not in caplog.text
    assert SECRET_CONTEXT not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "expected_code"),
    [(-6001, "-6001"), (SECRET, "unknown")],
)
async def test_http_api_rejection_redacts_payload_and_untrusted_codes(
    error_code: int | str,
    expected_code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep numeric API error codes while hiding raw firmware response data."""
    api, post = _api()
    response = MagicMock()
    response.history = ()
    response.headers.getall.return_value = []
    response.json = AsyncMock(
        return_value={
            "error_code": error_code,
            "result": {"device_name": SECRET},
        }
    )
    post.return_value = response

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException) as caught:
            await api._async_post(
                SECRET_CONTEXT,
                f"{HOST}/cgi-bin/luci/;stok={api._stok}/admin/client",
                params={"form": "client_list"},
                data="synthetic-request",
            )

    assert f"error_code={expected_code}" in str(caught.value)
    assert SECRET not in str(caught.value)
    _assert_redacted(caplog)
    assert "Deco API response reported an error" in caplog.text
    assert api._stok == "synthetic-session-token"


@pytest.mark.parametrize(
    ("error_code", "expected_code", "expected_error"),
    [
        (-6001, "-6001", UnexpectedApiException),
        (SECRET, "unknown", UnexpectedApiException),
        ("timeout", '"timeout"', TimeoutException),
    ],
)
def test_decrypted_error_code_does_not_expose_context_or_response(
    error_code: int | str,
    expected_code: str,
    expected_error: type[Exception],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retain error classification with only controlled diagnostic details."""
    payload = {"error_code": error_code, "result": {"device_name": SECRET}}
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(expected_error) as caught:
            check_data_error_code(SECRET_CONTEXT, payload)

    assert expected_code in str(caught.value)
    assert SECRET not in str(caught.value)
    _assert_redacted(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "missing_key"),
    [
        ("_async_list_devices", "device_list"),
        ("_async_list_clients", "client_list"),
    ],
)
async def test_malformed_device_or_client_lists_never_log_raw_payload(
    method: str,
    missing_key: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve a malformed-list KeyError without logging firmware details."""
    api, _ = _api()
    api.async_login_if_needed = AsyncMock()
    api._async_post = AsyncMock(return_value={"data": "ciphertext"})
    api._encode_payload = MagicMock(return_value="form-data")
    api._decrypt_data = MagicMock(
        return_value={"result": {"private_name": SECRET}}
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(KeyError, match=missing_key):
            if method == "_async_list_devices":
                await api._async_list_devices()
            else:
                await api._async_list_clients(SECRET)

    _assert_redacted(caplog)
    assert "parsing failed (KeyError)" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "error_label"),
    [
        ("_async_fetch_keys", "password key parsing failed"),
        ("_async_fetch_auth", "signing parameters parsing failed"),
    ],
)
async def test_invalid_login_metadata_never_logs_raw_router_response(
    method: str,
    error_label: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep an invalid login-metadata exception type without logging secrets."""
    api, _ = _api()
    api._async_post = AsyncMock(
        return_value={"result": {"private_secret": SECRET}}
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(KeyError):
            await getattr(api, method)()

    _assert_redacted(caplog)
    assert error_label in caplog.text


@pytest.mark.asyncio
async def test_successful_login_metadata_does_not_log_crypto_parameters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not reveal signing sequence values or large RSA parameters."""
    api, _ = _api()
    api._async_post = AsyncMock(
        side_effect=[
            {"result": {"password": [SECRET.encode().hex(), "11"]}},
            {"result": {"key": [SECRET.encode().hex(), "11"], "seq": SECRET}},
        ]
    )

    with caplog.at_level(logging.DEBUG):
        await api._async_fetch_keys()
        await api._async_fetch_auth()

    assert api._seq == SECRET
    _assert_redacted(caplog)
    assert "Deco password encryption key received" in caplog.text
    assert "Deco request signing key received" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", [-6001, 0])
async def test_login_response_errors_are_sanitized(
    error_code: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Never return a raw login response or retain it in debug logs."""
    api, _ = _api()
    api._aes_key = 123456789
    api._password_rsa_n = 11
    api._password_rsa_e = 17
    api._encode_payload = MagicMock(return_value="encoded-login")
    api._async_post = AsyncMock(return_value={"data": "ciphertext"})
    api._decrypt_data = MagicMock(
        return_value={
            "error_code": error_code,
            "result": {"private_value": SECRET},
        }
    )

    with patch(
        "custom_components.tplink_deco.api.rsa_encrypt",
        return_value="synthetic-encrypted-password",
    ):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(UnexpectedApiException) as caught:
                await api._async_login()

    assert SECRET not in str(caught.value)
    _assert_redacted(caplog)
    if error_code == -6001:
        assert str(caught.value) == "Deco login request was rejected"
    else:
        assert str(caught.value) == "Deco login response is malformed"
        assert caught.value.__suppress_context__


def test_decryption_failure_never_logs_encoded_data_or_upstream_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve decryption error classification without exposing ciphertext."""
    api, _ = _api()
    encrypted_data = base64.b64encode(SECRET.encode()).decode()
    with patch(
        "custom_components.tplink_deco.api.aes_decrypt",
        side_effect=ValueError(SECRET),
    ):
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ValueError, match=SECRET):
                api._decrypt_data(SECRET_CONTEXT, encrypted_data)

    _assert_redacted(caplog)
    assert encrypted_data not in caplog.text
    assert "Deco API response decoding failed (ValueError)" in caplog.text


@pytest.mark.asyncio
async def test_reboot_success_logs_no_private_mac(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep the reboot side effect but omit device identifiers from logging."""
    api, _ = _api()
    api.async_login_if_needed = AsyncMock()
    api._async_post = AsyncMock(return_value={"data": "ciphertext"})
    api._encode_payload = MagicMock(return_value="encoded-reboot")
    api._decrypt_data = MagicMock(return_value={"error_code": 0})

    with caplog.at_level(logging.DEBUG):
        await api._async_reboot_decos([SECRET])

    _assert_redacted(caplog)
    assert "Deco reboot request accepted" in caplog.text
    api._async_post.assert_awaited_once()
