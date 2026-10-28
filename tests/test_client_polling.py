"""Tests for client polling, error backoff, and recovery."""

from datetime import datetime
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.tplink_deco.coordinator import CLIENT_BACKOFF_INITIAL_SECONDS
from custom_components.tplink_deco.coordinator import CLIENT_BACKOFF_MAX_SECONDS
from custom_components.tplink_deco.coordinator import CoordinatorHealth
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from homeassistant.util import dt as dt_util


def _client_response_error(
    status: int = 500,
    message: str = "Internal Server Error",
    url: str = "https://192.168.0.1/cgi-bin/luci/;stok=SECRET_STOK_99999/admin/client?form=client_list",
):
    request_info = MagicMock()
    request_info.real_url = url
    request_info.url = url
    return aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=message,
    )


def _client_coordinator() -> TplinkDecoClientUpdateCoordinator:
    coordinator = object.__new__(TplinkDecoClientUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.clear_auth = MagicMock()
    deco_coord = MagicMock()
    deco_coord.paused = False
    deco_coord.data.decos = {"DE:CO:01:00:00:01": MagicMock()}
    deco_coord.data.master_deco = MagicMock(mac="DE:CO:01:00:00:01")
    coordinator._deco_update_coordinator = deco_coord
    coordinator._consider_home_seconds = 180

    initial_client = TpLinkDecoClient("AA:BB:CC:DD:EE:01")
    initial_client.online = True
    initial_client.deco_mac = "DE:CO:01:00:00:01"
    initial_client.last_activity = dt_util.utcnow()

    coordinator.data = {"AA:BB:CC:DD:EE:01": initial_client}
    coordinator._use_global_client_query = False
    coordinator._next_per_node_probe = 0.0
    coordinator._client_backoff_until = 0.0
    coordinator._client_backoff_seconds = 0.0
    coordinator._last_logged_500_error = None
    coordinator.health = CoordinatorHealth()
    coordinator.hass = MagicMock()
    return coordinator


@pytest.mark.asyncio
async def test_client_500_triggers_backoff_and_preserves_client_state():
    """Test that HTTP 500 response initiates backoff and preserves client states."""
    coordinator = _client_coordinator()
    err_500 = _client_response_error(500)
    coordinator.api.async_list_clients = AsyncMock(side_effect=err_500)

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000.0
    ):
        data = await coordinator._async_update_data_internal()

    # Preserves existing client state and returns data
    assert "AA:BB:CC:DD:EE:01" in data
    assert data["AA:BB:CC:DD:EE:01"].online is True

    # Applied initial backoff
    assert coordinator._client_backoff_seconds == float(CLIENT_BACKOFF_INITIAL_SECONDS)
    assert coordinator._client_backoff_until == 1000.0 + float(
        CLIENT_BACKOFF_INITIAL_SECONDS
    )

    # Auth session was NOT cleared
    coordinator.api.clear_auth.assert_not_called()


@pytest.mark.asyncio
async def test_client_polling_skipped_during_backoff():
    """Test that client polling queries are skipped while backoff window is active."""
    coordinator = _client_coordinator()
    coordinator._client_backoff_until = 1100.0
    coordinator._client_backoff_seconds = 30.0
    coordinator.api.async_list_clients = AsyncMock()

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1050.0
    ):
        data = await coordinator._async_update_data_internal()

    # Polling query was skipped entirely
    coordinator.api.async_list_clients.assert_not_called()
    assert "AA:BB:CC:DD:EE:01" in data
    assert data["AA:BB:CC:DD:EE:01"].online is True


@pytest.mark.asyncio
async def test_repeated_500_doubles_backoff_capped():
    """Test that repeated HTTP 500 errors double backoff duration up to cap."""
    coordinator = _client_coordinator()
    err_500 = _client_response_error(500)
    coordinator.api.async_list_clients = AsyncMock(side_effect=err_500)

    # First 500 error at t=1000
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000.0
    ):
        await coordinator._async_update_data_internal()
    assert coordinator._client_backoff_seconds == 30.0
    assert coordinator._client_backoff_until == 1030.0

    # Second 500 error after backoff expires at t=1031
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1031.0
    ):
        await coordinator._async_update_data_internal()
    assert coordinator._client_backoff_seconds == 60.0
    assert coordinator._client_backoff_until == 1031.0 + 60.0

    # Third 500 error after backoff expires at t=1100
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1100.0
    ):
        await coordinator._async_update_data_internal()
    assert coordinator._client_backoff_seconds == 120.0

    # Fourth 500 error after backoff expires at t=1230
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1230.0
    ):
        await coordinator._async_update_data_internal()
    assert coordinator._client_backoff_seconds == 240.0

    # Fifth 500 error caps at CLIENT_BACKOFF_MAX_SECONDS (300)
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1500.0
    ):
        await coordinator._async_update_data_internal()
    assert coordinator._client_backoff_seconds == float(CLIENT_BACKOFF_MAX_SECONDS)


@pytest.mark.asyncio
async def test_recovery_resets_backoff():
    """Test that a successful client query resets backoff state."""
    coordinator = _client_coordinator()
    coordinator._client_backoff_seconds = 120.0
    coordinator._client_backoff_until = 1000.0
    coordinator._last_logged_500_error = "500 Internal Server Error"

    success_clients = [
        {
            "mac": "AA:BB:CC:DD:EE:01",
            "name": "Test Client",
            "ip": "192.168.0.50",
            "online": True,
        }
    ]
    coordinator.api.async_list_clients = AsyncMock(return_value=success_clients)

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1001.0
    ):
        data = await coordinator._async_update_data_internal()

    # Backoff reset to 0
    assert coordinator._client_backoff_seconds == 0.0
    assert coordinator._client_backoff_until == 0.0
    assert coordinator._last_logged_500_error is None

    # Client data successfully updated
    assert "AA:BB:CC:DD:EE:01" in data
    assert data["AA:BB:CC:DD:EE:01"].online is True


@pytest.mark.asyncio
async def test_client_500_sanitized_logging(caplog):
    """Test that HTTP 500 error logs sanitize out URL and sensitive tokens."""
    coordinator = _client_coordinator()
    err_500 = _client_response_error(
        500,
        message="Internal Server Error",
        url="https://192.168.0.1/cgi-bin/luci/;stok=SECRET_STOK_99999/admin/client?form=client_list",
    )
    coordinator.api.async_list_clients = AsyncMock(side_effect=err_500)

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000.0
    ):
        await coordinator._async_update_data_internal()

    # Verify secret token is NOT leaked in log records
    assert "SECRET_STOK_99999" not in caplog.text
    assert ";stok=" not in caplog.text
    # Verify sanitized status and message are present
    assert "HTTP 500 (Internal Server Error)" in caplog.text


@pytest.mark.asyncio
async def test_coordinator_health_during_backoff():
    """Test that coordinator health tracks degraded state and does not mark success."""
    coordinator = _client_coordinator()
    initial_update_time = datetime(2026, 10, 28, 9, 0, 0)
    coordinator.health.last_successful_update = initial_update_time

    err_500 = _client_response_error(500)
    coordinator.api.async_list_clients = AsyncMock(side_effect=err_500)

    # Initial failure triggers backoff
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000.0
    ):
        await coordinator._async_update_data()
        assert coordinator.is_backed_off is True
        assert coordinator.remaining_backoff_seconds == 30
        # Health should NOT record success; last_successful_update must remain untouched
        assert coordinator.health.last_successful_update == initial_update_time
        assert coordinator.health.consecutive_failures == 1
        assert coordinator.health.last_error == "ClientResponseError"

    # Subsequent update while backoff is active (t=1010)
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1010.0
    ):
        await coordinator._async_update_data()
        assert coordinator.is_backed_off is True
        assert coordinator.remaining_backoff_seconds == 20
        assert coordinator.health.last_successful_update == initial_update_time
        assert coordinator.health.consecutive_failures == 2


@pytest.mark.asyncio
async def test_partial_per_node_success_preserves_failed_node_and_avoids_backoff():
    """Test that partial per-node failure preserves offline state and does not trigger backoff."""
    coordinator = _client_coordinator()
    # Configure 2 deco nodes
    coordinator._deco_update_coordinator.data.decos = {
        "DE:CO:01:00:00:01": MagicMock(),
        "DE:CO:02:00:00:02": MagicMock(),
    }
    client_node_1 = TpLinkDecoClient("AA:BB:CC:DD:EE:01")
    client_node_1.online = True
    client_node_1.deco_mac = "DE:CO:01:00:00:01"
    client_node_1.last_activity = dt_util.utcnow()
    coordinator.data = {"AA:BB:CC:DD:EE:01": client_node_1}

    async def list_clients(mac=None, timeout_error_retries=None):
        if mac == "DE:CO:01:00:00:01":
            raise _client_response_error(500)
        return [
            {
                "mac": "AA:BB:CC:DD:EE:02",
                "name": "Node 2 Client",
                "ip": "192.168.0.52",
                "online": True,
            }
        ]

    coordinator.api.async_list_clients = AsyncMock(side_effect=list_clients)

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000.0
    ):
        data = await coordinator._async_update_data_internal()

    # Node 1 client is preserved (not marked offline)
    assert "AA:BB:CC:DD:EE:01" in data
    assert data["AA:BB:CC:DD:EE:01"].online is True
    # Node 2 client is updated
    assert "AA:BB:CC:DD:EE:02" in data
    assert data["AA:BB:CC:DD:EE:02"].online is True

    # Backoff is NOT triggered because partial data was successfully obtained
    assert coordinator.is_backed_off is False
    assert coordinator._client_backoff_seconds == 0.0
