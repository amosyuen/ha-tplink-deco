"""Tests for device-registry identifier handling (reboot_deco service)."""

from custom_components.tplink_deco import deco_mac_from_identifiers
from custom_components.tplink_deco.const import DOMAIN

MAC = "AA:BB:CC:DD:EE:FF"


def test_single_deco_identifier_returns_mac():
    assert deco_mac_from_identifiers({(DOMAIN, MAC)}) == MAC


def test_deco_identifier_among_others_returns_mac():
    # Devices can carry extra identifiers (e.g. after a rename or an
    # integration overlap); the Deco MAC must still be found.
    identifiers = {("other_integration", "xyz"), (DOMAIN, MAC)}
    assert deco_mac_from_identifiers(identifiers) == MAC


def test_no_deco_identifier_returns_none():
    assert deco_mac_from_identifiers({("other_integration", "xyz")}) is None
    assert deco_mac_from_identifiers(set()) is None
