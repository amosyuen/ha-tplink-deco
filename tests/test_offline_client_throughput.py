"""Regression tests for connected-client throughput aggregation."""

from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.sensor import TplinkTotalClientDataRateSensor

MASTER_MAC = "AA:BB:CC:DD:EE:01"
SATELLITE_MAC = "AA:BB:CC:DD:EE:02"


def _client(
    mac: str,
    deco_mac: str | None,
    *,
    online: bool | None,
    down: float,
    up: float,
) -> TpLinkDecoClient:
    """Create a synthetic client with explicit online status and data rates."""
    client = TpLinkDecoClient(mac)
    client.deco_mac = deco_mac
    client.online = online
    client.down_kilobytes_per_s = down
    client.up_kilobytes_per_s = up
    return client


def _sensor(
    clients: dict[str, TpLinkDecoClient],
    attribute: str,
    deco: TpLinkDeco | None,
) -> TplinkTotalClientDataRateSensor:
    """Build an actual throughput sensor with mocked coordinators."""
    coordinator_clients = MagicMock()
    coordinator_clients.data = clients
    return TplinkTotalClientDataRateSensor(
        coordinator_decos=MagicMock(),
        coordinator_clients=coordinator_clients,
        name="Total Down" if attribute.startswith("down") else "Total Up",
        unique_id=(
            "test_total_down" if attribute.startswith("down") else "test_total_up"
        ),
        client_attribute=attribute,
        deco=deco,
    )


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("down_kilobytes_per_s", 17.0),
        ("up_kilobytes_per_s", 4.0),
    ],
)
def test_network_total_excludes_offline_clients(
    attribute: str, expected: float
) -> None:
    """Exclude offline and unknown-status clients despite stale transfer rates."""
    clients = {
        "online": _client(
            "00:00:00:00:00:01", MASTER_MAC, online=True, down=12.0, up=3.0
        ),
        "other_online": _client(
            "00:00:00:00:00:04", SATELLITE_MAC, online=True, down=5.0, up=1.0
        ),
        "offline": _client(
            "00:00:00:00:00:02", MASTER_MAC, online=False, down=5186.0, up=24.0
        ),
        "unknown": _client(
            "00:00:00:00:00:03", SATELLITE_MAC, online=None, down=200.0, up=50.0
        ),
    }

    sensor = _sensor(clients, attribute, None)

    assert sensor.native_value == pytest.approx(expected)
    expected_id = "test_total_down" if attribute.startswith("down") else "test_total_up"
    assert sensor.unique_id == expected_id


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("down_kilobytes_per_s", 12.0),
        ("up_kilobytes_per_s", 3.0),
    ],
)
def test_per_deco_total_excludes_offline_and_other_deco_clients(
    attribute: str, expected: float
) -> None:
    """Sum only online clients associated with the selected Deco node."""
    deco = TpLinkDeco(MASTER_MAC)
    clients = {
        "selected": _client(
            "00:00:00:00:00:01", MASTER_MAC, online=True, down=12.0, up=3.0
        ),
        "other_deco": _client(
            "00:00:00:00:00:02", SATELLITE_MAC, online=True, down=50.0, up=8.0
        ),
        "offline": _client(
            "00:00:00:00:00:03", MASTER_MAC, online=False, down=5186.0, up=24.0
        ),
    }

    sensor = _sensor(clients, attribute, deco)

    assert sensor.native_value == pytest.approx(expected)


@pytest.mark.parametrize("attribute", ["down_kilobytes_per_s", "up_kilobytes_per_s"])
def test_throughput_recalculates_on_client_status_change(attribute: str) -> None:
    """Drop stale rates after a connected client becomes offline."""
    client = _client(
        "00:00:00:00:00:01", MASTER_MAC, online=True, down=12.0, up=3.0
    )
    sensor = _sensor({"client": client}, attribute, None)

    assert sensor.native_value == pytest.approx(getattr(client, attribute))

    client.online = False
    sensor._update_state()
    assert sensor.native_value == pytest.approx(0.0)

    client.online = True
    sensor._update_state()
    assert sensor.native_value == pytest.approx(getattr(client, attribute))


def test_empty_and_offline_only_network_total_is_zero() -> None:
    """Avoid phantom data rates when the tracked clients are all offline."""
    empty_sensor = _sensor({}, "down_kilobytes_per_s", None)
    offline_sensor = _sensor(
        {
            "offline": _client(
                "00:00:00:00:00:01",
                MASTER_MAC,
                online=False,
                down=512.0,
                up=1.0,
            )
        },
        "down_kilobytes_per_s",
        None,
    )

    assert empty_sensor.native_value == pytest.approx(0.0)
    assert offline_sensor.native_value == pytest.approx(0.0)
