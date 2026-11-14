"""Regression tests for Deco master/satellite device registry links."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from homeassistant.helpers.entity import DeviceInfo

from custom_components.tplink_deco import device as device_module
from custom_components.tplink_deco.binary_sensor import (
    TplinkDecoInternetOnlineBinarySensor,
)
from custom_components.tplink_deco.binary_sensor import TplinkDecoOnlineBinarySensor
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.device import create_device_info
from custom_components.tplink_deco.device_tracker import (
    TplinkDecoClientDeviceTracker,
)
from custom_components.tplink_deco.device_tracker import TplinkDecoDeviceTracker
from custom_components.tplink_deco.select import DecoPollingIntervalSelect
from custom_components.tplink_deco.sensor import DIAGNOSTIC_SENSOR_DESCRIPTIONS
from custom_components.tplink_deco.sensor import TplinkDecoClientCountSensor
from custom_components.tplink_deco.sensor import TplinkDecoDiagnosticSensor
from custom_components.tplink_deco.sensor import TplinkTotalClientDataRateSensor
from custom_components.tplink_deco.switch import DecoPollingSwitch

MASTER_MAC = "02:00:00:00:00:11"
SATELLITE_MAC = "02:00:00:00:00:12"
CLIENT_MAC = "02:00:00:00:00:13"
MASTER_DEVICE_ID = "registry-master"


class _ModernDeviceInfo(dict):
    """Simulate device information with via_device_id support."""

    __annotations__ = {"identifiers": set, "via_device_id": str}


class _LegacyDeviceInfo(dict):
    """Simulate Home Assistant 2025.12 device information."""

    __annotations__ = {"identifiers": set, "via_device": tuple}


def _mesh() -> tuple[TpLinkDeco, TpLinkDeco]:
    """Create master and satellite devices with stable MAC identities."""
    master = TpLinkDeco(MASTER_MAC)
    master.update({"role": "master", "nickname": "main"})
    satellite = TpLinkDeco(SATELLITE_MAC)
    satellite.update({"role": "slave", "nickname": "satellite"})
    return master, satellite


def _coordinator(
    master: TpLinkDeco | None,
    satellite: TpLinkDeco | None,
    entry_id: str = "mesh-entry",
) -> MagicMock:
    """Build a coordinator for one Home Assistant configuration entry."""
    coordinator = MagicMock()
    coordinator.config_entry.entry_id = entry_id
    decos = {}
    for deco in (master, satellite):
        if deco is not None:
            decos[deco.mac] = deco
    coordinator.data = TpLinkDecoData(master, decos)
    return coordinator


def _registry() -> MagicMock:
    """Provide a fake registry with a stable master registry ID."""
    registry = MagicMock()
    registry.async_get_or_create.return_value.id = MASTER_DEVICE_ID
    return registry


@pytest.mark.parametrize(
    ("info_class", "expected_field"),
    [(_ModernDeviceInfo, "via_device_id"), (_LegacyDeviceInfo, "via_device")],
)
def test_supported_parent_link(
    info_class: type[dict], expected_field: str
) -> None:
    """Use the modern registry ID or the supported legacy identifier."""
    master, satellite = _mesh()
    coordinator = _coordinator(master, satellite)
    registry = _registry()

    with (
        patch.object(device_module, "DeviceInfo", info_class),
        patch.object(
            device_module.device_registry, "async_get", return_value=registry
        ) as get_registry,
    ):
        info = create_device_info(satellite, master, coordinator)

    assert info["identifiers"] == {(DOMAIN, SATELLITE_MAC)}
    assert info["name"] == f"{satellite.name} Deco"
    if expected_field == "via_device_id":
        assert info["via_device_id"] == MASTER_DEVICE_ID
        assert "via_device" not in info
        get_registry.assert_called_once_with(coordinator.hass)
        registry.async_get_or_create.assert_called_once_with(
            config_entry_id="mesh-entry",
            identifiers={(DOMAIN, MASTER_MAC)},
            name=f"{master.name} Deco",
            manufacturer="TP-Link Deco",
            model=master.device_model,
            sw_version=master.sw_version,
            hw_version=master.hw_version,
        )
    else:
        assert info["via_device"] == (DOMAIN, MASTER_MAC)
        get_registry.assert_not_called()


@pytest.mark.parametrize("missing", ["deco", "master", "coordinator"])
def test_missing_context_skips_parent_link(missing: str) -> None:
    """Avoid inventing parent links when required context is unavailable."""
    master, satellite = _mesh()
    with (
        patch.object(device_module, "DeviceInfo", _ModernDeviceInfo),
        patch.object(device_module.device_registry, "async_get") as get_registry,
    ):
        info = create_device_info(
            None if missing == "deco" else satellite,
            None if missing == "master" else master,
            None
            if missing == "coordinator"
            else _coordinator(master, satellite),
        )

    if missing == "deco":
        assert info is None
    else:
        assert info["identifiers"] == {(DOMAIN, SATELLITE_MAC)}
        assert "via_device_id" not in info
    get_registry.assert_not_called()


def test_master_never_links_to_itself() -> None:
    """Preserve the master device without a self-reference."""
    master, satellite = _mesh()
    with (
        patch.object(device_module, "DeviceInfo", _ModernDeviceInfo),
        patch.object(device_module.device_registry, "async_get") as get_registry,
    ):
        info = create_device_info(master, master, _coordinator(master, satellite))

    assert info["identifiers"] == {(DOMAIN, MASTER_MAC)}
    assert "via_device_id" not in info
    get_registry.assert_not_called()


def test_device_registry_scopes_identical_macs_to_config_entries() -> None:
    """Resolve each config entry's master independently for the same MAC."""
    master, satellite = _mesh()
    registry = _registry()
    registry.async_get_or_create.side_effect = [
        MagicMock(id="parent-one"),
        MagicMock(id="parent-two"),
    ]
    with (
        patch.object(device_module, "DeviceInfo", _ModernDeviceInfo),
        patch.object(
            device_module.device_registry, "async_get", return_value=registry
        ),
    ):
        first = create_device_info(
            satellite, master, _coordinator(master, satellite, "first")
        )
        second = create_device_info(
            satellite, master, _coordinator(master, satellite, "second")
        )

    assert first["via_device_id"] == "parent-one"
    assert second["via_device_id"] == "parent-two"
    assert [
        call.kwargs["config_entry_id"]
        for call in registry.async_get_or_create.call_args_list
    ] == ["first", "second"]


def test_satellite_entities_keep_unique_ids_and_parent_links() -> None:
    """Exercise trackers, binary sensors and fork-specific diagnostic entities."""
    master, satellite = _mesh()
    coordinator = _coordinator(master, satellite)
    clients_coordinator = MagicMock()
    clients_coordinator.data = {}
    client = TpLinkDecoClient(CLIENT_MAC)
    client.deco_mac = SATELLITE_MAC
    client.name = "client"

    with (
        patch.object(device_module, "DeviceInfo", _ModernDeviceInfo),
        patch.object(
            device_module.device_registry, "async_get", return_value=_registry()
        ),
    ):
        entities = [
            TplinkDecoDeviceTracker(coordinator, satellite, "", "Deco"),
            TplinkDecoClientDeviceTracker(
                coordinator, clients_coordinator, client, "", ""
            ),
            TplinkDecoInternetOnlineBinarySensor(coordinator, SATELLITE_MAC),
            TplinkDecoOnlineBinarySensor(coordinator, SATELLITE_MAC),
            TplinkDecoClientCountSensor(
                coordinator, clients_coordinator, SATELLITE_MAC
            ),
            TplinkDecoDiagnosticSensor(
                coordinator, SATELLITE_MAC, DIAGNOSTIC_SENSOR_DESCRIPTIONS[0]
            ),
            TplinkTotalClientDataRateSensor(
                coordinator,
                clients_coordinator,
                "Satellite up",
                f"{SATELLITE_MAC}_up",
                "up_kilobytes_per_s",
                satellite,
            ),
        ]
        for entity in entities:
            info = entity.device_info
            assert info["identifiers"] == {(DOMAIN, SATELLITE_MAC)}
            assert info["via_device_id"] == MASTER_DEVICE_ID

    assert entities[0].mac_address == SATELLITE_MAC
    assert entities[1].mac_address == CLIENT_MAC
    assert entities[2].unique_id == f"{SATELLITE_MAC}_internet_online"
    assert entities[3].unique_id == f"{SATELLITE_MAC}_online"
    assert entities[4].unique_id == f"{SATELLITE_MAC}_client_count"
    assert entities[6].unique_id == f"{SATELLITE_MAC}_up"


def test_polling_entities_stay_on_master_device() -> None:
    """Preserve the master device and polling switch/select unique IDs."""
    master, satellite = _mesh()
    coordinator = _coordinator(master, satellite)
    config_entry = MagicMock()
    config_entry.entry_id = "mesh-entry"

    with (
        patch.object(device_module, "DeviceInfo", _ModernDeviceInfo),
        patch.object(device_module.device_registry, "async_get") as get_registry,
    ):
        polling_switch = DecoPollingSwitch(coordinator)
        polling_select = DecoPollingIntervalSelect(
            MagicMock(), config_entry, coordinator
        )
        for entity in (polling_switch, polling_select):
            info = entity.device_info
            assert info["identifiers"] == {(DOMAIN, MASTER_MAC)}
            assert "via_device_id" not in info

    assert polling_switch.unique_id == "tplink_deco_polling"
    assert polling_select.unique_id == "mesh-entry_polling_interval"
    get_registry.assert_not_called()


def test_real_device_info_uses_supported_field() -> None:
    """Exercise the installed DeviceInfo API in both CI matrix entries."""
    master, satellite = _mesh()
    coordinator = _coordinator(master, satellite)
    with patch.object(
        device_module.device_registry, "async_get", return_value=_registry()
    ) as get_registry:
        info = create_device_info(satellite, master, coordinator)

    assert info["identifiers"] == {(DOMAIN, SATELLITE_MAC)}
    if "via_device_id" in DeviceInfo.__annotations__:
        assert info["via_device_id"] == MASTER_DEVICE_ID
        get_registry.assert_called_once_with(coordinator.hass)
    else:
        assert info["via_device"] == (DOMAIN, MASTER_MAC)
        get_registry.assert_not_called()
