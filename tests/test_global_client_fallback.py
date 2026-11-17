"""Regression tests for safe global client-list fallback on Deco HTTP 5xx."""

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.exceptions import TimeoutException

MASTER = "02:00:00:00:50:01"
SATELLITE = "02:00:00:00:50:02"
CLIENT = "02:00:00:00:50:10"
SECRET = "private-cookie-token"


def _server_error(status: int = 502) -> aiohttp.ClientResponseError:
    """Create a real synthetic HTTP error containing sensitive request data."""
    request_info = MagicMock()
    request_info.real_url = f"http://192.0.2.1/cgi-bin/luci/;stok={SECRET}"
    return aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=f"private error {SECRET}",
    )


def _coordinator(
    *,
    two_decos: bool = False,
    master_present: bool = True,
    old_clients: dict[str, TpLinkDecoClient] | None = None,
) -> tuple[TplinkDecoClientUpdateCoordinator, MagicMock]:
    """Build a coordinator with only local mock API calls."""
    master = TpLinkDeco(MASTER)
    decos = {MASTER: master}
    if two_decos:
        decos[SATELLITE] = TpLinkDeco(SATELLITE)
    deco_coordinator = MagicMock()
    deco_coordinator.paused = False
    deco_coordinator.data = TpLinkDecoData(master if master_present else None, decos)
    api = MagicMock(spec=TplinkDecoApi)
    coordinator = TplinkDecoClientUpdateCoordinator(
        hass=MagicMock(),
        api=api,
        config_entry=MagicMock(),
        deco_update_coordinator=deco_coordinator,
        consider_home_seconds=60,
        data=old_clients,
    )
    return coordinator, api


@pytest.mark.asyncio
async def test_502_global_fallback_reports_master_and_preserves_client_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A valid global reply succeeds without creating a sentinel Deco device."""
    old = TpLinkDecoClient(CLIENT)
    old.deco_mac = SATELLITE
    old.online = True
    coordinator, api = _coordinator(two_decos=True, old_clients={CLIENT: old})

    async def _client_list(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Fail one node and return the active mesh from the global endpoint."""
        assert timeout_error_retries == 0
        if deco_mac == MASTER:
            raise _server_error()
        if deco_mac == "default":
            return [{"mac": CLIENT, "name": "Test", "online": True}]
        return []

    api.async_list_clients = AsyncMock(side_effect=_client_list)
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        with caplog.at_level(logging.DEBUG):
            result = await coordinator._async_update_data()

    assert result[CLIENT] is old
    assert old.online is True
    assert old.deco_mac == MASTER
    assert coordinator.client_query_mode == "global"
    assert coordinator.successfully_polled_deco_macs == {MASTER}
    assert coordinator.has_successful_refresh is True
    assert coordinator.health.last_successful_update is not None
    assert coordinator._client_backoff_seconds == 30
    assert [call.args[0] for call in api.async_list_clients.await_args_list] == [
        MASTER,
        SATELLITE,
        "default",
    ]
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_global_success_continues_during_backoff_then_restores_per_node() -> None:
    """Do not hammer broken nodes while the fallback remains available."""
    coordinator, api = _coordinator(two_decos=True)
    phase = "broken"
    called: list[str] = []

    async def _client_list(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Switch from broken nodes to a healthy mesh after cooldown."""
        assert timeout_error_retries == 0
        called.append(deco_mac)
        if phase == "broken" and deco_mac == SATELLITE:
            raise _server_error()
        return [{"mac": CLIENT, "online": True}] if deco_mac == "default" else []

    api.async_list_clients = AsyncMock(side_effect=_client_list)
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        coordinator.data = await coordinator._async_update_data()
    assert coordinator.client_query_mode == "global"
    assert coordinator._client_backoff_seconds == 30
    assert called == [MASTER, SATELLITE, "default"]

    called.clear()
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1005
    ):
        coordinator.data = await coordinator._async_update_data()
    assert called == ["default"]
    assert coordinator._client_backoff_seconds == 30
    assert coordinator.data[CLIENT].deco_mac == MASTER

    phase = "recovered"
    called.clear()
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1031
    ):
        coordinator.data = await coordinator._async_update_data()
    assert called == [MASTER, SATELLITE]
    assert coordinator.client_query_mode == "per_node"
    assert coordinator._client_backoff_seconds == 0
    assert coordinator._client_backoff_until == 0.0


@pytest.mark.asyncio
async def test_global_empty_result_is_valid_and_updates_offline_grace() -> None:
    """An empty global reply is real success, not a missing or failed response."""
    stale = TpLinkDecoClient(CLIENT)
    stale.deco_mac = MASTER
    stale.online = True
    stale.last_activity = datetime.now(timezone.utc) - timedelta(hours=1)
    coordinator, api = _coordinator(old_clients={CLIENT: stale})
    api.async_list_clients = AsyncMock(side_effect=[_server_error(), []])
    result = await coordinator._async_update_data()

    assert result[CLIENT] is stale
    assert stale.online is False
    assert coordinator.client_query_mode == "global"
    assert coordinator.health.last_successful_update is not None
    assert coordinator._client_backoff_seconds == 30


@pytest.mark.asyncio
async def test_global_timeout_preserves_peers_and_records_timeout() -> None:
    """A failed global fallback must preserve valid peer data and health."""
    coordinator, api = _coordinator(two_decos=True)

    async def _client_list(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Simulate a broken master, valid satellite and global timeout."""
        assert timeout_error_retries == 0
        if deco_mac == MASTER:
            raise _server_error()
        if deco_mac == "default":
            raise TimeoutException("private-router-token")
        return [{"mac": CLIENT, "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_client_list)
    result = await coordinator._async_update_data()
    assert result[CLIENT].deco_mac == SATELLITE
    assert coordinator.client_query_mode == "per_node"
    assert coordinator._client_backoff_seconds == 30
    assert coordinator.health.timeout_count == 1
    assert coordinator.health.last_successful_update is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_global_non_5xx_errors_propagate(status: int) -> None:
    """Never turn an authorization or client error into a successful poll."""
    coordinator, api = _coordinator()
    api.async_list_clients = AsyncMock(
        side_effect=[_server_error(), _server_error(status)]
    )
    with pytest.raises(aiohttp.ClientResponseError) as error:
        await coordinator._async_update_data()
    assert error.value.status == status
    assert coordinator.client_query_mode == "per_node"
    assert coordinator.health.consecutive_failures == 1


@pytest.mark.asyncio
async def test_global_response_type_is_validated_before_client_state_changes() -> None:
    """Reject malformed global data without changing cached client state."""
    old = TpLinkDecoClient(CLIENT)
    old.deco_mac = MASTER
    old.online = True
    coordinator, api = _coordinator(old_clients={CLIENT: old})
    api.async_list_clients = AsyncMock(side_effect=[_server_error(), {"bad": SECRET}])

    with pytest.raises(ValueError, match="Invalid global Deco client list"):
        await coordinator._async_update_data()
    assert coordinator.data[CLIENT] is old
    assert old.online is True
    assert coordinator.health.last_error == "ValueError"


@pytest.mark.asyncio
async def test_no_master_avoids_fake_default_node() -> None:
    """Do not assign a global response to an unknown device identity."""
    coordinator, api = _coordinator(master_present=False)
    api.async_list_clients = AsyncMock(side_effect=_server_error())
    assert await coordinator._async_update_data() == {}
    api.async_list_clients.assert_awaited_once()
    assert coordinator.client_query_mode == "per_node"
    assert coordinator._client_backoff_seconds == 30


@pytest.mark.asyncio
async def test_cancellation_during_global_query_is_not_swallowed() -> None:
    """Home Assistant cancellation must stop the fallback immediately."""
    coordinator, api = _coordinator()
    waiting = asyncio.Event()
    started = asyncio.Event()

    async def _client_list(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Block only the global request until the refresh is cancelled."""
        assert timeout_error_retries == 0
        if deco_mac != "default":
            raise _server_error()
        started.set()
        await waiting.wait()
        return []

    api.async_list_clients = AsyncMock(side_effect=_client_list)
    task = asyncio.create_task(coordinator._async_update_data())
    await asyncio.wait_for(started.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)
    assert coordinator.client_query_mode == "per_node"
    assert coordinator.health.last_successful_update is None
