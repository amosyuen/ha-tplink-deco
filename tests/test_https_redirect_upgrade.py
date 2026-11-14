"""Regression tests for same-router HTTP 307 upgrades to HTTPS."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest
from yarl import URL

from custom_components.tplink_deco.api import TplinkDecoApi

ROUTER_HOST = "192.0.2.1"
SESSION_TOKEN = "synthetic-token"
SESSION_COOKIE = "sysauth=deadbeef"


def _api(host: str = f"http://{ROUTER_HOST}") -> tuple[TplinkDecoApi, AsyncMock]:
    """Return a Deco API with a mocked HTTP session and synthetic credentials."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=host,
        username="admin",
        password="not-a-real-password",
        verify_ssl=True,
    )
    api._stok = SESSION_TOKEN
    api._cookie = SESSION_COOKIE
    api._seq = 7
    return api, session.post


def _response(
    final_url: str,
    *,
    initial_url: str | None = None,
    redirect_status: int = 307,
) -> MagicMock:
    """Mock an aiohttp response and its optional redirect history."""
    response = MagicMock()
    response.url = URL(final_url)
    response.history = (
        (SimpleNamespace(status=redirect_status, url=URL(initial_url)),)
        if initial_url is not None
        else ()
    )
    response.headers.getall.return_value = []
    response.raise_for_status = MagicMock()
    response.json = AsyncMock(return_value={"data": "synthetic-payload"})
    return response


@pytest.mark.asyncio
async def test_same_host_307_upgrades_api_host_and_keeps_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Upgrade the host after a trusted redirect without exposing auth data."""
    api, post = _api()
    original_url = (
        f"http://{ROUTER_HOST}/cgi-bin/luci/;stok={SESSION_TOKEN}/admin/device"
    )
    redirected_url = original_url.replace("http://", "https://", 1)
    post.return_value = _response(redirected_url, initial_url=original_url)

    with caplog.at_level(logging.DEBUG):
        result = await api._async_post(
            "List Devices", original_url, params={"form": "device_list"}, data="x"
        )

    assert result == {"data": "synthetic-payload"}
    assert api._host == f"https://{ROUTER_HOST}"
    assert api._stok == SESSION_TOKEN
    assert api._cookie == SESSION_COOKIE
    assert api._seq == 7
    assert post.await_args.kwargs["cookies"] == {"sysauth": "deadbeef"}
    assert SESSION_TOKEN not in caplog.text
    assert SESSION_COOKIE not in caplog.text


@pytest.mark.asyncio
async def test_upgraded_host_uses_redirect_port_on_next_authenticated_poll() -> None:
    """Skip subsequent HTTP redirects while retaining the existing cookie."""
    api, post = _api(f"http://{ROUTER_HOST}:8080")
    initial_url = f"http://{ROUTER_HOST}:8080/cgi-bin/luci/;stok=/login"
    redirected_url = f"https://{ROUTER_HOST}:8443/cgi-bin/luci/;stok=/login"
    post.side_effect = [
        _response(redirected_url, initial_url=initial_url),
        _response(f"https://{ROUTER_HOST}:8443/admin/device"),
    ]
    api._encode_payload = MagicMock(return_value="synthetic-request")
    api._decrypt_data = MagicMock(return_value={"result": {"device_list": []}})
    api.async_login = AsyncMock()

    await api._async_post("Fetch Keys", initial_url, params={}, data="x")

    assert api._host == f"https://{ROUTER_HOST}:8443"
    assert await api.async_list_devices() == []
    assert post.await_count == 2
    assert post.await_args_list[0].args[0] == initial_url
    next_request_url = post.await_args_list[1].args[0]
    assert next_request_url.startswith(f"https://{ROUTER_HOST}:8443/cgi-bin/luci/")
    assert post.await_args_list[1].kwargs["cookies"] == {"sysauth": "deadbeef"}
    api.async_login.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured_host", "initial_host", "final_host", "status"),
    [
        (f"http://{ROUTER_HOST}", ROUTER_HOST, "other.example", 307),
        (f"http://{ROUTER_HOST}", ROUTER_HOST, ROUTER_HOST, 302),
        (f"http://{ROUTER_HOST}", "other.example", ROUTER_HOST, 307),
        (f"https://{ROUTER_HOST}", ROUTER_HOST, ROUTER_HOST, 307),
        (f"http://{ROUTER_HOST}", ROUTER_HOST, "other.example", 301),
    ],
)
async def test_untrusted_or_inapplicable_redirect_does_not_change_host(
    configured_host: str,
    initial_host: str,
    final_host: str,
    status: int,
) -> None:
    """Reject cross-host, unrelated-status and already-HTTPS redirects."""
    api, post = _api(configured_host)
    initial_url = f"http://{initial_host}/admin/device"
    final_url = f"https://{final_host}/admin/device"
    post.return_value = _response(
        final_url, initial_url=initial_url, redirect_status=status
    )

    await api._async_post("List Devices", initial_url, params={}, data="x")

    assert api._host == configured_host
    assert api._cookie == SESSION_COOKIE


@pytest.mark.asyncio
async def test_direct_response_without_redirect_preserves_configured_host() -> None:
    """Leave existing HTTP installations unchanged when no 307 occurred."""
    api, post = _api()
    post.return_value = _response(f"http://{ROUTER_HOST}/admin/device")

    await api._async_post(
        "List Devices", f"http://{ROUTER_HOST}/admin/device", params={}, data="x"
    )

    assert api._host == f"http://{ROUTER_HOST}"
    assert api._stok == SESSION_TOKEN
