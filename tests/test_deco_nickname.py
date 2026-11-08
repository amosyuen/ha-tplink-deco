"""Tests for Deco nickname handling."""

from custom_components.tplink_deco import device
from custom_components.tplink_deco.coordinator import TpLinkDeco

MAC = "AA:BB:CC:DD:EE:FF"


def test_update_without_nickname_uses_mac():
    deco = TpLinkDeco(MAC)

    deco.update({})

    assert deco.name == MAC


def test_update_formats_nickname():
    deco = TpLinkDeco(MAC)

    deco.update({"nickname": "living_room"})

    assert deco.name == "Living Room"


def test_update_prefers_custom_nickname():
    deco = TpLinkDeco(MAC)

    deco.update({"custom_nickname": "Kitchen", "nickname": "living_room"})

    assert deco.name == "Kitchen"


def test_update_empty_custom_nickname_falls_back_to_nickname():
    deco = TpLinkDeco(MAC)

    deco.update({"custom_nickname": "", "nickname": "living_room"})

    assert deco.name == "Living Room"


def test_update_empty_custom_nickname_without_nickname_uses_mac():
    deco = TpLinkDeco(MAC)

    deco.update({"custom_nickname": ""})

    assert deco.name == MAC


def test_device_info_name_without_nickname():
    deco = TpLinkDeco(MAC)
    deco.update({})

    device_info = device.create_device_info(deco, None)

    assert device_info["name"] == f"{MAC} Deco"
