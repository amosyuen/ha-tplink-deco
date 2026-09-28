"""Tests for resilient client coordinator polling."""

from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.tplink_deco.coordinator import CoordinatorHealth
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.exceptions import TimeoutException


def _coordinator(internal_update=None):
    coordinator = object.__new__(TplinkDecoClientUpdateCoordinator)
    coordinator._deco_update_coordinator = SimpleNamespace(
        paused=False, data=SimpleNamespace(decos={"deco-mac"})
    )
    coordinator.data = {"existing": object()}
    coordinator.has_successful_refresh = True
    coordinator.health = CoordinatorHealth()
    coordinator._transient_client_errors = []
    coordinator._use_global_client_query = False
    coordinator._next_per_node_probe = 0
    coordinator._consider_home_seconds = 300
    if internal_update is not None:
        coordinator._async_update_data_internal = internal_update
    return coordinator


@pytest.mark.asyncio
async def test_per_deco_query_disables_timeout_retries():
    """Per-node queries use the coordinator's bounded retry policy."""
    coordinator = _coordinator(AsyncMock())
    coordinator.api = SimpleNamespace(async_list_clients=AsyncMock(return_value=[]))

    responses, failed_deco_macs = await coordinator._async_list_clients_per_deco(
        ["deco-mac"]
    )

    assert responses == [("deco-mac", [])]
    assert failed_deco_macs == set()
    coordinator.api.async_list_clients.assert_awaited_once_with(
        "deco-mac", timeout_error_retries=0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TimeoutException(),
        aiohttp.ClientResponseError(
            request_info=None, history=(), status=503, message="server error"
        ),
    ],
)
async def test_per_deco_transient_errors_are_recorded(error):
    """Timeouts and server errors mark only the affected Deco as failed."""
    coordinator = _coordinator(AsyncMock())
    coordinator.api = SimpleNamespace(async_list_clients=AsyncMock(side_effect=error))

    responses, failed_deco_macs = await coordinator._async_list_clients_per_deco(
        ["deco-mac"]
    )

    assert responses == []
    assert failed_deco_macs == {"deco-mac"}
    assert coordinator._transient_client_errors == [error]
    if isinstance(error, TimeoutException):
        assert coordinator.health.timeout_count == 1


@pytest.mark.asyncio
async def test_per_deco_client_errors_below_500_propagate():
    """Client errors are not classified as transient polling failures."""
    error = aiohttp.ClientResponseError(
        request_info=None, history=(), status=401, message="client error"
    )
    coordinator = _coordinator(AsyncMock())
    coordinator.api = SimpleNamespace(async_list_clients=AsyncMock(side_effect=error))

    with pytest.raises(aiohttp.ClientResponseError) as raised:
        await coordinator._async_list_clients_per_deco(["deco-mac"])

    assert raised.value is error


@pytest.mark.asyncio
async def test_global_query_disables_timeout_retries():
    """Global fallback queries also disable timeout retries."""
    coordinator = _coordinator(AsyncMock())
    coordinator.api = SimpleNamespace(async_list_clients=AsyncMock(return_value=[]))
    coordinator._deco_update_coordinator.data.master_deco = SimpleNamespace(
        mac="master-mac"
    )

    deco_macs, responses = await coordinator._async_list_clients_global()

    assert deco_macs == ["master-mac"]
    assert responses == [[]]
    coordinator.api.async_list_clients.assert_awaited_once_with(timeout_error_retries=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TimeoutException(),
        aiohttp.ClientResponseError(
            request_info=None, history=(), status=503, message="server error"
        ),
    ],
)
async def test_global_transient_failure_preserves_snapshot_and_fails_refresh(error):
    """Transient global errors retain data and fail the coordinator refresh."""
    previous_data = {"existing": object()}

    async def fail_update():
        raise error

    coordinator = _coordinator(fail_update)
    coordinator.data = previous_data

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.data is previous_data
    assert coordinator.health.consecutive_failures == 1
    assert coordinator.health.last_error == type(error).__name__


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ConfigEntryAuthFailed, RuntimeError])
async def test_auth_and_unexpected_failures_propagate(error):
    """Authentication and programming failures are never hidden as stale data."""

    async def fail_update():
        raise error("failure")

    coordinator = _coordinator(fail_update)

    with pytest.raises(error):
        await coordinator._async_update_data()

    assert coordinator.health.consecutive_failures == 1


@pytest.mark.asyncio
async def test_partial_transient_failure_preserves_failed_nodes_client_state():
    """A failed node keeps its prior client state while other nodes refresh."""
    stale_activity = datetime(2025, 1, 1, tzinfo=timezone.utc)
    failed_node_client = TpLinkDecoClient("failed-client")
    failed_node_client.deco_mac = "failed-deco"
    failed_node_client.online = True
    failed_node_client.last_activity = stale_activity
    refreshed_client = TpLinkDecoClient("refreshed-client")
    refreshed_client.deco_mac = "healthy-deco"
    coordinator = _coordinator()
    coordinator.data = {
        "failed-client": failed_node_client,
        "refreshed-client": refreshed_client,
    }
    coordinator._deco_update_coordinator.data.decos = {
        "healthy-deco": object(),
        "failed-deco": object(),
    }
    coordinator.api = SimpleNamespace(
        async_list_clients=AsyncMock(
            side_effect=[
                [{"mac": "refreshed-client", "online": True}],
                TimeoutException(),
            ]
        )
    )

    result = await coordinator._async_update_data()

    assert result["failed-client"].online is True
    assert result["failed-client"].last_activity is stale_activity
    assert result["refreshed-client"].deco_mac == "healthy-deco"
    assert coordinator.health.consecutive_failures == 1
    assert coordinator.health.last_error == "TimeoutException"
    assert coordinator.health.timeout_count == 1
