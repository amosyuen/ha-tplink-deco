"""Regression tests for legacy Deco firmware numeric telemetry fields."""

from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator
from custom_components.tplink_deco.coordinator import _coerce_finite_float
from custom_components.tplink_deco.coordinator import bytes_to_bits
from custom_components.tplink_deco.sensor import TplinkTotalClientDataRateSensor

MASTER_MAC = "02:00:00:00:00:11"
CLIENT_MAC = "02:00:00:00:00:12"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.25", 0.25),
        (" 2.5 ", 2.5),
        ("0", 0.0),
        (0, 0.0),
        (2.5, 2.5),
        (None, None),
        ("invalid", None),
        ("NaN", None),
        ("inf", None),
        ("-Infinity", None),
        (float("nan"), None),
        (float("inf"), None),
        (True, None),
        ([], None),
        (10**1000, None),
    ],
)
def test_legacy_finite_float_parsing(value: object, expected: float | None) -> None:
    """Accept finite numeric JSON values, rejecting malformed measurements."""
    assert _coerce_finite_float(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("80", 10.0),
        (80, 10.0),
        ("0", 0.0),
        (0, 0.0),
        (None, None),
        ("not-a-number", None),
        ("NaN", None),
        ("Infinity", None),
        (False, None),
    ],
)
def test_legacy_client_rate_conversion(value: object, expected: float | None) -> None:
    """Retain the existing rate units and support legacy string values."""
    assert bytes_to_bits(value) == expected


def test_legacy_client_update_preserves_identifiers_and_state() -> None:
    """Decode numeric string rates without changing established client IDs."""
    client = TpLinkDecoClient(CLIENT_MAC)
    timestamp = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    client.update(
        {
            "name": "Private Test Client",
            "online": True,
            "down_speed": "80",
            "up_speed": "0",
        },
        MASTER_MAC,
        timestamp,
    )

    assert client.mac == CLIENT_MAC
    assert client.deco_mac == MASTER_MAC
    assert client.online is True
    assert client.last_activity == timestamp
    assert client.down_kilobytes_per_s == 10.0
    assert client.up_kilobytes_per_s == 0.0

    client.update(
        {"down_speed": "invalid", "up_speed": "NaN", "online": False},
        MASTER_MAC,
        timestamp,
    )
    assert client.down_kilobytes_per_s == 0.0
    assert client.up_kilobytes_per_s == 0.0
    assert client.online is False


def test_invalid_online_client_rate_keeps_network_totals_numeric() -> None:
    """Invalid firmware rates cannot break existing throughput aggregation."""
    timestamp = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    broken_client = TpLinkDecoClient(CLIENT_MAC)
    broken_client.update(
        {"online": True, "down_speed": "NaN", "up_speed": None},
        MASTER_MAC,
        timestamp,
    )
    healthy_client = TpLinkDecoClient("02:00:00:00:00:13")
    healthy_client.update(
        {"online": True, "down_speed": "80", "up_speed": "40"},
        MASTER_MAC,
        timestamp,
    )
    client_coordinator = MagicMock()
    client_coordinator.data = {
        broken_client.mac: broken_client,
        healthy_client.mac: healthy_client,
    }

    for attr_name, expected in (
        ("down_kilobytes_per_s", 10.0),
        ("up_kilobytes_per_s", 5.0),
    ):
        sensor = TplinkTotalClientDataRateSensor(
            coordinator_decos=MagicMock(),
            coordinator_clients=client_coordinator,
            name="Network rate",
            unique_id=f"test_{attr_name}",
            client_attribute=attr_name,
            deco=None,
        )
        assert sensor.native_value == expected


@pytest.mark.asyncio
async def test_legacy_master_performance_ignores_invalid_numeric_values() -> None:
    """Keep old CPU/memory samples and smoothing across malformed responses."""
    master = TpLinkDeco(MASTER_MAC)
    master.update(
        {
            "mac": MASTER_MAC,
            "role": "master",
            "group_status": "connected",
            "inet_status": "online",
        }
    )
    api = MagicMock()
    api.async_list_devices = AsyncMock(
        return_value=[
            {
                "mac": MASTER_MAC,
                "role": "master",
                "group_status": "connected",
                "inet_status": "online",
            }
        ]
    )
    api.async_get_performance = AsyncMock(
        side_effect=[
            {"result": {"cpu_usage": "0.25", "mem_usage": "0.5"}},
            {"result": {"cpu_usage": "NaN", "mem_usage": "invalid"}},
            {"result": {"cpu_usage": "0.5", "mem_usage": "0.25"}},
            {"result": {"cpu_usage": "0", "mem_usage": "0"}},
        ]
    )
    coordinator = TplinkDecoUpdateCoordinator(
        hass=MagicMock(),
        api=api,
        config_entry=MagicMock(),
        data=TpLinkDecoData(master, {MASTER_MAC: master}),
    )

    first = await coordinator._async_update_data()
    assert first.master_deco is master
    assert master.cpu_usage_raw == 25.0
    assert master.mem_usage_raw == 50.0
    assert master.cpu_usage == 25.0
    assert master.mem_usage == 50.0

    await coordinator._async_update_data()
    assert master.cpu_usage_raw == 25.0
    assert master.mem_usage_raw == 50.0
    assert master.cpu_usage == 25.0
    assert master.mem_usage == 50.0

    await coordinator._async_update_data()
    assert master.cpu_usage_raw == 50.0
    assert master.mem_usage_raw == 25.0
    assert master.cpu_usage == 32.5
    assert master.mem_usage == 42.5

    await coordinator._async_update_data()
    assert master.cpu_usage_raw == 0.0
    assert master.mem_usage_raw == 0.0
    assert master.cpu_usage == 22.8
    assert master.mem_usage == 29.7
    assert coordinator.data.master_deco is master
    assert api.async_list_devices.await_count == 4
    assert api.async_get_performance.await_count == 4
