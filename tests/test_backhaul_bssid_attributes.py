"""Regression tests for optional TP-Link Deco wireless backhaul BSSIDs."""

from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.const import ATTR_BACKHAUL_BSSID_BAND2_4
from custom_components.tplink_deco.const import ATTR_BACKHAUL_BSSID_BAND5
from custom_components.tplink_deco.const import ATTR_BSSID_BAND2_4
from custom_components.tplink_deco.const import ATTR_BSSID_BAND5
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.device_tracker import TplinkDecoDeviceTracker

DECO_MAC = "02:00:00:00:00:01"
BACKHAUL_2G = "02:00:00:00:00:02"
BACKHAUL_5G = "02:00:00:00:00:03"
ACCESS_POINT_2G = "02:00:00:00:00:04"
ACCESS_POINT_5G = "02:00:00:00:00:05"


def _tracker(deco: TpLinkDeco) -> TplinkDecoDeviceTracker:
    """Create a real Deco tracker with a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data.master_deco = None
    return TplinkDecoDeviceTracker(coordinator, deco, "", "Deco")


@pytest.mark.parametrize(
    ("payload", "expected_2g", "expected_5g"),
    [
        ({}, None, None),
        ({"bssid_sta_2g": BACKHAUL_2G}, BACKHAUL_2G, None),
        ({"bssid_sta_5g": BACKHAUL_5G}, None, BACKHAUL_5G),
        (
            {"bssid_sta_2g": BACKHAUL_2G, "bssid_sta_5g": BACKHAUL_5G},
            BACKHAUL_2G,
            BACKHAUL_5G,
        ),
        ({"bssid_sta_2g": None, "bssid_sta_5g": None}, None, None),
    ],
)
def test_coordinator_retains_optional_backhaul_bssids(
    payload: dict[str, str | None],
    expected_2g: str | None,
    expected_5g: str | None,
) -> None:
    """Read the optional wireless backhaul identifiers from firmware data."""
    deco = TpLinkDeco(DECO_MAC)

    assert deco.backhaul_bssid_band2_4 is None
    assert deco.backhaul_bssid_band5 is None

    deco.update(payload)

    assert deco.backhaul_bssid_band2_4 == expected_2g
    assert deco.backhaul_bssid_band5 == expected_5g
    assert deco.mac == DECO_MAC


@pytest.mark.parametrize("role", ["master", "slave"])
def test_deco_tracker_exposes_backhaul_separately_from_ap_bssids(role: str) -> None:
    """Expose both backhaul and existing access-point BSSID attributes."""
    deco = TpLinkDeco(DECO_MAC)
    deco.update(
        {
            "role": role,
            "bssid_2g": ACCESS_POINT_2G,
            "bssid_5g": ACCESS_POINT_5G,
            "bssid_sta_2g": BACKHAUL_2G,
            "bssid_sta_5g": BACKHAUL_5G,
        }
    )
    tracker = _tracker(deco)
    attributes = tracker.extra_state_attributes

    assert attributes[ATTR_BSSID_BAND2_4] == ACCESS_POINT_2G
    assert attributes[ATTR_BSSID_BAND5] == ACCESS_POINT_5G
    assert attributes[ATTR_BACKHAUL_BSSID_BAND2_4] == BACKHAUL_2G
    assert attributes[ATTR_BACKHAUL_BSSID_BAND5] == BACKHAUL_5G
    assert tracker.mac_address == DECO_MAC
    assert tracker.device_info["identifiers"] == {("tplink_deco", DECO_MAC)}


def test_missing_backhaul_fields_remain_none_on_tracker() -> None:
    """Keep unsupported firmware safe and retain existing AP BSSID fields."""
    deco = TpLinkDeco(DECO_MAC)
    deco.update({"bssid_2g": ACCESS_POINT_2G, "bssid_5g": ACCESS_POINT_5G})
    attributes = _tracker(deco).extra_state_attributes

    assert attributes[ATTR_BACKHAUL_BSSID_BAND2_4] is None
    assert attributes[ATTR_BACKHAUL_BSSID_BAND5] is None
    assert attributes[ATTR_BSSID_BAND2_4] == ACCESS_POINT_2G
    assert attributes[ATTR_BSSID_BAND5] == ACCESS_POINT_5G


def test_backhaul_attributes_refresh_and_clear_when_missing() -> None:
    """Replace obsolete backhaul data on a subsequent firmware refresh."""
    deco = TpLinkDeco(DECO_MAC)
    deco.update({"bssid_sta_2g": BACKHAUL_2G, "bssid_sta_5g": BACKHAUL_5G})
    tracker = _tracker(deco)

    assert tracker.extra_state_attributes[ATTR_BACKHAUL_BSSID_BAND5] == BACKHAUL_5G

    deco.update({"bssid_sta_2g": BACKHAUL_2G})
    attributes = tracker.extra_state_attributes

    assert attributes[ATTR_BACKHAUL_BSSID_BAND2_4] == BACKHAUL_2G
    assert attributes[ATTR_BACKHAUL_BSSID_BAND5] is None
