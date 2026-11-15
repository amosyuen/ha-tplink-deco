"""Regression tests for Deco nickname handling and stable device identifiers."""

from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.helpers.entity import DeviceInfo
import pytest

from custom_components.tplink_deco import device
from custom_components.tplink_deco.coordinator import TpLinkDeco

MAC = "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize(
    ("device_data", "expected"),
    [
        ({}, MAC),
        ({"nickname": None}, MAC),
        ({"nickname": ""}, MAC),
        ({"custom_nickname": ""}, MAC),
        ({"nickname": "living_room"}, "Living Room"),
        ({"custom_nickname": "Kitchen", "nickname": "living_room"}, "Kitchen"),
        ({"custom_nickname": "", "nickname": "living_room"}, "Living Room"),
        ({"custom_nickname": "<Error Decoding Kitchen>"}, "Kitchen"),
        ({"custom_nickname": "<Error Decoding >"}, MAC),
        (
            {"custom_nickname": "<Error Decoding >", "nickname": "living_room"},
            "Living Room",
        ),
        ({"nickname": "<Error Decoding >"}, MAC),
        ({"custom_nickname": "", "nickname": "<Error Decoding >"}, MAC),
    ],
)
def test_deco_uses_available_name_or_mac(
    device_data: dict[str, str | None], expected: str
) -> None:
    """Prefer the custom name, then firmware nickname, then stable MAC."""
    deco = TpLinkDeco(MAC)

    deco.update(device_data)

    assert deco.name == expected


@pytest.mark.parametrize("signal_level", [None, {}])
def test_null_signal_level_matches_missing_telemetry(
    signal_level: dict[str, int] | None,
) -> None:
    """Treat optional null signals as absent while keeping Deco identity."""
    deco = TpLinkDeco(MAC)
    deco.update({"signal_level": {"band2_4": 48, "band5": 62}})
    assert deco.signal_band2_4 == 48
    assert deco.signal_band5 == 62

    deco.update({"signal_level": signal_level})

    assert deco.mac == MAC
    assert deco.signal_band2_4 is None
    assert deco.signal_band5 is None


def test_device_info_without_nickname() -> None:
    """Keep the device registry identifier unchanged when the name is missing."""
    deco = TpLinkDeco(MAC)
    deco.update({})

    device_info = device.create_device_info(deco, None)

    assert device_info["name"] == f"{MAC} Deco"
    assert device_info["identifiers"] == {("tplink_deco", MAC)}


def test_device_identity_survives_nickname_changes() -> None:
    """Keep MAC-based registry identifiers stable across repeated updates."""
    deco = TpLinkDeco(MAC)
    name_updates = [
        ({"nickname": "living_room"}, "Living Room"),
        ({"custom_nickname": "Kitchen"}, "Kitchen"),
        ({"custom_nickname": ""}, MAC),
        ({}, MAC),
    ]

    for device_data, expected_name in name_updates:
        deco.update(device_data)
        device_info = device.create_device_info(deco, None)

        assert deco.mac == MAC
        assert device_info["identifiers"] == {("tplink_deco", MAC)}
        assert device_info["name"] == f"{expected_name} Deco"


def test_satellite_keeps_master_registry_link_when_name_is_missing() -> None:
    """Preserve the satellite-to-master device association on name fallback."""
    master = TpLinkDeco(MAC)
    master.update({"role": "master", "nickname": "living_room"})
    satellite = TpLinkDeco("11:22:33:44:55:66")
    satellite.update({"role": "slave"})

    coordinator = MagicMock()
    coordinator.config_entry.entry_id = "nickname-test"
    registry = MagicMock()
    registry.async_get_or_create.return_value.id = "master-registry-id"

    with patch.object(device.device_registry, "async_get", return_value=registry):
        device_info = device.create_device_info(satellite, master, coordinator)

    assert device_info["identifiers"] == {("tplink_deco", "11:22:33:44:55:66")}
    if "via_device_id" in DeviceInfo.__annotations__:
        assert device_info["via_device_id"] == "master-registry-id"
        registry.async_get_or_create.assert_called_once()
    else:
        assert device_info["via_device"] == ("tplink_deco", MAC)
        registry.async_get_or_create.assert_not_called()
    assert device_info["name"] == "11:22:33:44:55:66 Deco"
