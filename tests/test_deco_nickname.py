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
