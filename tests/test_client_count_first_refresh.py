"""Regressions for accurate, deferred per-Deco connected-client counts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.sensor import TplinkDecoClientCountSensor
from custom_components.tplink_deco.sensor import async_setup_entry

MASTER_MAC = "02:00:00:00:10:01"
SATELLITE_MAC = "02:00:00:00:10:02"
OTHER_MAC = "02:00:00:00:20:01"


def _deco(mac: str, *, master: bool = False) -> TpLinkDeco:
    """Make a Deco object with realistic device metadata."""
    device = TpLinkDeco(mac)
    device.update(
        {
            "role": "master" if master else "slave",
            "nickname": "test_node",
            "group_status": "connected",
            "inet_status": "online",
        }
    )
    return device


def _client(mac: str, *, deco_mac: str | None, online: bool | None) -> TpLinkDecoClient:
    """Build a known client without an external router connection."""
    client = TpLinkDecoClient(mac)
    client.deco_mac = deco_mac
    client.online = online
    return client


def _counts(add_entities: MagicMock) -> list[TplinkDecoClientCountSensor]:
    """Return all client-count entities registered by the sensor platform."""
    return [
        entity
        for call in add_entities.call_args_list
        for entity in call.args[0]
        if isinstance(entity, TplinkDecoClientCountSensor)
    ]


def _client_coordinator() -> tuple[TplinkDecoClientUpdateCoordinator, MagicMock]:
    """Make a real client coordinator with a mocked two-node mesh."""
    hass = MagicMock()
    master = _deco(MASTER_MAC, master=True)
    satellite = _deco(SATELLITE_MAC)
    deco_coordinator = MagicMock()
    deco_coordinator.paused = False
    deco_coordinator.data = TpLinkDecoData(
        master, {MASTER_MAC: master, SATELLITE_MAC: satellite}
    )
    coordinator = TplinkDecoClientUpdateCoordinator(
        hass=hass,
        api=MagicMock(),
        config_entry=MagicMock(),
        deco_update_coordinator=deco_coordinator,
        consider_home_seconds=300,
        data={},
    )
    return coordinator, deco_coordinator


@pytest.mark.asyncio
async def test_only_valid_per_node_responses_establish_count_readiness() -> None:
    """Keep an unpolled peer unverified through partial failures and backoff."""
    coordinator, deco_coordinator = _client_coordinator()

    assert coordinator.has_successful_refresh is False
    assert coordinator.successfully_polled_deco_macs == set()

    coordinator._async_clients_for_deco = AsyncMock(
        side_effect=[(None, False), (None, False)]
    )
    await coordinator._async_update_data()
    assert coordinator.has_successful_refresh is False
    assert coordinator.successfully_polled_deco_macs == set()

    # A valid empty response counts, even when the other Deco fails.
    coordinator._async_clients_for_deco = AsyncMock(
        side_effect=[([], False), (None, True)]
    )
    await coordinator._async_update_data()
    assert coordinator.has_successful_refresh is True
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC}

    # The 5xx backoff skips polling, not only updating the sensor.
    coordinator._async_clients_for_deco.reset_mock()
    await coordinator._async_update_data()
    coordinator._async_clients_for_deco.assert_not_awaited()
    assert coordinator.successfully_polled_deco_macs == {MASTER_MAC}

    # Simulate elapsed backoff, then a valid satellite recovery.
    coordinator._client_backoff_until = 0.0
    coordinator._async_clients_for_deco = AsyncMock(
        side_effect=[([], False), ([], False)]
    )
    await coordinator._async_update_data()
    assert coordinator.successfully_polled_deco_macs == {
        MASTER_MAC,
        SATELLITE_MAC,
    }
    assert coordinator.remaining_backoff_seconds == 0

    deco_coordinator.paused = True
    coordinator._async_clients_for_deco.reset_mock()
    await coordinator._async_update_data()
    coordinator._async_clients_for_deco.assert_not_awaited()


@pytest.mark.asyncio
async def test_deferred_count_entities_are_per_node_and_idempotent() -> None:
    """Avoid premature zeros and duplicate counts for late mesh nodes."""
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    client_coordinators: dict[str, MagicMock] = {}
    added_by_entry: dict[str, MagicMock] = {}

    with patch(
        "custom_components.tplink_deco.sensor.async_dispatcher_connect",
        return_value=MagicMock(),
    ):
        for entry_id, mac in (("mesh-one", MASTER_MAC), ("mesh-two", OTHER_MAC)):
            master = _deco(mac, master=True)
            deco_coordinator = MagicMock()
            deco_coordinator.data = TpLinkDecoData(master, {mac: master})
            client_coordinator = MagicMock()
            client_coordinator.data = {}
            client_coordinator.has_successful_refresh = False
            client_coordinator.successfully_polled_deco_macs = set()
            client_coordinators[entry_id] = client_coordinator
            hass.data[DOMAIN][entry_id] = {
                COORDINATOR_DECOS_KEY: deco_coordinator,
                COORDINATOR_CLIENTS_KEY: client_coordinator,
            }
            added_by_entry[entry_id] = MagicMock()
            await async_setup_entry(
                hass, SimpleNamespace(entry_id=entry_id), added_by_entry[entry_id]
            )

        assert not _counts(added_by_entry["mesh-one"])
        assert not _counts(added_by_entry["mesh-two"])

        first = client_coordinators["mesh-one"]
        first_listener = first.async_add_listener.call_args.args[0]
        first.has_successful_refresh = True

        # A successful poll of an unknown peer must not create its count.
        first_listener()
        assert not _counts(added_by_entry["mesh-one"])

        first.successfully_polled_deco_macs.add(MASTER_MAC)
        first_listener()
        assert [entity.unique_id for entity in _counts(added_by_entry["mesh-one"])] == [
            f"{MASTER_MAC}_client_count"
        ]
        assert not _counts(added_by_entry["mesh-two"])

        # A new satellite is visible before its first client-list response.
        satellite = _deco(SATELLITE_MAC)
        data = hass.data[DOMAIN]["mesh-one"][COORDINATOR_DECOS_KEY].data
        data.decos[SATELLITE_MAC] = satellite
        first_listener()
        assert len(_counts(added_by_entry["mesh-one"])) == 1

        first.successfully_polled_deco_macs.add(SATELLITE_MAC)
        first_listener()
        first_listener()
        assert [entity.unique_id for entity in _counts(added_by_entry["mesh-one"])] == [
            f"{MASTER_MAC}_client_count",
            f"{SATELLITE_MAC}_client_count",
        ]

        # A second config entry is completely independent.
        second = client_coordinators["mesh-two"]
        second.has_successful_refresh = True
        second.successfully_polled_deco_macs.add(OTHER_MAC)
        second.async_add_listener.call_args.args[0]()
        assert [entity.unique_id for entity in _counts(added_by_entry["mesh-two"])] == [
            f"{OTHER_MAC}_client_count"
        ]
        for client_coordinator in client_coordinators.values():
            client_coordinator.on_close.assert_called_once()


def test_connected_client_count_excludes_offline_historical_records() -> None:
    """Count truthy online states without dropping restored tracker records."""
    master = _deco(MASTER_MAC, master=True)
    deco_coordinator = MagicMock()
    deco_coordinator.data = TpLinkDecoData(master, {MASTER_MAC: master})
    client_coordinator = MagicMock()
    known_clients = {
        "online": _client("online", deco_mac=MASTER_MAC, online=True),
        "offline": _client("offline", deco_mac=MASTER_MAC, online=False),
        "unknown": _client("unknown", deco_mac=MASTER_MAC, online=None),
        "peer": _client("peer", deco_mac=SATELLITE_MAC, online=True),
        "unassigned": _client("unassigned", deco_mac=None, online=True),
    }
    client_coordinator.data = known_clients
    sensor = TplinkDecoClientCountSensor(
        coordinator_decos=deco_coordinator,
        coordinator_clients=client_coordinator,
        deco_mac=MASTER_MAC,
    )

    assert sensor.unique_id == f"{MASTER_MAC}_client_count"
    assert sensor.native_value == 1
    known_clients["offline"].online = True  # Existing consider_home grace period.
    sensor._update_state()
    assert sensor.native_value == 2
    known_clients["offline"].online = False
    known_clients["online"].online = False
    sensor._update_state()
    assert sensor.native_value == 0
    assert len(known_clients) == 5
