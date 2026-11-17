"""Regressions for safe TP-Link Deco config-entry teardown and logout."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.tplink_deco import async_unload_entry
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import PLATFORMS
from custom_components.tplink_deco.const import SERVICE_PAUSE_POLLING
from custom_components.tplink_deco.const import SERVICE_RESUME_POLLING

TEST_HOST = "http://192.0.2.1"
TEST_TOKEN = "fake-stok-secret"
TEST_COOKIE = "sysauth=deadbeef"


def _api() -> TplinkDecoApi:
    """Create a Deco API with synthetic authentication and no live network."""
    api = TplinkDecoApi(
        session=MagicMock(spec=aiohttp.ClientSession),
        host=TEST_HOST,
        username="test-user",
        password="not-a-real-password",
        verify_ssl=True,
    )
    api._stok = TEST_TOKEN
    api._cookie = TEST_COOKIE
    api._seq = 15
    api._encode_payload = MagicMock(return_value="encoded-request")
    api._async_post = AsyncMock(return_value={"error_code": 0})
    return api


def _mock_coordinator(name: str, events: list[str]) -> MagicMock:
    """Create a coordinator that records shutdown and callback cleanup order."""
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock(
        side_effect=lambda: events.append(f"{name}_shutdown")
    )
    coordinator.async_close = AsyncMock(
        side_effect=lambda: events.append(f"{name}_close")
    )
    return coordinator


def _unload_context(
    events: list[str],
) -> tuple[MagicMock, SimpleNamespace, MagicMock, MagicMock]:
    """Set up a config entry with both existing coordinator types."""
    entry = SimpleNamespace(entry_id="test-entry")
    deco = _mock_coordinator("deco", events)
    client = _mock_coordinator("clients", events)
    deco.api.async_logout = AsyncMock(side_effect=lambda: events.append("logout"))
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_CLIENTS_KEY: client,
            }
        }
    }

    async def _platform_unload(_entry: SimpleNamespace, _platform: str) -> bool:
        """Record platform unloads before coordinator and session cleanup."""
        events.append("platform_unload")
        return True

    hass.config_entries.async_forward_entry_unload = AsyncMock(
        side_effect=_platform_unload
    )
    return hass, entry, deco, client


@pytest.mark.asyncio
async def test_successful_unload_stops_polling_before_callbacks_and_logout() -> None:
    """Unload platforms before stopping coordinators and logging out."""
    events: list[str] = []
    hass, entry, deco, client = _unload_context(events)

    assert await async_unload_entry(hass, entry) is True
    assert events == [
        *(["platform_unload"] * len(PLATFORMS)),
        "deco_shutdown",
        "clients_shutdown",
        "deco_close",
        "clients_close",
        "logout",
    ]
    assert entry.entry_id not in hass.data[DOMAIN]
    deco.async_shutdown.assert_awaited_once()
    client.async_shutdown.assert_awaited_once()
    deco.async_close.assert_awaited_once()
    client.async_close.assert_awaited_once()
    deco.api.async_logout.assert_awaited_once()
    hass.services.async_remove.assert_any_call(DOMAIN, SERVICE_PAUSE_POLLING)
    hass.services.async_remove.assert_any_call(DOMAIN, SERVICE_RESUME_POLLING)


@pytest.mark.asyncio
async def test_wireless_unload_requires_shutdown_but_not_custom_close() -> None:
    """Shutdown all coordinators while closing only fork-specific ones."""
    events: list[str] = []
    hass, entry, deco, client = _unload_context(events)
    wireless = SimpleNamespace(
        async_shutdown=AsyncMock(
            side_effect=lambda: events.append("wireless_shutdown")
        )
    )
    hass.data[DOMAIN][entry.entry_id][COORDINATOR_WIRELESS_KEY] = wireless

    assert await async_unload_entry(hass, entry) is True

    assert events == [
        *(["platform_unload"] * len(PLATFORMS)),
        "deco_shutdown",
        "clients_shutdown",
        "wireless_shutdown",
        "deco_close",
        "clients_close",
        "logout",
    ]
    wireless.async_shutdown.assert_awaited_once()
    deco.async_close.assert_awaited_once()
    client.async_close.assert_awaited_once()
    deco.api.async_logout.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_failed_platform_unload_preserves_polling_callbacks_and_login() -> None:
    """Keep the entry and router session intact when a platform cannot unload."""
    events: list[str] = []
    hass, entry, deco, client = _unload_context(events)
    hass.config_entries.async_forward_entry_unload = AsyncMock(return_value=False)
    entry_data = hass.data[DOMAIN][entry.entry_id]

    assert await async_unload_entry(hass, entry) is False
    assert hass.data[DOMAIN][entry.entry_id] is entry_data
    for coordinator in (deco, client):
        coordinator.async_shutdown.assert_not_awaited()
        coordinator.async_close.assert_not_awaited()
    deco.api.async_logout.assert_not_awaited()
    hass.services.async_remove.assert_not_called()


@pytest.mark.asyncio
async def test_platform_unload_exception_does_not_cleanup_runtime() -> None:
    """Propagate unload exceptions before touching coordinator or auth state."""
    events: list[str] = []
    hass, entry, deco, client = _unload_context(events)
    hass.config_entries.async_forward_entry_unload = AsyncMock(
        side_effect=RuntimeError("platform unload failed")
    )

    with pytest.raises(RuntimeError, match="platform unload failed"):
        await async_unload_entry(hass, entry)

    assert entry.entry_id in hass.data[DOMAIN]
    for coordinator in (deco, client):
        coordinator.async_shutdown.assert_not_awaited()
        coordinator.async_close.assert_not_awaited()
    deco.api.async_logout.assert_not_awaited()


@pytest.mark.asyncio
async def test_unload_without_registered_entry_is_idempotent() -> None:
    """Return success without touching services or platforms for an absent entry."""
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    entry = SimpleNamespace(entry_id="missing-entry")

    assert await async_unload_entry(hass, entry) is True
    hass.config_entries.async_forward_entry_unload.assert_not_called()
    hass.services.async_remove.assert_not_called()


@pytest.mark.asyncio
async def test_unload_without_coordinators_succeeds() -> None:
    """Tolerate missing coordinator values during an otherwise valid unload."""
    events: list[str] = []
    hass, entry, _, _ = _unload_context(events)
    hass.data[DOMAIN][entry.entry_id] = {}

    assert await async_unload_entry(hass, entry) is True
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_unload_leaves_other_config_entry_runtime_intact() -> None:
    """Remove only the selected config entry's coordinator data."""
    events: list[str] = []
    hass, entry, _, _ = _unload_context(events)
    other_entry_data = {COORDINATOR_DECOS_KEY: MagicMock()}
    hass.data[DOMAIN]["other-entry"] = other_entry_data

    assert await async_unload_entry(hass, entry) is True
    assert hass.data[DOMAIN]["other-entry"] is other_entry_data


@pytest.mark.asyncio
async def test_logout_posts_request_and_clears_local_session() -> None:
    """Send logout to the existing endpoint and invalidate all session data."""
    api = _api()
    await api.async_logout()

    api._encode_payload.assert_called_once_with({"operation": "logout"})
    api._async_post.assert_awaited_once_with(
        "Logout",
        f"{TEST_HOST}/cgi-bin/luci/;stok={TEST_TOKEN}/admin/system",
        params={"form": "logout"},
        data="encoded-request",
    )
    assert (api._stok, api._cookie, api._seq) == (None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_field", ["_stok", "_cookie"])
async def test_logout_without_complete_auth_does_not_call_router(
    missing_field: str,
) -> None:
    """Avoid a logout request when authentication has never completed."""
    api = _api()
    setattr(api, missing_field, None)

    await api.async_logout()

    api._async_post.assert_not_awaited()
    assert (api._stok, api._cookie, api._seq) == (None, None, None)


@pytest.mark.asyncio
async def test_logout_failure_still_clears_auth_without_leaking_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rejected logout must not block unload or expose upstream error text."""
    api = _api()
    api._async_post.side_effect = aiohttp.ClientError(
        f"error containing {TEST_TOKEN} and {TEST_COOKIE}"
    )

    with caplog.at_level(logging.DEBUG):
        await api.async_logout()

    assert (api._stok, api._cookie, api._seq) == (None, None, None)
    assert TEST_TOKEN not in caplog.text
    assert TEST_COOKIE not in caplog.text
    assert "ClientError" in caplog.text


@pytest.mark.asyncio
async def test_logout_cancellation_is_not_swallowed() -> None:
    """Propagate cancellation while clearing the locally held session."""
    api = _api()
    api._async_post.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await api.async_logout()

    assert (api._stok, api._cookie, api._seq) == (None, None, None)
