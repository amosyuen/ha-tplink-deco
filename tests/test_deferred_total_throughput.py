"""Regression tests for network totals when a master Deco appears late."""

from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.sensor import TplinkCoordinatorHealthSensor
from custom_components.tplink_deco.sensor import TplinkTotalClientDataRateSensor
from custom_components.tplink_deco.sensor import async_setup_entry

MASTER_MAC = "AA:BB:CC:DD:EE:01"
SATELLITE_MAC = "AA:BB:CC:DD:EE:02"


def _deco(mac: str, *, master: bool = False) -> TpLinkDeco:
    """Build a test Deco with a stable MAC and explicit role."""
    deco = TpLinkDeco(mac)
    deco.update({"role": "master" if master else "slave", "nickname": "living_room"})
    return deco


async def _setup_sensors(
    *,
    entry_id: str,
    master: TpLinkDeco | None,
    decos: dict[str, TpLinkDeco],
) -> tuple[MagicMock, MagicMock, Callable[[], None], Callable[[], None]]:
    """Set up the real sensor platform and capture discovery/update callbacks."""
    coordinator_decos = MagicMock()
    coordinator_decos.data = TpLinkDecoData(master, decos)
    coordinator_clients = MagicMock()
    coordinator_clients.data = {}

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry_id: {
                COORDINATOR_DECOS_KEY: coordinator_decos,
                COORDINATOR_CLIENTS_KEY: coordinator_clients,
            }
        }
    }
    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    async_add_entities = MagicMock()

    with (
        patch(
            "custom_components.tplink_deco.sensor.async_dispatcher_connect",
            return_value=MagicMock(),
        ) as connect,
        patch(
            "custom_components.tplink_deco.sensor.entity_registry.async_get",
            return_value=MagicMock(
                async_get_entity_id=MagicMock(return_value=None)
            ),
        ),
    ):
        await async_setup_entry(hass, config_entry, async_add_entities)

    update_callback = coordinator_decos.async_add_listener.call_args.args[0]
    discovery_callback = connect.call_args.args[2]
    coordinator_decos.on_close.assert_any_call(
        coordinator_decos.async_add_listener.return_value
    )
    coordinator_decos.on_close.assert_any_call(connect.return_value)
    return coordinator_decos, async_add_entities, update_callback, discovery_callback


def _total_sensors(
    async_add_entities: MagicMock,
) -> list[TplinkTotalClientDataRateSensor]:
    """Collect only network-wide throughput sensors across platform additions."""
    return [
        entity
        for call in async_add_entities.call_args_list
        for entity in call.args[0]
        if isinstance(entity, TplinkTotalClientDataRateSensor)
        and entity.unique_id.endswith(("_total_down", "_total_up"))
    ]


@pytest.mark.asyncio
async def test_standalone_master_has_no_network_totals() -> None:
    """Keep per-node rates and master health without redundant mesh totals."""
    master = _deco(MASTER_MAC, master=True)
    coordinator, async_add, on_update, on_discovery = await _setup_sensors(
        entry_id="standalone_master",
        master=master,
        decos={MASTER_MAC: master},
    )

    assert _total_sensors(async_add) == []
    ids = [
        entity.unique_id for call in async_add.call_args_list for entity in call.args[0]
    ]
    assert {f"{MASTER_MAC}_down", f"{MASTER_MAC}_up"}.issubset(ids)
    assert len([uid for uid in ids if uid.endswith(("_down", "_up"))]) == 2
    assert (
        len(
            [
                entity
                for call in async_add.call_args_list
                for entity in call.args[0]
                if isinstance(entity, TplinkCoordinatorHealthSensor)
            ]
        )
        == 8
    )

    for _ in range(3):
        on_update()
        on_discovery()
    assert _total_sensors(async_add) == []
    assert coordinator.data.master_deco is master
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_standalone_master_adds_totals_after_satellite_discovery() -> None:
    """Create network totals only when a satellite joins an existing master."""
    master = _deco(MASTER_MAC, master=True)
    coordinator, async_add, on_update, on_discovery = await _setup_sensors(
        entry_id="late_satellite",
        master=master,
        decos={MASTER_MAC: master},
    )

    assert _total_sensors(async_add) == []
    satellite = _deco(SATELLITE_MAC)
    coordinator.data = TpLinkDecoData(
        master, {MASTER_MAC: master, SATELLITE_MAC: satellite}
    )
    on_discovery()
    on_update()
    on_discovery()
    on_update()

    assert {entity.unique_id for entity in _total_sensors(async_add)} == {
        f"{MASTER_MAC}_total_down",
        f"{MASTER_MAC}_total_up",
    }
    assert len(_total_sensors(async_add)) == 2
    assert (
        sum(
            isinstance(entity, TplinkCoordinatorHealthSensor)
            for call in async_add.call_args_list
            for entity in call.args[0]
        )
        == 8
    )


@pytest.mark.asyncio
async def test_offline_satellite_does_not_hide_known_mesh_totals() -> None:
    """Retained offline satellites count as part of an existing mesh."""
    master = _deco(MASTER_MAC, master=True)
    satellite = _deco(SATELLITE_MAC)
    satellite.online = False
    _, async_add, on_update, _ = await _setup_sensors(
        entry_id="offline_satellite",
        master=master,
        decos={MASTER_MAC: master, SATELLITE_MAC: satellite},
    )

    on_update()
    assert {entity.unique_id for entity in _total_sensors(async_add)} == {
        f"{MASTER_MAC}_total_down",
        f"{MASTER_MAC}_total_up",
    }
    assert len(_total_sensors(async_add)) == 2


@pytest.mark.asyncio
async def test_network_totals_created_once_when_master_known_at_setup() -> None:
    """Keep the existing master-based IDs and avoid duplicate totals on updates."""
    master = _deco(MASTER_MAC, master=True)
    coordinator, async_add, on_update, on_discovery = await _setup_sensors(
        entry_id="master_entry",
        master=master,
        decos={MASTER_MAC: master, SATELLITE_MAC: _deco(SATELLITE_MAC)},
    )

    totals = _total_sensors(async_add)
    assert {entity.unique_id for entity in totals} == {
        f"{MASTER_MAC}_total_down",
        f"{MASTER_MAC}_total_up",
    }
    assert {next(iter(entity.device_info["identifiers"])) for entity in totals} == {
        (DOMAIN, MASTER_MAC)
    }
    initial_entities = async_add.call_args_list[0].args[0]
    throughput_entities = [
        item
        for item in initial_entities
        if isinstance(item, TplinkTotalClientDataRateSensor)
    ]
    health_entities = [
        item
        for item in initial_entities
        if isinstance(item, TplinkCoordinatorHealthSensor)
    ]
    assert len(throughput_entities) == 2
    assert len(health_entities) == 8

    on_update()
    on_discovery()
    on_update()
    assert len(_total_sensors(async_add)) == 2
    assert coordinator.data.master_deco is master


@pytest.mark.asyncio
async def test_network_totals_added_after_master_discovered() -> None:
    """Defer network totals while keeping satellite sensors available."""
    satellite = _deco(SATELLITE_MAC)
    coordinator, async_add, on_update, on_discovery = await _setup_sensors(
        entry_id="satellite_entry",
        master=None,
        decos={SATELLITE_MAC: satellite},
    )

    assert _total_sensors(async_add) == []
    satellite_ids = {
        entity.unique_id for call in async_add.call_args_list for entity in call.args[0]
    }
    assert {f"{SATELLITE_MAC}_down", f"{SATELLITE_MAC}_up"}.issubset(satellite_ids)

    # The discovery signal is dispatched before the coordinator commits data.
    on_discovery()
    assert _total_sensors(async_add) == []

    master = _deco(MASTER_MAC, master=True)
    coordinator.data = TpLinkDecoData(
        master, {SATELLITE_MAC: satellite, MASTER_MAC: master}
    )
    on_update()
    on_update()
    on_discovery()

    assert {entity.unique_id for entity in _total_sensors(async_add)} == {
        f"{MASTER_MAC}_total_down",
        f"{MASTER_MAC}_total_up",
    }
    assert len(_total_sensors(async_add)) == 2


@pytest.mark.asyncio
async def test_no_master_keeps_totals_absent_across_updates() -> None:
    """Do not create network totals or raise when the master stays unknown."""
    coordinator, async_add, on_update, on_discovery = await _setup_sensors(
        entry_id="unknown_master", master=None, decos={}
    )
    assert async_add.call_count == 0

    for _ in range(3):
        on_update()
        on_discovery()

    assert _total_sensors(async_add) == []
    assert coordinator.data.master_deco is None


@pytest.mark.asyncio
async def test_network_totals_do_not_duplicate_after_master_disappears() -> None:
    """Avoid re-registering old IDs after a later temporary loss of master."""
    master = _deco(MASTER_MAC, master=True)
    satellite = _deco(SATELLITE_MAC)
    mesh = {MASTER_MAC: master, SATELLITE_MAC: satellite}
    coordinator, async_add, on_update, _ = await _setup_sensors(
        entry_id="flapping_master", master=master, decos=mesh
    )
    coordinator.data = TpLinkDecoData(None, mesh)
    on_update()
    coordinator.data = TpLinkDecoData(master, mesh)
    on_update()

    assert len(_total_sensors(async_add)) == 2


@pytest.mark.asyncio
async def test_totals_are_independent_between_config_entries() -> None:
    """One config entry cannot suppress totals for another Deco network."""
    first = _deco(MASTER_MAC, master=True)
    second_mac = "AA:BB:CC:DD:EE:03"
    second = _deco(second_mac, master=True)
    first_coord, first_added, first_update, _ = await _setup_sensors(
        entry_id="first",
        master=first,
        decos={MASTER_MAC: first, SATELLITE_MAC: _deco(SATELLITE_MAC)},
    )
    second_coord, second_added, second_update, _ = await _setup_sensors(
        entry_id="second", master=None, decos={}
    )
    second_coord.data = TpLinkDecoData(second, {second_mac: second})
    second_update()
    first_update()

    assert _total_sensors(second_added) == []
    assert {item.unique_id for item in _total_sensors(first_added)} == {
        f"{MASTER_MAC}_total_down",
        f"{MASTER_MAC}_total_up",
    }
    second_satellite_mac = "AA:BB:CC:DD:EE:04"
    second_coord.data = TpLinkDecoData(
        second,
        {
            second_mac: second,
            second_satellite_mac: _deco(second_satellite_mac),
        },
    )
    second_update()
    second_update()
    assert {item.unique_id for item in _total_sensors(second_added)} == {
        f"{second_mac}_total_down",
        f"{second_mac}_total_up",
    }
    assert len(_total_sensors(second_added)) == 2
    assert first_coord.data.master_deco is first
