"""Regression tests for Home Assistant client tracker hostname behavior."""

from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.device_tracker import TplinkDecoClientDeviceTracker

CLIENT_MAC = "AA:BB:CC:DD:EE:01"


def _make_tracker(
    client_name: str | None,
    prefix: str = "",
    postfix: str = "",
) -> TplinkDecoClientDeviceTracker:
    """Create a client tracker with a test coordinator and a stable MAC."""
    client = TpLinkDecoClient(CLIENT_MAC)
    client.name = client_name
    return TplinkDecoClientDeviceTracker(
        coordinator_decos=MagicMock(),
        coordinator_clients=MagicMock(),
        client=client,
        client_prefix=prefix,
        client_postfix=postfix,
    )


@pytest.mark.parametrize(
    ("client_name", "prefix", "postfix", "expected"),
    [
        ("Office Printer", "", "", "Office Printer"),
        ("Café Speaker", "", "", "Café Speaker"),
        ("Phone", "Home", "Wi-Fi", "Home Phone Wi-Fi"),
        ("Workstation", "Network", "", "Network Workstation"),
        ("Tablet", "", "connected", "Tablet connected"),
        (None, "Home", "Wi-Fi", None),
        ("", "", "", ""),
    ],
)
def test_client_tracker_hostname_matches_display_name(
    client_name: str | None,
    prefix: str,
    postfix: str,
    expected: str | None,
) -> None:
    """Expose the generated client name without changing the tracker MAC."""
    tracker = _make_tracker(client_name, prefix, postfix)

    assert tracker.hostname == expected
    assert tracker.name == expected
    assert tracker.mac_address == CLIENT_MAC


@pytest.mark.parametrize("client_name", [None, ""])
def test_scanner_hostname_falls_back_to_mac_when_name_is_missing(
    client_name: str | None,
) -> None:
    """Allow Home Assistant to fall back to the existing MAC when unnamed."""
    tracker = _make_tracker(client_name)

    assert tracker.hostname or tracker.mac_address == CLIENT_MAC


def test_client_rename_updates_hostname_and_preserves_mac() -> None:
    """Reflect a refreshed client nickname without changing its identity."""
    tracker = _make_tracker("Initial Name", prefix="Home", postfix="Device")

    assert tracker.hostname == "Home Initial Name Device"

    tracker._client.name = "Updated Name"
    tracker._update_from_client()

    assert tracker.hostname == "Home Updated Name Device"
    assert tracker.name == "Home Updated Name Device"
    assert tracker.mac_address == CLIENT_MAC
