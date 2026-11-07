"""Tests for logging out of the Deco when unloading the integration."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco import async_unload_entry
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import PLATFORMS


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


@pytest.mark.asyncio
async def test_async_logout_posts_logout_and_clears_auth(api):
    _authenticate(api)
    api._encode_payload = MagicMock(return_value="encoded")
    api._async_post = AsyncMock()

    await api.async_logout()

    api._async_post.assert_awaited_once_with(
        "Logout",
        "http://192.168.1.1/cgi-bin/luci/;stok=token/admin/system",
        params={"form": "logout"},
        data="encoded",
    )
    api._encode_payload.assert_called_once_with({"operation": "logout"})
    assert api._stok is None
    assert api._cookie is None


@pytest.mark.asyncio
async def test_async_logout_without_session_does_not_call_router(api):
    api._stok = None
    api._cookie = "sysauth=abc"
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


@pytest.mark.asyncio
async def test_unload_entry_logs_out_after_platforms_unload(api):
    events = []
    entry = MagicMock()
    entry.entry_id = "entry"
    deco = MagicMock()
    deco.async_close = AsyncMock()
    deco.async_shutdown = AsyncMock(side_effect=lambda: events.append("deco_shutdown"))
    deco.api.async_logout = AsyncMock(side_effect=lambda: events.append("logout"))
    clients = MagicMock()
    clients.async_close = AsyncMock()
    clients.async_shutdown = AsyncMock(side_effect=lambda: events.append("clients_shutdown"))

    async def unload_platform(_entry, _platform):
        events.append("platform_unload")
        return True

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_CLIENTS_KEY: clients,
            }
        }
    }
    hass.config_entries.async_forward_entry_unload = AsyncMock(
        side_effect=unload_platform
    )

    result = await async_unload_entry(hass, entry)

    assert result is True
    deco.api.async_logout.assert_awaited_once()
    deco.async_shutdown.assert_awaited_once()
    clients.async_shutdown.assert_awaited_once()
    assert events == [
        *(["platform_unload"] * len(PLATFORMS)),
        "deco_shutdown",
        "clients_shutdown",
        "logout",
    ]


@pytest.mark.asyncio
async def test_unload_entry_failed_platform_unload_keeps_session(api):
    entry = MagicMock()
    entry.entry_id = "entry"
    deco = MagicMock()
    deco.async_close = AsyncMock()
    deco.async_shutdown = AsyncMock()
    deco.api.async_logout = AsyncMock()
    clients = MagicMock()
    clients.async_close = AsyncMock()
    clients.async_shutdown = AsyncMock()

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_CLIENTS_KEY: clients,
            }
        }
    }
    hass.config_entries.async_forward_entry_unload = AsyncMock(return_value=False)

    result = await async_unload_entry(hass, entry)

    assert result is False
    deco.api.async_logout.assert_not_awaited()
    deco.async_shutdown.assert_not_awaited()
    clients.async_shutdown.assert_not_awaited()
