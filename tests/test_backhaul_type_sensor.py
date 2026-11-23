"""Regressions for complete Deco backhaul connection types."""

from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.const import ATTR_CONNECTION_TYPE
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.device_tracker import TplinkDecoDeviceTracker
from custom_components.tplink_deco.sensor import DIAGNOSTIC_SENSOR_DESCRIPTIONS
from custom_components.tplink_deco.sensor import TplinkDecoDiagnosticSensor

MASTER_MAC = "02:00:00:00:71:01"
SATELLITE_MAC = "02:00:00:00:71:02"


def _sensor(
    connection_type: object,
    *,
    role: str = "slave",
) -> tuple[TpLinkDeco, TplinkDecoDiagnosticSensor, MagicMock]:
    """Create the existing diagnostic entity from anonymous firmware data."""
    master = TpLinkDeco(MASTER_MAC)
    master.update({"role": "master", "group_status": "connected"})
    deco = master if role == "master" else TpLinkDeco(SATELLITE_MAC)
    deco.update(
        {
            "role": role,
            "group_status": "connected",
            "connection_type": connection_type,
        }
    )
    coordinator = MagicMock()
    coordinator.config_entry = None
    coordinator.last_update_success = True
    coordinator.data = TpLinkDecoData(
        master_deco=master,
        decos={master.mac: master, deco.mac: deco},
    )
    description = next(
        description
        for description in DIAGNOSTIC_SENSOR_DESCRIPTIONS
        if description.key == "connection_type"
    )
    sensor = TplinkDecoDiagnosticSensor(
        coordinator_decos=coordinator,
        deco_mac=deco.mac,
        description=description,
    )
    return deco, sensor, coordinator


@pytest.mark.parametrize("role", ["master", "slave"])
@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        (["band2_4", "band5"], "band2_4, band5"),
        (["band5", "band2_4"], "band5, band2_4"),
        (["band2_4"], "band2_4"),
        (["band5"], "band5"),
        ("band2_4", "band2_4"),
        ("wired", "wired"),
        (None, None),
        ([], None),
        ("", None),
        ("  ", None),
        (["band2_4", ""], None),
        (["band2_4", None], None),
        (["band2_4", True], None),
        ({"band2_4": True}, None),
        (42, None),
    ],
)
def test_backhaul_type_preserves_all_bands_and_rejects_invalid_values(
    role: str, reported: object, expected: str | None
) -> None:
    """Keep the MAC-based entity while converting firmware lists to strings."""
    deco, sensor, _ = _sensor(reported, role=role)

    assert sensor.native_value == expected
    assert sensor.unique_id == f"{deco.mac}_connection_type"
    assert sensor.entity_description.key == "connection_type"
    assert sensor.entity_description.entity_registry_enabled_default is False
    assert sensor.device_info["identifiers"] == {(DOMAIN, deco.mac)}


def test_backhaul_band_updates_keep_sensor_and_tracker_identity() -> None:
    """Refresh bands without losing the original tracker list or unique IDs."""
    deco, sensor, coordinator = _sensor(["band2_4", "band5"])
    tracker = TplinkDecoDeviceTracker(coordinator, deco, "", "Deco")

    assert sensor.native_value == "band2_4, band5"
    assert tracker.extra_state_attributes[ATTR_CONNECTION_TYPE] == [
        "band2_4",
        "band5",
    ]
    original_unique_id = sensor.unique_id
    original_sensor = sensor

    deco.update({"group_status": "connected", "connection_type": ["band5"]})
    tracker._update_from_deco()
    assert sensor.native_value == "band5"
    assert tracker.extra_state_attributes[ATTR_CONNECTION_TYPE] == ["band5"]

    deco.update({"group_status": "connected"})
    tracker._update_from_deco()
    assert sensor.native_value is None
    assert sensor.unique_id == original_unique_id
    assert sensor is original_sensor

    deco.update({"group_status": "connected", "connection_type": ["band2_4", "band5"]})
    tracker._update_from_deco()
    assert sensor.native_value == "band2_4, band5"
    assert sensor.unique_id == original_unique_id
    assert tracker.mac_address == SATELLITE_MAC
