"""Regression coverage for per-entry HTTP-only and HTTPS transport policy."""

from copy import deepcopy
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
import pytest

from custom_components.tplink_deco import config_flow
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import CONF_USE_HTTPS
from custom_components.tplink_deco.const import CONF_VERIFY_SSL
from custom_components.tplink_deco.exceptions import HttpsRequiredException
from custom_components.tplink_deco.exceptions import UnsafeRedirectException

HOST = "192.0.2.1"
SECRET = "synthetic-private-session-token"
COOKIE = "sysauth=deadbeef"
HOST_HTTP = f"http://{HOST}"
HOST_HTTPS = f"https://{HOST}"
REQUEST_PATH = "/cgi-bin/luci/;stok=synthetic-private-session-token/admin/device"
FORM = {"form": "device_list"}


def _api(
    *, host: str = HOST_HTTP, use_https: bool = True
) -> tuple[TplinkDecoApi, AsyncMock]:
    """Create a real API object with a mocked aiohttp session."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=host,
        username="admin",
        password="dummy-password",
        verify_ssl=True,
        use_https=use_https,
    )
    api._stok = SECRET
    api._cookie = COOKIE
    api._seq = 5
    return api, session.post


def _response(status: int = 200, *, location: str | None = None) -> MagicMock:
    """Return a synthetic firmware HTTP response with no private payload."""
    response = MagicMock()
    response.status = status
    response.headers.get.return_value = location
    response.headers.getall.return_value = []
    response.json = AsyncMock(return_value={"data": "encoded-data"})
    response.raise_for_status = MagicMock()
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect_status", [307, 308])
async def test_same_router_upgrade_preserves_post_fields_and_session(
    redirect_status: int, caplog: pytest.LogCaptureFixture
) -> None:
    """Use the HTTPS redirect's port without leaking the session to another host."""
    api, post = _api()
    location = f"https://{HOST}:8443{REQUEST_PATH}"
    first = _response(redirect_status, location=location)
    post.side_effect = [first, _response()]

    with caplog.at_level(logging.DEBUG):
        result = await api._async_post(
            "List Devices",
            HOST_HTTP + REQUEST_PATH,
            params=FORM,
            data="synthetic-encrypted-request",
        )

    assert result == {"data": "encoded-data"}
    assert first.release.call_count == 1
    assert api._host == f"https://{HOST}:8443"
    assert api._stok == SECRET
    assert api._cookie == COOKIE
    assert post.await_count == 2
    assert post.await_args_list[0].args[0] == HOST_HTTP + REQUEST_PATH
    assert post.await_args_list[1].args[0] == location
    for call in post.await_args_list:
        assert call.kwargs["allow_redirects"] is False
        assert call.kwargs["params"] == FORM
        assert call.kwargs["cookies"] == {"sysauth": "deadbeef"}
        assert call.kwargs["data"] == "synthetic-encrypted-request"
    assert SECRET not in caplog.text
    assert COOKIE not in caplog.text


@pytest.mark.asyncio
async def test_legacy_default_and_direct_https_are_backward_compatible() -> None:
    """Omitted transport setting accepts HTTPS and direct HTTPS avoids redirect."""
    api, post = _api(host=HOST_HTTPS)
    post.return_value = _response()
    await api._async_post(
        "List Devices", HOST_HTTPS + REQUEST_PATH, params=FORM, data="test"
    )
    assert api._host == HOST_HTTPS
    assert post.await_count == 1
    assert post.await_args.kwargs["allow_redirects"] is False

    session = MagicMock(spec=aiohttp.ClientSession)
    old_api = TplinkDecoApi(
        session=session,
        host=HOST_HTTP,
        username="admin",
        password="password",
        verify_ssl=True,
    )
    assert old_api._use_https is True


@pytest.mark.asyncio
async def test_http_only_success_never_uses_tls() -> None:
    """Keep ordinary API traffic on HTTP if the firmware allows it."""
    api, post = _api(use_https=False)
    post.return_value = _response()
    await api._async_post(
        "List Devices", HOST_HTTP + REQUEST_PATH, params=FORM, data="test"
    )
    assert api._host == HOST_HTTP
    assert post.await_count == 1
    assert post.await_args.kwargs["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect_status", [307, 308, 302])
async def test_http_only_rejects_router_enforced_https_without_retry_or_token(
    redirect_status: int, caplog: pytest.LogCaptureFixture
) -> None:
    """A router requiring HTTPS cannot bypass the HTTP-only setting."""
    api, post = _api(use_https=False)
    first = _response(redirect_status, location=f"https://{HOST}:8443{REQUEST_PATH}")
    post.return_value = first
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(HttpsRequiredException, match="enable Use HTTPS"):
            await api._async_post(
                "List Devices", HOST_HTTP + REQUEST_PATH, params=FORM, data="test"
            )

    assert post.await_count == 1
    assert first.release.call_count == 1
    assert api._host == HOST_HTTP
    assert SECRET not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("host", "location", "status"),
    [
        (HOST_HTTP, "https://other.invalid/admin/device", 307),
        (HOST_HTTP, f"https://{HOST}/different", 307),
        (HOST_HTTP, f"http://{HOST}{REQUEST_PATH}", 307),
        (HOST_HTTP, f"https://{HOST}{REQUEST_PATH}", 302),
        (HOST_HTTP, f"https://user:secret@{HOST}{REQUEST_PATH}", 307),
        (HOST_HTTPS, f"http://{HOST}{REQUEST_PATH}", 307),
        (HOST_HTTP, None, 307),
    ],
)
async def test_unsafe_redirects_are_blocked_without_following(
    host: str, location: str | None, status: int
) -> None:
    """Reject cross-host, wrong method, wrong path and downgrade redirects."""
    api, post = _api(host=host)
    response = _response(status, location=location)
    post.return_value = response

    with pytest.raises(UnsafeRedirectException):
        await api._async_post(
            "List Devices", host + REQUEST_PATH, params=FORM, data="test"
        )

    assert post.await_count == 1
    assert api._host == host
    response.release.assert_called_once()


@pytest.mark.asyncio
async def test_repeated_upgrade_is_rejected_and_response_released() -> None:
    """Never follow more than one redirect or fall back to another endpoint."""
    api, post = _api()
    first = _response(307, location=f"https://{HOST}{REQUEST_PATH}")
    second = _response(307, location=f"https://{HOST}{REQUEST_PATH}")
    post.side_effect = [first, second]
    with pytest.raises(UnsafeRedirectException, match="multiple redirects"):
        await api._async_post(
            "List Devices", HOST_HTTP + REQUEST_PATH, params=FORM, data="test"
        )
    first.release.assert_called_once()
    second.release.assert_called_once()
    assert api._host == HOST_HTTP
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_login_key_exchange_honors_http_only_policy() -> None:
    """Apply the same redirect guard to the unauthenticated key exchange."""
    api, post = _api(use_https=False)
    first = _response(307, location=f"https://{HOST}/cgi-bin/luci/;stok=/login")
    post.return_value = first

    with pytest.raises(HttpsRequiredException):
        await api._async_fetch_keys()

    assert post.await_count == 1
    assert post.await_args.kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_system_log_download_honors_http_only_policy() -> None:
    """Block HTTPS upgrades in the plain system-log export POST too."""
    api, post = _api(use_https=False)
    first = _response(
        307, location=f"https://{HOST}/cgi-bin/luci/;stok={SECRET}/admin/log_export"
    )
    post.return_value = first

    with pytest.raises(HttpsRequiredException):
        await api._async_save_system_log()

    assert post.await_count == 1
    assert post.await_args.kwargs["allow_redirects"] is False
    first.release.assert_called_once()


@pytest.mark.parametrize(
    ("host", "use_https", "error"),
    [
        (HOST_HTTP, False, {}),
        (HOST_HTTPS, True, {}),
        (HOST_HTTP, True, {}),
        (HOST_HTTPS, False, {CONF_HOST: "http_only_requires_http"}),
        ("ftp://192.0.2.1", True, {CONF_HOST: "invalid_host_scheme"}),
        ("http://192.0.2.1/path", True, {CONF_HOST: "invalid_host_scheme"}),
        ("http://user:secret@192.0.2.1", True, {CONF_HOST: "invalid_host_scheme"}),
        ("http://192.0.2.1:bad", True, {CONF_HOST: "invalid_host_scheme"}),
        (HOST_HTTP, "false", {CONF_USE_HTTPS: "invalid_use_https"}),
        (HOST_HTTP, 0, {CONF_USE_HTTPS: "invalid_use_https"}),
    ],
)
def test_host_and_protocol_validation(
    host: str, use_https: object, error: dict[str, str]
) -> None:
    """Reject mismatched protocol settings before network access."""
    assert (
        config_flow._transport_errors({CONF_HOST: host, CONF_USE_HTTPS: use_https})
        == error
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (HttpsRequiredException("private-token"), "https_required"),
        (UnsafeRedirectException("private-token"), "unsafe_redirect"),
    ],
)
async def test_protocol_failures_are_translated_without_leaking_secrets(
    failure: Exception, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Show actionable form codes and never raw redirect or token data."""
    with (
        patch.object(
            config_flow,
            "async_create_and_refresh_coordinators",
            new=AsyncMock(side_effect=failure),
        ),
        caplog.at_level(logging.DEBUG, logger=config_flow.__name__),
    ):
        result = await config_flow._async_test_credentials(
            MagicMock(), {CONF_HOST: HOST_HTTP}
        )
    assert result == {"base": expected}
    assert "private-token" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("http_only_host", "expected_error"),
    [
        (HOST_HTTPS, "http_only_requires_http"),
        ("ftp://example.invalid", "invalid_host_scheme"),
    ],
)
@pytest.mark.parametrize("is_options", [False, True])
async def test_mismatched_transport_is_rejected_before_credentials_or_storage(
    http_only_host: str, expected_error: str, is_options: bool
) -> None:
    """Preserve stored values and avoid API calls for invalid combinations."""
    existing = {
        CONF_HOST: HOST_HTTP,
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "dummy",
        CONF_USE_HTTPS: True,
        CONF_VERIFY_SSL: True,
    }
    entry = SimpleNamespace(entry_id="fixture-entry", data=deepcopy(existing))
    if is_options:
        flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
        flow.handler = entry.entry_id
    else:
        flow = config_flow.TplinkDecoFlowHandler()
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.async_show_form = MagicMock(return_value={"type": "form"})
    user_input = {**existing, CONF_HOST: http_only_host, CONF_USE_HTTPS: False}
    with patch.object(
        config_flow, "_async_test_credentials", new=AsyncMock()
    ) as credential_check:
        if is_options:
            await flow.async_step_init(user_input)
        else:
            await flow.async_step_user(user_input)

    assert flow._errors == {CONF_HOST: expected_error}
    credential_check.assert_not_awaited()
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert entry.data == existing


@pytest.mark.asyncio
async def test_legacy_options_save_preserves_default_and_other_settings() -> None:
    """Store the new default only after a valid options verification."""
    original = {
        CONF_HOST: HOST_HTTP,
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "dummy",
        CONF_VERIFY_SSL: False,
    }
    entry = SimpleNamespace(entry_id="fixture-entry", data=deepcopy(original))
    flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
    flow.handler = entry.entry_id
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    with patch.object(
        config_flow, "_async_test_credentials", new=AsyncMock(return_value={})
    ):
        result = await flow.async_step_init({CONF_USE_HTTPS: False})

    assert result == {"type": "create_entry"}
    candidate = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert candidate[CONF_USE_HTTPS] is False
    assert candidate[CONF_VERIFY_SSL] is False
    assert candidate[CONF_HOST] == HOST_HTTP
    assert entry.data == original
