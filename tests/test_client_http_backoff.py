"""Regression tests for capped HTTP 5xx client-list polling backoff."""

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
from custom_components.tplink_deco.coordinator import CLIENT_BACKOFF_INITIAL_SECONDS
from custom_components.tplink_deco.coordinator import CLIENT_BACKOFF_MAX_SECONDS
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.exceptions import TransientConnectionException

MASTER_MAC = "00:00:00:00:00:01"
SATELLITE_MAC = "00:00:00:00:00:02"
MASTER_CLIENT = "00:00:00:00:00:11"
SATELLITE_CLIENT = "00:00:00:00:00:12"
NEW_CLIENT = "00:00:00:00:00:13"
STOK = "secret-stok-for-backoff"
COOKIE = "sysauth=private-cookie"


def _response_error(status: int = 500) -> aiohttp.ClientResponseError:
    """Create a real HTTP error containing a sensitive LuCI request URL."""
    request_info = MagicMock()
    request_info.real_url = f"http://192.0.2.1/cgi-bin/luci/;stok={STOK}/admin/client"
    return aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=f"Router error containing {COOKIE}",
    )


def _old_client(mac: str, deco_mac: str) -> TpLinkDecoClient:
    """Build an online client whose last activity is outside the grace period."""
    client = TpLinkDecoClient(mac)
    client.deco_mac = deco_mac
    client.online = True
    client.last_activity = datetime.now(timezone.utc) - timedelta(minutes=30)
    return client


def _coordinator(
    *,
    two_decos: bool = False,
    old_clients: dict[str, TpLinkDecoClient] | None = None,
) -> tuple[TplinkDecoClientUpdateCoordinator, MagicMock]:
    """Create an independent client coordinator with mocked Home Assistant."""
    api = MagicMock(spec=TplinkDecoApi)
    master = TpLinkDeco(MASTER_MAC)
    decos = {MASTER_MAC: master}
    if two_decos:
        decos[SATELLITE_MAC] = TpLinkDeco(SATELLITE_MAC)

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
@pytest.mark.parametrize("status", [500, 502, 503])
async def test_http_5xx_starts_backoff_without_losing_known_clients(
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Back off on a 5xx error while retaining online state and association."""
    old = _old_client(MASTER_CLIENT, MASTER_MAC)
    coordinator, api = _coordinator(old_clients={old.mac: old})
    api.async_list_clients = AsyncMock(side_effect=_response_error(status))

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        with caplog.at_level(logging.DEBUG):
            result = await coordinator._async_update_data()

    assert result[MASTER_CLIENT] is old
    assert old.online is True
    assert old.deco_mac == MASTER_MAC
    assert coordinator._client_backoff_seconds == CLIENT_BACKOFF_INITIAL_SECONDS
    assert coordinator._client_backoff_until == 1030
    assert api.async_list_clients.await_count == 1
    assert STOK not in caplog.text
    assert COOKIE not in caplog.text


@pytest.mark.asyncio
async def test_backoff_skips_requests_and_preserves_last_known_state() -> None:
    """No router requests are made while the exponential delay is active."""
    old = _old_client(MASTER_CLIENT, MASTER_MAC)
    coordinator, api = _coordinator(old_clients={old.mac: old})
    api.async_list_clients = AsyncMock(side_effect=_response_error())

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        coordinator.data = await coordinator._async_update_data()

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1011
    ):
        result = await coordinator._async_update_data()
        assert coordinator.remaining_backoff_seconds == 19

    assert result is coordinator.data
    assert result[MASTER_CLIENT].online is True
    assert api.async_list_clients.await_count == 1


@pytest.mark.asyncio
async def test_repeated_http_500_backoff_doubles_and_caps() -> None:
    """Progress from 30 to 60, 120, 240, 300, then remain at 300 seconds."""
    coordinator, api = _coordinator()
    api.async_list_clients = AsyncMock(side_effect=_response_error())

    for start, delay in [
        (1000, 30),
        (1031, 60),
        (1092, 120),
        (1213, 240),
        (1454, 300),
        (1765, 300),
    ]:
        with patch(
            "custom_components.tplink_deco.coordinator.monotonic",
            return_value=start,
        ):
            coordinator.data = await coordinator._async_update_data()
            assert coordinator._client_backoff_seconds == delay
            assert coordinator._client_backoff_until == start + delay
            assert coordinator.remaining_backoff_seconds == delay

    assert coordinator._client_backoff_seconds == CLIENT_BACKOFF_MAX_SECONDS
    assert api.async_list_clients.await_count == 6


@pytest.mark.asyncio
async def test_successful_recovery_resets_backoff_and_next_failure_restarts() -> None:
    """A new HTTP 5xx incident begins at 30 seconds, not the previous delay."""
    coordinator, api = _coordinator()
    api.async_list_clients = AsyncMock(
        side_effect=[
            _response_error(),
            [{"mac": MASTER_CLIENT, "name": "recovered", "online": True}],
            _response_error(),
        ]
    )

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        coordinator.data = await coordinator._async_update_data()
    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1031
    ):
        coordinator.data = await coordinator._async_update_data()

    assert coordinator._client_backoff_seconds == 0
    assert coordinator._client_backoff_until == 0.0
    assert coordinator.data[MASTER_CLIENT].online is True

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1050
    ):
        coordinator.data = await coordinator._async_update_data()

    assert coordinator._client_backoff_seconds == 30
    assert api.async_list_clients.await_count == 3


@pytest.mark.asyncio
async def test_partial_node_success_preserved_during_500_backoff() -> None:
    """One faulty node cannot discard clients returned by a healthy peer."""
    old = _old_client(MASTER_CLIENT, MASTER_MAC)
    coordinator, api = _coordinator(two_decos=True, old_clients={old.mac: old})

    async def _per_node_clients(deco_mac: str) -> list[dict[str, object]]:
        """Simulate a master 500 and successful satellite client list."""
        if deco_mac == MASTER_MAC:
            raise _response_error()
        return [{"mac": NEW_CLIENT, "name": "new", "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_per_node_clients)

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        result = await coordinator._async_update_data()

    assert result[MASTER_CLIENT] is old
    assert old.online is True
    assert result[NEW_CLIENT].online is True
    assert result[NEW_CLIENT].deco_mac == SATELLITE_MAC
    assert coordinator._client_backoff_seconds == 30
    assert api.async_list_clients.await_count == 2


@pytest.mark.asyncio
async def test_all_nodes_failing_preserves_last_known_data() -> None:
    """Do not mark clients offline even if last activity is stale."""
    master = _old_client(MASTER_CLIENT, MASTER_MAC)
    satellite = _old_client(SATELLITE_CLIENT, SATELLITE_MAC)
    unassigned = _old_client(NEW_CLIENT, MASTER_MAC)
    unassigned.deco_mac = None
    coordinator, api = _coordinator(
        two_decos=True,
        old_clients={
            master.mac: master,
            satellite.mac: satellite,
            unassigned.mac: unassigned,
        },
    )
    api.async_list_clients = AsyncMock(side_effect=_response_error())

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        result = await coordinator._async_update_data()

    assert set(result) == {MASTER_CLIENT, SATELLITE_CLIENT, NEW_CLIENT}
    assert result[MASTER_CLIENT] is master
    assert result[SATELLITE_CLIENT] is satellite
    assert result[NEW_CLIENT] is unassigned
    assert all(client.online for client in result.values())
    assert coordinator._client_backoff_seconds == 30


@pytest.mark.asyncio
async def test_http_401_and_403_remain_nonretryable() -> None:
    """Authentication failures must propagate instead of triggering backoff."""
    coordinator, api = _coordinator()
    for status in (401, 403):
        api.async_list_clients = AsyncMock(side_effect=_response_error(status))
        with pytest.raises(aiohttp.ClientResponseError) as failure:
            await coordinator._async_update_data()
        assert failure.value.status == status
        assert coordinator._client_backoff_seconds == 0


@pytest.mark.asyncio
async def test_truncated_reply_does_not_start_http_backoff() -> None:
    """Keep transient-response retries distinct from HTTP server errors."""
    old = _old_client(MASTER_CLIENT, MASTER_MAC)
    coordinator, api = _coordinator(old_clients={old.mac: old})
    api.async_list_clients = AsyncMock(
        side_effect=TransientConnectionException("incomplete")
    )

    result = await coordinator._async_update_data()

    assert result[MASTER_CLIENT] is old
    assert old.online is True
    assert coordinator._client_backoff_seconds == 0


@pytest.mark.asyncio
async def test_successful_empty_node_response_resets_backoff() -> None:
    """Valid empty client lists still follow the normal offline grace policy."""
    old = _old_client(MASTER_CLIENT, MASTER_MAC)
    coordinator, api = _coordinator(old_clients={old.mac: old})
    coordinator._client_backoff_seconds = 30
    coordinator._client_backoff_until = 1000
    api.async_list_clients = AsyncMock(return_value=[])

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1031
    ):
        result = await coordinator._async_update_data()

    assert result[MASTER_CLIENT].online is False
    assert coordinator._client_backoff_seconds == 0


@pytest.mark.asyncio
async def test_backoff_is_isolated_per_config_entry() -> None:
    """A failing router must not prevent another config entry from polling."""
    failing, failing_api = _coordinator()
    healthy, healthy_api = _coordinator()
    failing_api.async_list_clients = AsyncMock(side_effect=_response_error())
    healthy_api.async_list_clients = AsyncMock(return_value=[])

    with patch(
        "custom_components.tplink_deco.coordinator.monotonic", return_value=1000
    ):
        await failing._async_update_data()
        await healthy._async_update_data()

    assert failing._client_backoff_seconds == 30
    assert healthy._client_backoff_seconds == 0
    healthy_api.async_list_clients.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_session_survives_client_list_500_without_sensitive_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not log the LuCI token or clear authentication on HTTP 500."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host="http://192.0.2.1",
        username="placeholder",
        password="placeholder",
        verify_ssl=True,
    )
    api._stok = STOK
    api._cookie = COOKIE
    api._seq = 42
    response = MagicMock()
    response.raise_for_status.side_effect = _response_error()
    response.headers.getall.return_value = []
    session.post.return_value = response

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(aiohttp.ClientResponseError):
            await api._async_post(
                "List Clients",
                f"http://192.0.2.1/cgi-bin/luci/;stok={STOK}/admin/client",
                params={"form": "client_list"},
                data="mock-request",
            )

    assert (api._stok, api._cookie, api._seq) == (STOK, COOKIE, 42)
    assert STOK not in caplog.text
    assert COOKIE not in caplog.text
