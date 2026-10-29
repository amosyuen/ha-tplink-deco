"""Tests for TP-Link Deco sensors."""

from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.sensor import TplinkTotalClientDataRateSensor


def _client(
    mac: str,
    deco_mac: str,
    *,
    online: bool,
    down: float,
    up: float,
) -> TpLinkDecoClient:
    client = TpLinkDecoClient(mac)
    client.deco_mac = deco_mac
    client.online = online
    client.down_kilobytes_per_s = down
    client.up_kilobytes_per_s = up
    return client


@pytest.mark.parametrize(
    "client_attribute,expected",
    [
        ("down_kilobytes_per_s", 12.0),
        ("up_kilobytes_per_s", 3.0),
    ],
)
def test_total_data_rate_excludes_offline_clients(client_attribute, expected):
    coordinator_clients = MagicMock()
    coordinator_clients.data = {
        "online": _client(
            "AA:BB:CC:DD:EE:01",
            "AA:BB:CC:DD:FF:01",
            online=True,
            down=12.0,
            up=3.0,
        ),
        "offline": _client(
            "AA:BB:CC:DD:EE:02",
            "AA:BB:CC:DD:FF:01",
            online=False,
            down=5186.0,
            up=24.0,
        ),
    }

    sensor = TplinkTotalClientDataRateSensor(
        MagicMock(),
        coordinator_clients,
        "Total",
        "total",
        client_attribute,
        None,
    )

    assert sensor.native_value == expected


def test_deco_data_rate_only_includes_online_clients_for_that_deco():
    selected_deco = TpLinkDeco("AA:BB:CC:DD:FF:01")
    coordinator_clients = MagicMock()
    coordinator_clients.data = {
        "selected": _client(
            "AA:BB:CC:DD:EE:01",
            selected_deco.mac,
            online=True,
            down=12.0,
            up=3.0,
        ),
        "other_deco": _client(
            "AA:BB:CC:DD:EE:02",
            "AA:BB:CC:DD:FF:02",
            online=True,
            down=50.0,
            up=8.0,
        ),
        "offline": _client(
            "AA:BB:CC:DD:EE:03",
            selected_deco.mac,
            online=False,
            down=5186.0,
            up=24.0,
        ),
    }

    sensor = TplinkTotalClientDataRateSensor(
        MagicMock(),
        coordinator_clients,
        "Selected Deco Down",
        "selected_deco_down",
        "down_kilobytes_per_s",
        selected_deco,
    )

    assert sensor.native_value == 12.0
