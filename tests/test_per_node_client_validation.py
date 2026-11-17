"""Regressions for privacy-safe, atomic per-Deco client-list validation."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import traceback
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.exceptions import TimeoutException

MASTER_MAC = "02:00:00:00:60:01"
SATELLITE_MAC = "02:00:00:00:60:02"
CLIENT_MAC = "02:00:00:00:60:10"
NEW_CLIENT_MAC = "02:00:00:00:60:11"
PRIVATE_VALUE = "synthetic-private-router-token"


def _coordinator(
    old_clients: dict[str, TpLinkDecoClient] | None = None,
    *,
    two_decos: bool = False,
) -> tuple[TplinkDecoClientUpdateCoordinator, MagicMock]:
    """Build an isolated real client coordinator with a mocked Deco API."""
    master = TpLinkDeco(MASTER_MAC)
    decos = {MASTER_MAC: master}
    if two_decos:
        decos[SATELLITE_MAC] = TpLinkDeco(SATELLITE_MAC)

    deco_coordinator = MagicMock()
    deco_coordinator.paused = False
    deco_coordinator.data = TpLinkDecoData(master, decos)
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
@pytest.mark.parametrize(
    "invalid_entry",
    [
        None,
        {},
        {"mac": None},
        {"mac": ""},
        {"mac": 7},
        {"mac": CLIENT_MAC, "name": "duplicate"},
        {"mac": NEW_CLIENT_MAC, "name": {"private": PRIVATE_VALUE}},
    ],
    ids=[
        "non-mapping",
        "missing-mac",
        "null-mac",
        "empty-mac",
        "numeric-mac",
        "duplicate-mac",
        "invalid-client-name",
    ],
)
async def test_late_invalid_node_reply_preserves_prior_client_state(
    invalid_entry: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bad later entry must not partially update a cached client."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.name = "original"
    old_client.deco_mac = MASTER_MAC
    old_client.online = True
    old_client.last_activity = datetime.now(timezone.utc) - timedelta(hours=1)
    previous_activity = old_client.last_activity
    coordinator, api = _coordinator({CLIENT_MAC: old_client})
    api.async_list_clients = AsyncMock(
        return_value=[
            {"mac": CLIENT_MAC, "name": "changed", "online": False},
            invalid_entry,
        ]
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(
            ValueError, match="^Invalid Deco client list response$"
        ) as exc:
            await coordinator._async_update_data()

    assert coordinator.data == {CLIENT_MAC: old_client}
    assert old_client.name == "original"
    assert old_client.deco_mac == MASTER_MAC
    assert old_client.online is True
    assert old_client.last_activity == previous_activity
    assert coordinator.successfully_polled_deco_macs == set()
    assert coordinator.has_successful_refresh is False
    assert coordinator.health.last_error == "ValueError"
    assert coordinator.health.consecutive_failures == 1
    assert exc.value.__cause__ is None
    assert PRIVATE_VALUE not in caplog.text
    assert PRIVATE_VALUE not in "".join(traceback.format_exception(exc.value))
    api.async_list_clients.assert_awaited_once_with(MASTER_MAC, timeout_error_retries=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"bad": PRIVATE_VALUE}, PRIVATE_VALUE, 42])
async def test_malformed_node_response_type_is_rejected_without_state_changes(
    response: object,
) -> None:
    """A mapping, scalar or string must never masquerade as a client list."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.online = True
    coordinator, api = _coordinator({CLIENT_MAC: old_client})
    api.async_list_clients = AsyncMock(return_value=response)

    with pytest.raises(ValueError, match="^Invalid Deco client list response$"):
        await coordinator._async_update_data()

    assert coordinator.data[CLIENT_MAC] is old_client
    assert old_client.online is True
    assert not coordinator.successfully_polled_deco_macs
    assert coordinator.health.last_error == "ValueError"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_ip",
    [
        "not-an-ip-address",
        {"private": PRIVATE_VALUE},
    ],
    ids=["malformed-ip-string", "unexpected-ip-mapping"],
)
async def test_invalid_client_ip_normalizes_without_rejecting_valid_peer(
    invalid_ip: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve a successful client refresh when firmware sends an invalid IP."""
    cached_client = TpLinkDecoClient(CLIENT_MAC)
    cached_client.name = "old-name"
    cached_client.ip_address = "192.0.2.1"
    cached_client.online = False
    coordinator, api = _coordinator({CLIENT_MAC: cached_client})
    api.async_list_clients = AsyncMock(
        return_value=[
            {
                "mac": CLIENT_MAC,
                "name": "updated-name",
                "ip": invalid_ip,
                "online": True,
            }
        ]
    )

    with caplog.at_level(logging.DEBUG):
        result = await coordinator._async_update_data()

    assert result[CLIENT_MAC] is cached_client
    assert cached_client.name == "updated-name"
    assert cached_client.ip_address is None
    assert cached_client.online is True
    assert cached_client.deco_mac == MASTER_MAC
    assert cached_client.last_activity is not None
    assert coordinator.has_successful_refresh is True
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC}
    assert coordinator.health.consecutive_failures == 0
    assert coordinator.health.last_error == "0"
    assert coordinator.health.last_successful_update is not None
    assert CLIENT_MAC not in caplog.text
    assert PRIVATE_VALUE not in caplog.text
    api.async_list_clients.assert_awaited_once_with(
        MASTER_MAC, timeout_error_retries=0
    )


@pytest.mark.asyncio
async def test_valid_peer_updates_when_other_node_times_out() -> None:
    """A missing node response remains incomplete, not an empty success."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.deco_mac = SATELLITE_MAC
    old_client.online = True
    coordinator, api = _coordinator({CLIENT_MAC: old_client}, two_decos=True)

    async def _client_list(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Provide one valid peer and one exhausted node timeout."""
        assert timeout_error_retries == 0
        if deco_mac == SATELLITE_MAC:
            raise TimeoutException(PRIVATE_VALUE)
        return [{"mac": NEW_CLIENT_MAC, "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_client_list)
    result = await coordinator._async_update_data()

    assert result[CLIENT_MAC] is old_client
    assert old_client.online is True
    assert old_client.deco_mac == SATELLITE_MAC
    assert result[NEW_CLIENT_MAC].deco_mac == MASTER_MAC
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC}
    assert coordinator.health.timeout_count == 1


@pytest.mark.asyncio
async def test_new_client_discovery_does_not_log_client_mac(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A successful discovery must not reveal a client's MAC at DEBUG level."""
    coordinator, api = _coordinator()
    api.async_list_clients = AsyncMock(
        return_value=[{"mac": NEW_CLIENT_MAC, "name": PRIVATE_VALUE, "online": True}]
    )

    with caplog.at_level(logging.DEBUG):
        result = await coordinator._async_update_data()

    assert NEW_CLIENT_MAC in result
    assert result[NEW_CLIENT_MAC].name == PRIVATE_VALUE
    assert NEW_CLIENT_MAC not in caplog.text
    assert PRIVATE_VALUE not in caplog.text
    assert coordinator.health.last_successful_update is not None
