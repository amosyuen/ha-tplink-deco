"""Regression tests for Deco nickname handling and stable device identifiers."""

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
    ],
)
def test_deco_uses_available_name_or_mac(
    device_data: dict[str, str | None], expected: str
) -> None:
    """Prefer the custom name, then firmware nickname, then stable MAC."""
    deco = TpLinkDeco(MAC)

    deco.update(device_data)

    assert deco.name == expected


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

    device_info = device.create_device_info(satellite, master)

    assert device_info["identifiers"] == {
        ("tplink_deco", "11:22:33:44:55:66")
    }
    assert device_info["via_device"] == ("tplink_deco", MAC)
    assert device_info["name"] == "11:22:33:44:55:66 Deco"
