"""Regressions for privacy-safe, atomic per-Deco client-list validation."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import traceback
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.exceptions import InvalidClientListException
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.sensor import TplinkDecoClientCountSensor
from custom_components.tplink_deco.sensor import TplinkTotalClientDataRateSensor

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
    api.async_list_clients.assert_awaited_once_with(MASTER_MAC, timeout_error_retries=0)


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_response",
    [None, {}, {"private": PRIVATE_VALUE}, "", PRIVATE_VALUE, 42],
    ids=[
        "null",
        "empty-object",
        "populated-object",
        "empty-string",
        "string",
        "number",
    ],
)
@pytest.mark.parametrize("failed_node", [MASTER_MAC, SATELLITE_MAC])
async def test_mesh_non_list_peer_preserves_valid_client_sensors_and_recovers(
    invalid_response: object,
    failed_node: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep good mesh peers available and old failed-node client state intact."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.deco_mac = failed_node
    old_client.online = True
    old_client.down_kilobytes_per_s = 2.0
    old_client.up_kilobytes_per_s = 1.0
    old_client.last_activity = datetime.now(timezone.utc)
    previous_activity = old_client.last_activity
    coordinator, api = _coordinator({CLIENT_MAC: old_client}, two_decos=True)
    good_node = SATELLITE_MAC if failed_node == MASTER_MAC else MASTER_MAC

    async def _list_clients(deco_mac: str, *, timeout_error_retries: int) -> object:
        """Return an invalid peer and one valid client-list response."""
        assert timeout_error_retries == 0
        if deco_mac == failed_node:
            return invalid_response
        return [
            {
                "mac": NEW_CLIENT_MAC,
                "name": "fixture",
                "online": True,
                "down_speed": 80,
                "up_speed": 32,
            }
        ]

    api.async_list_clients = AsyncMock(side_effect=_list_clients)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        with caplog.at_level(logging.DEBUG):
            await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.health.last_error == "0"
    assert coordinator.health.last_successful_update is not None
    assert coordinator.successfully_polled_deco_macs == {good_node}
    assert coordinator.data[CLIENT_MAC] is old_client
    assert old_client.deco_mac == failed_node
    assert old_client.online is True
    assert old_client.last_activity == previous_activity
    assert coordinator.data[NEW_CLIENT_MAC].deco_mac == good_node
    assert coordinator.data[NEW_CLIENT_MAC].online is True
    assert PRIVATE_VALUE not in caplog.text
    assert CLIENT_MAC not in caplog.text
    assert NEW_CLIENT_MAC not in caplog.text

    count_sensor = TplinkDecoClientCountSensor(
        coordinator_decos=coordinator._deco_update_coordinator,
        coordinator_clients=coordinator,
        deco_mac=good_node,
    )
    assert count_sensor.available is True
    assert count_sensor.native_value == 1
    assert count_sensor.unique_id == f"{good_node}_client_count"

    throughput = TplinkTotalClientDataRateSensor(
        coordinator_decos=coordinator._deco_update_coordinator,
        coordinator_clients=coordinator,
        name="Network download",
        unique_id="mesh_total_down",
        client_attribute="down_kilobytes_per_s",
        deco=None,
    )
    assert throughput.available is True
    assert throughput.native_value == pytest.approx(12.0)

    async def _recovered(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Return valid lists for both peers after the firmware recovers."""
        assert timeout_error_retries == 0
        if deco_mac == failed_node:
            return [{"mac": CLIENT_MAC, "name": "restored", "online": True}]
        return [{"mac": NEW_CLIENT_MAC, "name": "fixture", "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_recovered)
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.health.consecutive_failures == 0
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC, SATELLITE_MAC}
    assert coordinator.data[CLIENT_MAC] is old_client
    assert coordinator.data[CLIENT_MAC].name == "restored"


@pytest.mark.asyncio
async def test_typed_firmware_client_error_is_isolated_to_one_peer() -> None:
    """Treat the API's specific shape error as a failed node, not an empty list."""
    coordinator, api = _coordinator(two_decos=True)

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Simulate typed parsing failure from the real API boundary."""
        assert timeout_error_retries == 0
        if deco_mac == SATELLITE_MAC:
            raise InvalidClientListException("Deco client-list response must be a list")
        return [{"mac": CLIENT_MAC, "name": "fixture", "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_clients)
    result = await coordinator._async_update_data()

    assert result[CLIENT_MAC].deco_mac == MASTER_MAC
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC}
    assert coordinator.health.last_error == "0"


@pytest.mark.asyncio
async def test_all_invalid_mesh_client_lists_remain_failed_not_empty() -> None:
    """Reject a fully invalid mesh without changing cached node identities."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.deco_mac = MASTER_MAC
    old_client.online = True
    coordinator, api = _coordinator({CLIENT_MAC: old_client}, two_decos=True)
    async def _invalid_clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> object:
        """Simulate an invalid mesh and an invalid global firmware response."""
        assert timeout_error_retries == 0
        if deco_mac == "default":
            raise InvalidClientListException("Deco client-list response must be a list")
        return {}

    api.async_list_clients = AsyncMock(side_effect=_invalid_clients)

    with pytest.raises(ValueError, match="^Invalid Deco client list response$"):
        await coordinator._async_update_data()

    assert coordinator.data == {CLIENT_MAC: old_client}
    assert old_client.online is True
    assert coordinator.health.last_error == "ValueError"
    assert coordinator.health.consecutive_failures == 1
    assert coordinator.successfully_polled_deco_macs == set()
    assert api.async_list_clients.await_count == 3
    assert api.async_list_clients.await_args_list[-1].args == ("default",)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_empty", [{}, ""], ids=["empty-object", "empty-string"])
@pytest.mark.parametrize("empty_node", [MASTER_MAC, SATELLITE_MAC])
async def test_real_api_legacy_empty_reply_keeps_both_mesh_counts_live(
    legacy_empty: dict[str, object] | str,
    empty_node: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Normalize actual firmware replies before atomic per-node reconciliation."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.deco_mac = empty_node
    old_client.online = True
    old_client.last_activity = datetime.now(timezone.utc) - timedelta(hours=1)
    coordinator, _ = _coordinator({CLIENT_MAC: old_client}, two_decos=True)
    populated_node = SATELLITE_MAC if empty_node == MASTER_MAC else MASTER_MAC

    api = TplinkDecoApi(
        session=MagicMock(),
        host="http://192.0.2.1",
        username="admin",
        password="dummy-password",
        verify_ssl=True,
    )
    api.async_login_if_needed = AsyncMock()
    api._encode_payload = MagicMock(return_value="mocked-request-body")
    api._async_post = AsyncMock(return_value={"data": "encrypted-fixture"})
    api._stok = "synthetic-token"

    def _decode_data(context: str, encrypted: str) -> dict[str, object]:
        """Return node-specific decrypted fixtures without a router request."""
        assert encrypted == "encrypted-fixture"
        is_empty_node = context == f"List Clients {empty_node}"
        return {
            "error_code": 0,
            "result": {
                "client_list": (
                    legacy_empty
                    if is_empty_node
                    else [
                        {
                            "mac": NEW_CLIENT_MAC,
                            "name": "fixture",
                            "online": True,
                            "down_speed": 80,
                        }
                    ]
                )
            },
        }

    api._decrypt_data = MagicMock(side_effect=_decode_data)
    coordinator.api = api
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        with caplog.at_level(logging.DEBUG):
            await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.health.last_error == "0"
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC, SATELLITE_MAC}
    assert coordinator.data[CLIENT_MAC] is old_client
    assert old_client.deco_mac == empty_node
    assert old_client.online is False
    assert coordinator.data[NEW_CLIENT_MAC].deco_mac == populated_node
    assert coordinator.data[NEW_CLIENT_MAC].online is True
    assert api._async_post.await_count == 2

    for node_mac, expected_count in ((empty_node, 0), (populated_node, 1)):
        count_sensor = TplinkDecoClientCountSensor(
            coordinator_decos=coordinator._deco_update_coordinator,
            coordinator_clients=coordinator,
            deco_mac=node_mac,
        )
        assert count_sensor.available is True
        assert count_sensor.native_value == expected_count
        assert count_sensor.unique_id == f"{node_mac}_client_count"

    rate_sensor = TplinkTotalClientDataRateSensor(
        coordinator_decos=coordinator._deco_update_coordinator,
        coordinator_clients=coordinator,
        name="Network download",
        unique_id="mesh_total_down",
        client_attribute="down_kilobytes_per_s",
        deco=None,
    )
    assert rate_sensor.available is True
    assert rate_sensor.native_value == pytest.approx(10.0)
    assert "Deco client poll returned an unsupported list type" not in caplog.text
    assert "Invalid Deco client list response" not in caplog.text
    assert CLIENT_MAC not in caplog.text
    assert NEW_CLIENT_MAC not in caplog.text



@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_node", [MASTER_MAC, SATELLITE_MAC])
async def test_all_invalid_node_lists_recover_from_valid_global_client_list(
    invalid_node: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Use one strictly validated global fallback when every node poll failed."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.deco_mac = MASTER_MAC
    old_client.online = False
    coordinator, api = _coordinator({CLIENT_MAC: old_client}, two_decos=True)
    original_identity = old_client
    query_order: list[str] = []

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Return invalid node shapes and one usable global inventory."""
        assert timeout_error_retries == 0
        query_order.append(deco_mac)
        if deco_mac == invalid_node:
            raise InvalidClientListException("Deco client-list response must be a list")
        if deco_mac != "default":
            raise InvalidClientListException("Deco client-list response must be a list")
        return [
            {"mac": CLIENT_MAC, "name": "known", "online": True, "down_speed": 80},
            {"mac": NEW_CLIENT_MAC, "name": "new", "online": True, "up_speed": 32},
        ]

    api.async_list_clients = AsyncMock(side_effect=_clients)

    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        with caplog.at_level(logging.DEBUG):
            await coordinator.async_refresh()

    assert query_order[-1] == "default"
    assert set(query_order[:-1]) == {MASTER_MAC, SATELLITE_MAC}
    assert len(query_order) == 3
    assert coordinator.last_update_success is True
    assert coordinator.health.last_error == "0"
    assert coordinator.health.consecutive_failures == 0
    assert coordinator.client_query_mode == "global"
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC}
    assert coordinator.data[CLIENT_MAC] is original_identity
    assert original_identity.online is True
    assert original_identity.deco_mac == MASTER_MAC
    assert coordinator.data[NEW_CLIENT_MAC].deco_mac == MASTER_MAC
    assert coordinator.data[NEW_CLIENT_MAC].online is True

    master_count = TplinkDecoClientCountSensor(
        coordinator_decos=coordinator._deco_update_coordinator,
        coordinator_clients=coordinator,
        deco_mac=MASTER_MAC,
    )
    satellite_count = TplinkDecoClientCountSensor(
        coordinator_decos=coordinator._deco_update_coordinator,
        coordinator_clients=coordinator,
        deco_mac=SATELLITE_MAC,
    )
    assert master_count.available is True
    assert master_count.native_value == 2
    assert satellite_count.available is False

    throughput = TplinkTotalClientDataRateSensor(
        coordinator_decos=coordinator._deco_update_coordinator,
        coordinator_clients=coordinator,
        name="Total Down",
        unique_id="mesh_total_down",
        client_attribute="down_kilobytes_per_s",
        deco=None,
    )
    assert throughput.available is True
    assert throughput.native_value == pytest.approx(10.0)
    assert "All Deco node client polls failed; trying one global query" in caplog.text
    assert CLIENT_MAC not in caplog.text
    assert NEW_CLIENT_MAC not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("global_failure", ["timeout", "bad_item", "bad_type"])
async def test_all_invalid_global_fallback_never_commits_untrusted_client_data(
    global_failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep prior client identities on a failed or malformed global recovery."""
    old_client = TpLinkDecoClient(CLIENT_MAC)
    old_client.deco_mac = SATELLITE_MAC
    old_client.online = True
    coordinator, api = _coordinator({CLIENT_MAC: old_client}, two_decos=True)

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> object:
        """Return safe synthetic invalid responses for every query."""
        assert timeout_error_retries == 0
        if deco_mac != "default":
            raise InvalidClientListException(PRIVATE_VALUE)
        if global_failure == "timeout":
            raise TimeoutException(PRIVATE_VALUE)
        if global_failure == "bad_type":
            raise InvalidClientListException(PRIVATE_VALUE)
        return [{"mac": NEW_CLIENT_MAC}, {"mac": None, "name": PRIVATE_VALUE}]

    api.async_list_clients = AsyncMock(side_effect=_clients)
    with (
        patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"),
        caplog.at_level(logging.DEBUG),
    ):
        with pytest.raises(
            ValueError, match="^Invalid (global )?Deco client list response$"
        ):
            await coordinator._async_update_data()

    assert coordinator.health.last_error == "ValueError"
    assert coordinator.data == {CLIENT_MAC: old_client}
    assert old_client.online is True
    assert old_client.deco_mac == SATELLITE_MAC
    assert coordinator.successfully_polled_deco_macs == set()
    assert coordinator.has_successful_refresh is False
    assert coordinator.health.consecutive_failures == 1
    assert api.async_list_clients.await_count == 3
    assert PRIVATE_VALUE not in caplog.text


@pytest.mark.asyncio
async def test_valid_peer_skips_global_fallback_after_an_invalid_node() -> None:
    """Do not add a global query when at least one real node is healthy."""
    coordinator, api = _coordinator(two_decos=True)

    async def _clients(
        deco_mac: str, *, timeout_error_retries: int
    ) -> list[dict[str, object]]:
        """Return one invalid node and a healthy peer."""
        assert deco_mac != "default"
        assert timeout_error_retries == 0
        if deco_mac == SATELLITE_MAC:
            raise InvalidClientListException("Deco client-list response must be a list")
        return [{"mac": CLIENT_MAC, "online": True}]

    api.async_list_clients = AsyncMock(side_effect=_clients)
    result = await coordinator._async_update_data()

    assert result[CLIENT_MAC].deco_mac == MASTER_MAC
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC}
    assert coordinator.client_query_mode == "per_node"
    assert api.async_list_clients.await_count == 2
