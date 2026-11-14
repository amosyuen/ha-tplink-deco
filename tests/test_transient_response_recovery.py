"""Regressions for bounded transport retries and retained Deco client state."""

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
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.exceptions import TransientConnectionException

HOST = "http://192.0.2.1"
TOKEN = "synthetic-secret-token"
COOKIE = "sysauth=deadbeef"
MASTER_MAC = "00:00:00:00:00:01"
SATELLITE_MAC = "00:00:00:00:00:02"
MASTER_CLIENT = "00:00:00:00:00:11"
SATELLITE_CLIENT = "00:00:00:00:00:12"
NEW_CLIENT = "00:00:00:00:00:13"


def _api(retries: int = 1) -> tuple[TplinkDecoApi, AsyncMock]:
    """Create an authenticated API without live network access."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host=HOST,
        username="test",
        password="placeholder",
        verify_ssl=True,
        timeout_error_retries=retries,
    )
    api._stok = TOKEN
    api._cookie = COOKIE
    api._seq = 17
    api._encode_payload = MagicMock(return_value="fake-request")
    api._decrypt_data = MagicMock(
        return_value={"error_code": 0, "result": {"device_list": []}}
    )
    api.async_login = AsyncMock()
    return api, session.post


def _response(json_error: aiohttp.ClientError | None = None) -> MagicMock:
    """Return a fake successful response or an incomplete JSON body."""
    response = MagicMock()
    response.history = ()
    response.headers.getall.return_value = []
    response.raise_for_status = MagicMock()
    if json_error is None:
        response.json = AsyncMock(return_value={"data": "fake-ciphertext"})
    else:
        response.json = AsyncMock(side_effect=json_error)
    return response


def _client(mac: str, deco_mac: str) -> TpLinkDecoClient:
    """Create a previously online client with an old activity timestamp."""
    client = TpLinkDecoClient(mac)
    client.deco_mac = deco_mac
    client.online = True
    client.last_activity = datetime.now(timezone.utc) - timedelta(minutes=30)
    return client


def _client_coordinator(
    api: MagicMock,
    old_clients: dict[str, TpLinkDecoClient],
) -> TplinkDecoClientUpdateCoordinator:
    """Construct a real coordinator for two synthetic mesh nodes."""
    master = TpLinkDeco(MASTER_MAC)
    satellite = TpLinkDeco(SATELLITE_MAC)
    deco_coordinator = MagicMock()
    deco_coordinator.paused = False
    deco_coordinator.data = TpLinkDecoData(
        master, {MASTER_MAC: master, SATELLITE_MAC: satellite}
    )
    return TplinkDecoClientUpdateCoordinator(
        hass=MagicMock(),
        api=api,
        config_entry=MagicMock(),
        deco_update_coordinator=deco_coordinator,
        consider_home_seconds=60,
        data=old_clients,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [aiohttp.ServerDisconnectedError(), aiohttp.ClientPayloadError("cut off")],
)
async def test_transport_retry_recovers_without_relogin(
    transport_error: aiohttp.ClientError,
) -> None:
    """Retry an incomplete API request without clearing authentication."""
    api, post = _api()
    post.side_effect = [transport_error, _response()]

    assert await api.async_list_devices() == []
    assert post.await_count == 2
    api.async_login.assert_not_awaited()
    assert (api._stok, api._cookie, api._seq) == (TOKEN, COOKIE, 17)


@pytest.mark.asyncio
async def test_incomplete_json_body_is_retried() -> None:
    """Retry a payload failure occurring while reading the HTTP body."""
    api, post = _api()
    post.side_effect = [
        _response(aiohttp.ClientPayloadError("truncated")),
        _response(),
    ]

    assert await api.async_list_devices() == []
    assert post.await_count == 2
    api.async_login.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhaustion_keeps_auth_and_private_payloads_out_of_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bound retries and redact secret-bearing transport errors."""
    api, post = _api()
    post.side_effect = aiohttp.ClientPayloadError(f"private {TOKEN} {COOKIE}")

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TransientConnectionException) as exc_info:
            await api.async_list_devices()

    assert isinstance(exc_info.value.__cause__, aiohttp.ClientPayloadError)
    assert post.await_count == 2
    assert (api._stok, api._cookie, api._seq) == (TOKEN, COOKIE, 17)
    assert TOKEN not in caplog.text
    assert COOKIE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [aiohttp.ServerDisconnectedError(), aiohttp.ClientPayloadError("cut off")],
)
async def test_zero_retries_is_respected(
    transport_error: aiohttp.ClientError,
) -> None:
    """Do not override an existing zero-retry configuration."""
    api, post = _api(retries=0)
    post.side_effect = transport_error

    with pytest.raises(TransientConnectionException):
        await api.async_list_devices()

    assert post.await_count == 1
    assert api._stok == TOKEN


@pytest.mark.asyncio
async def test_timeout_and_transport_retry_budgets_are_independent() -> None:
    """Keep existing timeout behavior separate from incomplete responses."""
    api, _ = _api()
    action = AsyncMock(
        side_effect=[
            TimeoutException(),
            TransientConnectionException("incomplete"),
            "recovered",
        ]
    )

    assert await api._async_call_with_retry(action) == "recovered"
    assert action.await_count == 3


@pytest.mark.asyncio
async def test_cancellation_is_not_retried() -> None:
    """Preserve Home Assistant cancellation propagation."""
    api, _ = _api()
    action = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await api._async_call_with_retry(action)

    assert action.await_count == 1


@pytest.mark.asyncio
async def test_failed_node_keeps_clients_while_peer_node_updates() -> None:
    """Preserve failed-node clients, including expired last activity."""
    old = _client(MASTER_CLIENT, MASTER_MAC)
    api = MagicMock(spec=TplinkDecoApi)

    async def _list_clients(deco_mac: str) -> list[dict[str, object]]:
        """Fail one node while delivering the peer's new client data."""
        if deco_mac == MASTER_MAC:
            raise TransientConnectionException("incomplete")
        return [{"mac": NEW_CLIENT, "name": "new", "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_list_clients)
    coordinator = _client_coordinator(api, {old.mac: old})
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        result = await coordinator._async_update_data()

    assert result[MASTER_CLIENT] is old
    assert old.online is True
    assert old.deco_mac == MASTER_MAC
    assert result[NEW_CLIENT].online is True
    assert result[NEW_CLIENT].deco_mac == SATELLITE_MAC
    assert api.async_list_clients.await_count == 2


@pytest.mark.asyncio
async def test_empty_success_is_not_confused_with_failed_node() -> None:
    """Apply normal offline grace only on nodes polled successfully."""
    master_client = _client(MASTER_CLIENT, MASTER_MAC)
    satellite_client = _client(SATELLITE_CLIENT, SATELLITE_MAC)
    api = MagicMock(spec=TplinkDecoApi)

    async def _list_clients(deco_mac: str) -> list[dict[str, object]]:
        """Return a genuine empty list for the satellite only."""
        if deco_mac == MASTER_MAC:
            raise TransientConnectionException("incomplete")
        return []

    api.async_list_clients = AsyncMock(side_effect=_list_clients)
    coordinator = _client_coordinator(
        api, {master_client.mac: master_client, satellite_client.mac: satellite_client}
    )

    result = await coordinator._async_update_data()

    assert result[MASTER_CLIENT].online is True
    assert result[SATELLITE_CLIENT].online is False
    assert result[MASTER_CLIENT].deco_mac == MASTER_MAC


@pytest.mark.asyncio
async def test_all_failed_nodes_preserve_last_known_clients() -> None:
    """Keep clients when every node's response is incomplete."""
    master_client = _client(MASTER_CLIENT, MASTER_MAC)
    satellite_client = _client(SATELLITE_CLIENT, SATELLITE_MAC)
    api = MagicMock(spec=TplinkDecoApi)
    api.async_list_clients = AsyncMock(
        side_effect=TransientConnectionException("incomplete")
    )
    coordinator = _client_coordinator(
        api, {master_client.mac: master_client, satellite_client.mac: satellite_client}
    )

    result = await coordinator._async_update_data()

    assert set(result) == {MASTER_CLIENT, SATELLITE_CLIENT}
    assert all(client.online is True for client in result.values())
    assert api.async_list_clients.await_count == 2


@pytest.mark.asyncio
async def test_unexpected_node_error_is_not_hidden() -> None:
    """Surface programming/response failures unrelated to truncation."""
    api = MagicMock(spec=TplinkDecoApi)
    api.async_list_clients = AsyncMock(side_effect=ValueError("bad data"))
    coordinator = _client_coordinator(api, {})

    with pytest.raises(ValueError, match="bad data"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_performance_failure_keeps_previous_cpu_and_memory() -> None:
    """Retain existing CPU and memory readings after transport exhaustion."""
    master = TpLinkDeco(MASTER_MAC)
    master.cpu_usage = 17.0
    master.cpu_usage_raw = 12.0
    master.mem_usage = 49.0
    master.mem_usage_raw = 46.0
    api = MagicMock(spec=TplinkDecoApi)
    api.async_list_devices = AsyncMock(
        return_value=[{"mac": MASTER_MAC, "role": "master"}]
    )
    api.async_get_performance = AsyncMock(
        side_effect=TransientConnectionException("incomplete")
    )
    coordinator = TplinkDecoUpdateCoordinator(
        hass=MagicMock(),
        api=api,
        config_entry=MagicMock(),
        data=TpLinkDecoData(master, {MASTER_MAC: master}),
    )

    result = await coordinator._async_update_data()

    assert result.master_deco is master
    assert result.decos[MASTER_MAC] is master
    assert (master.cpu_usage, master.cpu_usage_raw) == (17.0, 12.0)
    assert (master.mem_usage, master.mem_usage_raw) == (49.0, 46.0)
    api.async_get_performance.assert_awaited_once()
