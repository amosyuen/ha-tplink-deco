"""Tests for Deco nickname handling."""

from custom_components.tplink_deco.coordinator import TpLinkDeco

MAC = "AA:BB:CC:DD:EE:FF"


def test_update_without_nickname_keeps_name_none():
    deco = TpLinkDeco(MAC)

    deco.update({})

    assert deco.name is None


def test_update_formats_nickname():
    deco = TpLinkDeco(MAC)

    deco.update({"nickname": "living_room"})

    assert deco.name == "Living Room"


def test_update_prefers_custom_nickname():
    deco = TpLinkDeco(MAC)

    deco.update({"custom_nickname": "Kitchen", "nickname": "living_room"})

    assert deco.name == "Kitchen"
