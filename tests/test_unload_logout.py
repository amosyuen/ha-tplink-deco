"""Tests for releasing a Deco session during config-entry unload."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco import async_unload_entry
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import COORDINATOR_MOBILE_KEY
from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import PLATFORMS


@pytest.fixture
def api():
    return TplinkDecoApi(
        session=MagicMock(spec=aiohttp.ClientSession),
        host="http://192.168.1.1",
        username="admin",
        password="password",
        verify_ssl=False,
    )


def _authenticate(api, *, legacy: bool = False):
    api._stok = "" if legacy else "token"
    api._cookie = "outer=1" if legacy else "sysauth=abc"
    api._seq = 0 if legacy else 1
    api._outer_id = "outer-session" if legacy else None


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_async_logout_posts_logout_and_clears_auth(api, legacy):
    _authenticate(api, legacy=legacy)
    api._encode_payload = MagicMock(return_value="encoded")
    api._async_post = AsyncMock()

    await api.async_logout()

    expected_stok = "" if legacy else "token"
    api._async_post.assert_awaited_once_with(
        "Logout",
        f"http://192.168.1.1/cgi-bin/luci/;stok={expected_stok}/admin/system",
        params={"form": "logout"},
        data="encoded",
    )
    assert api._stok is None
    assert api._cookie is None
    assert api._outer_id is None


@pytest.mark.asyncio
async def test_async_logout_without_session_does_not_call_router(api):
    api._async_post = AsyncMock()

    await api.async_logout()

    api._async_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_logout_failure_still_clears_auth(api):
    _authenticate(api)
    api._encode_payload = MagicMock(return_value="encoded")
    api._async_post = AsyncMock(side_effect=aiohttp.ClientError())

    await api.async_logout()

    assert api._stok is None
    assert api._cookie is None


def _coordinator(name: str, events: list[str], *, close: bool = False):
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock(
        side_effect=lambda: events.append(f"{name}_shutdown")
    )
    if close:
        coordinator.async_close = AsyncMock(
            side_effect=lambda: events.append(f"{name}_close")
        )
    return coordinator


@pytest.mark.asyncio
async def test_unload_cleans_up_after_platforms_unload():
    events = []
    entry = SimpleNamespace(entry_id="entry")
    deco = _coordinator("deco", events, close=True)
    clients = _coordinator("clients", events, close=True)
    mobile = _coordinator("mobile", events)
    wireless = _coordinator("wireless", events)
    deco.api.async_logout = AsyncMock(side_effect=lambda: events.append("logout"))

    async def unload_platform(_entry, _platform):
        events.append("platform_unload")
        return True

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_CLIENTS_KEY: clients,
                COORDINATOR_MOBILE_KEY: mobile,
                COORDINATOR_WIRELESS_KEY: wireless,
            }
        }
    }
    hass.config_entries.async_forward_entry_unload = AsyncMock(
        side_effect=unload_platform
    )

    assert await async_unload_entry(hass, entry) is True
    assert events == [
        *(["platform_unload"] * len(PLATFORMS)),
        "deco_shutdown",
        "clients_shutdown",
        "mobile_shutdown",
        "wireless_shutdown",
        "deco_close",
        "clients_close",
        "logout",
    ]
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_failed_platform_unload_keeps_runtime_and_session():
    entry = SimpleNamespace(entry_id="entry")
    coordinators = [
        _coordinator(name, []) for name in ("deco", "clients", "mobile", "wireless")
    ]
    deco, clients, mobile, wireless = coordinators
    deco.async_close = AsyncMock()
    clients.async_close = AsyncMock()
    deco.api.async_logout = AsyncMock()

    entry_data = {
        COORDINATOR_DECOS_KEY: deco,
        COORDINATOR_CLIENTS_KEY: clients,
        COORDINATOR_MOBILE_KEY: mobile,
        COORDINATOR_WIRELESS_KEY: wireless,
    }
    hass = MagicMock()
    hass.data = {DOMAIN: {entry.entry_id: entry_data}}
    hass.config_entries.async_forward_entry_unload = AsyncMock(return_value=False)

    assert await async_unload_entry(hass, entry) is False
    assert hass.data[DOMAIN][entry.entry_id] is entry_data
    for coordinator in coordinators:
        coordinator.async_shutdown.assert_not_awaited()
    deco.async_close.assert_not_awaited()
    clients.async_close.assert_not_awaited()
    deco.api.async_logout.assert_not_awaited()
    hass.services.async_remove.assert_not_called()
