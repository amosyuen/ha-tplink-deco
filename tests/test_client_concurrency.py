"""Regression tests for bounded multi-node Deco client-list polling."""

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.coordinator import MAX_CONCURRENT_CLIENT_REQUESTS
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.exceptions import TimeoutException

MASTER = "02:00:00:00:40:01"
SATELLITE = "02:00:00:00:40:02"
CLIENT = "02:00:00:00:40:10"


def _client_coordinator(
    node_count: int = 2,
    old_clients: dict[str, TpLinkDecoClient] | None = None,
) -> tuple[TplinkDecoClientUpdateCoordinator, MagicMock]:
    """Create isolated real coordinator instances without a live router."""
    api = MagicMock(spec=TplinkDecoApi)
    macs = [f"02:00:00:00:40:{index:02x}" for index in range(1, node_count + 1)]
    decos = {mac: TpLinkDeco(mac) for mac in macs}
    master = decos[macs[0]]
    deco_coordinator = MagicMock()
    deco_coordinator.paused = False
    deco_coordinator.data = TpLinkDecoData(master, decos)
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
async def test_node_requests_never_exceed_two_concurrent_queries() -> None:
    """Poll five nodes with at most two in flight and no timeout retries."""
    coordinator, api = _client_coordinator(node_count=5)
    started = asyncio.Event()
    unblock = asyncio.Event()
    active = 0
    maximum = 0
    attempted: list[str] = []

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Hold a request open so concurrency can be measured deterministically."""
        nonlocal active, maximum
        assert timeout_error_retries == 0
        active += 1
        maximum = max(maximum, active)
        attempted.append(deco_mac)
        if active == MAX_CONCURRENT_CLIENT_REQUESTS:
            started.set()
        try:
            await unblock.wait()
            return []
        finally:
            active -= 1

    api.async_list_clients = AsyncMock(side_effect=_clients)
    task = asyncio.create_task(coordinator._async_update_data())
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        assert len(attempted) == MAX_CONCURRENT_CLIENT_REQUESTS
        assert active == MAX_CONCURRENT_CLIENT_REQUESTS
    finally:
        unblock.set()

    assert await asyncio.wait_for(task, timeout=3) == {}
    assert active == 0
    assert len(attempted) == 5
    assert maximum == MAX_CONCURRENT_CLIENT_REQUESTS
    assert api.async_list_clients.await_count == 5
    assert coordinator.health.consecutive_failures == 0
    assert coordinator.client_query_mode == "per_node"


@pytest.mark.asyncio
async def test_unexpected_node_error_cancels_other_pending_requests() -> None:
    """Cancel and await remaining node calls if one poll fails unexpectedly."""
    coordinator, api = _client_coordinator(node_count=4)
    two_started = asyncio.Event()
    never_finish = asyncio.Event()
    active: set[str] = set()
    ended: set[str] = set()
    cancelled: set[str] = set()

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Wait for both slots before triggering one failure."""
        assert timeout_error_retries == 0
        active.add(deco_mac)
        if len(active) == MAX_CONCURRENT_CLIENT_REQUESTS:
            two_started.set()
        try:
            if deco_mac == MASTER:
                await two_started.wait()
                raise ValueError("malformed response")
            await never_finish.wait()
            return []
        except asyncio.CancelledError:
            cancelled.add(deco_mac)
            raise
        finally:
            ended.add(deco_mac)
            active.discard(deco_mac)

    api.async_list_clients = AsyncMock(side_effect=_clients)
    with pytest.raises(ValueError, match="malformed response"):
        await asyncio.wait_for(coordinator._async_update_data(), timeout=3)

    assert active == set()
    assert {MASTER, SATELLITE}.issubset(ended)
    assert SATELLITE in cancelled
    assert ended == {call.args[0] for call in api.async_list_clients.await_args_list}
    # A semaphore waiter may briefly start after the first slot releases.
    assert coordinator.health.last_error == "ValueError"
    assert coordinator.health.consecutive_failures == 1


@pytest.mark.asyncio
async def test_cancelling_refresh_cleans_up_all_node_queries() -> None:
    """Stop outstanding calls cleanly when Home Assistant cancels a refresh."""
    coordinator, api = _client_coordinator(node_count=4)
    two_started = asyncio.Event()
    blocked = asyncio.Event()
    in_flight: set[str] = set()

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Remain pending until cancelled by the parent refresh."""
        assert timeout_error_retries == 0
        in_flight.add(deco_mac)
        if len(in_flight) == MAX_CONCURRENT_CLIENT_REQUESTS:
            two_started.set()
        try:
            await blocked.wait()
            return []
        finally:
            in_flight.discard(deco_mac)

    api.async_list_clients = AsyncMock(side_effect=_clients)
    task = asyncio.create_task(coordinator._async_update_data())
    await asyncio.wait_for(two_started.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)
    assert in_flight == set()
    assert api.async_list_clients.await_count == MAX_CONCURRENT_CLIENT_REQUESTS


@pytest.mark.asyncio
async def test_timed_out_peer_keeps_cached_clients_and_updates_healthy_peer() -> None:
    """Treat timeout as incomplete, not as an empty list or a 5xx response."""
    old_client = TpLinkDecoClient(CLIENT)
    old_client.deco_mac = MASTER
    old_client.online = True
    old_client.last_activity = datetime.now(timezone.utc) - timedelta(hours=1)
    coordinator, api = _client_coordinator(old_clients={CLIENT: old_client})
    peer_client = "02:00:00:00:40:20"

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Raise a timeout on the master and return data from the satellite."""
        assert timeout_error_retries == 0
        if deco_mac == MASTER:
            raise TimeoutException("hidden-router-token")
        return [{"mac": peer_client, "name": "peer", "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_clients)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        result = await coordinator._async_update_data()

    assert result[CLIENT] is old_client
    assert result[CLIENT].online is True
    assert result[CLIENT].deco_mac == MASTER
    assert result[peer_client].deco_mac == SATELLITE
    assert result[peer_client].online is True
    assert coordinator._client_backoff_seconds == 0
    assert coordinator.health.consecutive_failures == 0


@pytest.mark.asyncio
async def test_real_api_override_prevents_per_node_timeout_retries() -> None:
    """Override retry budget without changing normal API timeout behavior."""
    api = TplinkDecoApi(
        session=MagicMock(spec=aiohttp.ClientSession),
        host="http://192.0.2.10",
        username="fixture",
        password="not-a-real-password",
        verify_ssl=True,
        timeout_error_retries=2,
    )
    api._async_list_clients = AsyncMock(side_effect=[TimeoutException("private"), []])
    with pytest.raises(TimeoutException):
        await api.async_list_clients(MASTER, timeout_error_retries=0)
    assert api._async_list_clients.await_count == 1

    api._async_list_clients.reset_mock()
    api._async_list_clients.side_effect = [TimeoutException("private"), []]
    assert await api.async_list_clients(MASTER) == []
    assert api._async_list_clients.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [-1, True, False, 1.5, "2"])
async def test_api_rejects_invalid_timeout_retry_overrides(invalid: object) -> None:
    """Reject invalid per-request retry values before contacting the router."""
    api = TplinkDecoApi(
        session=MagicMock(spec=aiohttp.ClientSession),
        host="http://192.0.2.10",
        username="fixture",
        password="not-a-real-password",
        verify_ssl=True,
    )
    api._async_list_clients = AsyncMock(return_value=[])
    with pytest.raises(ValueError, match="non-negative integer"):
        await api.async_list_clients(MASTER, timeout_error_retries=invalid)
    api._async_list_clients.assert_not_awaited()
