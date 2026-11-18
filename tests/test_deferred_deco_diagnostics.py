"""Regression tests for diagnostics which become available after Deco discovery."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.sensor import DIAGNOSTIC_SENSOR_DESCRIPTIONS
from custom_components.tplink_deco.sensor import TplinkDecoDiagnosticSensor
from custom_components.tplink_deco.sensor import async_setup_entry

MASTER_MAC = "02:00:00:00:60:01"
SATELLITE_MAC = "02:00:00:00:60:02"


def _sensor_ids(added: MagicMock) -> list[str]:
    """Collect every registered unique ID in registration order."""
    return [
        entity.unique_id for call in added.call_args_list for entity in call.args[0]
    ]


def _diagnostics(added: MagicMock) -> list[TplinkDecoDiagnosticSensor]:
    """Select actual Deco diagnostic entities from all platform additions."""
    return [
        entity
        for call in added.call_args_list
        for entity in call.args[0]
        if isinstance(entity, TplinkDecoDiagnosticSensor)
    ]


async def _setup_sensor_platform() -> tuple[TpLinkDeco, MagicMock, MagicMock]:
    """Configure real sensor setup with an initially incomplete Deco record."""
    master = TpLinkDeco(MASTER_MAC)
    master.name = "Main Deco"
    deco_coordinator = MagicMock()
    deco_coordinator.data = TpLinkDecoData(master, {MASTER_MAC: master})
    client_coordinator = MagicMock()
    client_coordinator.data = {}
    client_coordinator.has_successful_refresh = False
    added = MagicMock()
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "mesh-one": {
                COORDINATOR_DECOS_KEY: deco_coordinator,
                COORDINATOR_CLIENTS_KEY: client_coordinator,
            }
        }
    }
    with patch(
        "custom_components.tplink_deco.sensor.async_dispatcher_connect",
        return_value=MagicMock(),
    ):
        await async_setup_entry(hass, SimpleNamespace(entry_id="mesh-one"), added)
    return master, deco_coordinator, added


@pytest.mark.asyncio
async def test_late_diagnostic_values_register_once_without_placeholder_entities() -> (
    None
):
    """Publish optional metrics on later polls, retaining their original IDs."""
    master, coordinator, added = await _setup_sensor_platform()
    callback = coordinator.async_add_listener.call_args_list[0].args[0]

    assert callback.__name__ == "_add_untracked_deco_sensors"
    assert _diagnostics(added) == []
    assert {
        f"{MASTER_MAC}_down",
        f"{MASTER_MAC}_up",
        f"{MASTER_MAC}_total_down",
        f"{MASTER_MAC}_total_up",
    }.issubset(_sensor_ids(added))

    master.ip_address = "192.0.2.10"
    master.cpu_usage = 0
    callback()
    sensors = {entity.entity_description.key: entity for entity in _diagnostics(added)}

    assert set(sensors) == {"ip_address", "cpu_usage"}
    assert sensors["ip_address"].unique_id == f"{MASTER_MAC}_ip_address"
    assert sensors["cpu_usage"].unique_id == f"{MASTER_MAC}_cpu_usage"
    assert sensors["cpu_usage"].native_value == 0
    assert all(
        entity.entity_description.entity_registry_enabled_default is False
        for entity in sensors.values()
    )

    master.ip_address = None
    master.cpu_usage = None
    callback()
    assert sensors["ip_address"].native_value is None
    assert len(_diagnostics(added)) == 2

    master.bssid_band2_4 = "02:00:00:00:60:11"
    callback()
    callback()
    keys = [entity.entity_description.key for entity in _diagnostics(added)]
    assert keys == ["ip_address", "cpu_usage", "bssid_2_4ghz"]
    assert len(_sensor_ids(added)) == len(set(_sensor_ids(added)))
    assert all(
        key in {item.key for item in DIAGNOSTIC_SENSOR_DESCRIPTIONS} for key in keys
    )


@pytest.mark.asyncio
async def test_delayed_satellite_discovery_keeps_per_node_ids_and_no_duplicates() -> (
    None
):
    """Handle a newly committed node and its subsequent optional fields."""
    master, coordinator, added = await _setup_sensor_platform()
    callback = coordinator.async_add_listener.call_args_list[0].args[0]

    satellite = TpLinkDeco(SATELLITE_MAC)
    satellite.name = "Satellite"
    satellite.backhaul_speed = 100.0
    coordinator.data.decos[SATELLITE_MAC] = satellite
    callback()
    callback()

    ids = _sensor_ids(added)
    assert f"{SATELLITE_MAC}_down" in ids
    assert f"{SATELLITE_MAC}_up" in ids
    assert f"{SATELLITE_MAC}_backhaul_speed" in ids
    assert f"{MASTER_MAC}_backhaul_speed" not in ids
    assert ids.count(f"{SATELLITE_MAC}_backhaul_speed") == 1

    satellite.mem_usage = 42.0
    master.mem_usage = 24.0
    callback()
    callback()

    ids = _sensor_ids(added)
    assert f"{SATELLITE_MAC}_mem_usage" in ids
    assert f"{MASTER_MAC}_mem_usage" in ids
    assert len(ids) == len(set(ids))
    assert len([value for value in ids if value.endswith("_total_down")]) == 1
    assert len([value for value in ids if value.endswith("_total_up")]) == 1


@pytest.mark.parametrize(
    "reported_value",
    [None, "", "  ", True, False, 123, {"unexpected": "object"}],
)
def test_device_type_ignores_missing_or_malformed_firmware_values(
    reported_value: object,
) -> None:
    """Avoid exposing malformed values as a Home Assistant sensor state."""
    deco = TpLinkDeco(MASTER_MAC)
    deco.update({"device_type": reported_value})

    assert deco.device_type is None


@pytest.mark.asyncio
async def test_extra_device_type_sensor_keeps_identity_and_late_discovery() -> None:
    """Restore the extra-branch sensor without changing tracker identifiers."""
    master, coordinator, added = await _setup_sensor_platform()
    callback = coordinator.async_add_listener.call_args_list[0].args[0]

    assert master.device_type is None
    assert all(
        entity.entity_description.key != "device_type" for entity in _diagnostics(added)
    )

    master.update({"role": "master", "nickname": "Main", "device_type": "router"})
    callback()

    sensors = [
        entity
        for entity in _diagnostics(added)
        if entity.entity_description.key == "device_type"
    ]
    assert len(sensors) == 1
    device_type_sensor = sensors[0]
    assert device_type_sensor.unique_id == f"{MASTER_MAC}_device_type"
    assert device_type_sensor.entity_description.name == "Device Type"
    assert (
        device_type_sensor.entity_description.entity_registry_enabled_default is False
    )
    assert device_type_sensor.native_value == "router"

    master.update({"role": "master", "nickname": "Main", "device_type": "mesh"})
    callback()
    assert device_type_sensor.native_value == "mesh"

    satellite = TpLinkDeco(SATELLITE_MAC)
    satellite.update({"role": "slave", "nickname": "Other", "device_type": "satellite"})
    coordinator.data.decos[SATELLITE_MAC] = satellite
    callback()
    callback()
    ids = _sensor_ids(added)
    assert ids.count(f"{MASTER_MAC}_device_type") == 1
    assert ids.count(f"{SATELLITE_MAC}_device_type") == 1
    assert len(ids) == len(set(ids))

    master.update({"role": "master", "nickname": "Main"})
    assert device_type_sensor.native_value is None
    callback()
    assert _sensor_ids(added).count(f"{MASTER_MAC}_device_type") == 1
