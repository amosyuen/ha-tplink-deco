"""Regression coverage for Deco entities discovered after entry setup."""

from collections import defaultdict
from collections.abc import Callable
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco import binary_sensor
from custom_components.tplink_deco import device_tracker
from custom_components.tplink_deco import sensor
from custom_components.tplink_deco.const import CONF_CLIENT_POSTFIX
from custom_components.tplink_deco.const import CONF_CLIENT_PREFIX
from custom_components.tplink_deco.const import CONF_DECO_POSTFIX
from custom_components.tplink_deco.const import CONF_DECO_PREFIX
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SIGNAL_DECO_ADDED
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator

MASTER_MAC = "AA:BB:CC:DD:EE:01"
SATELLITE_MAC = "AA:BB:CC:DD:EE:02"


def _payload(mac: str, *, master: bool = False) -> dict[str, str]:
    """Build a valid synthetic Deco device-list entry."""
    return {
        "mac": mac,
        "nickname": "living_room",
        "role": "master" if master else "slave",
        "group_status": "connected",
        "inet_status": "online",
        "device_ip": "192.0.2.10",
    }


def _coordinator(
    hass: MagicMock,
    initial: TpLinkDecoData,
) -> tuple[TplinkDecoUpdateCoordinator, MagicMock]:
    """Construct an independently owned coordinator with a mocked API."""
    api = MagicMock()
    api.async_list_devices = AsyncMock()
    api.async_get_performance = AsyncMock(return_value={"result": {}})
    coordinator = TplinkDecoUpdateCoordinator(
        hass=hass,
        api=api,
        config_entry=MagicMock(),
        data=initial,
    )
    return coordinator, api


def _unique_ids(add_entities: MagicMock) -> list[str]:
    """Collect every entity unique ID registered by a platform."""
    return [
        entity.unique_id
        for call in add_entities.call_args_list
        for entity in call.args[0]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("late_master", [False, True])
async def test_new_node_is_committed_before_discovery_notification(
    late_master: bool,
) -> None:
    """Make the complete new inventory visible to synchronous listeners."""
    hass = MagicMock()
    existing_master = TpLinkDeco(MASTER_MAC)
    existing_master.update(_payload(MASTER_MAC, master=True))
    initial = (
        TpLinkDecoData()
        if late_master
        else TpLinkDecoData(existing_master, {MASTER_MAC: existing_master})
    )
    coordinator, api = _coordinator(hass, initial)
    expected_mac = MASTER_MAC if late_master else SATELLITE_MAC
    devices = [_payload(MASTER_MAC, master=True)]
    if not late_master:
        devices.append(_payload(SATELLITE_MAC))
    api.async_list_devices.return_value = devices

    observed: list[tuple[set[str], str | None]] = []

    def _capture(target_hass: MagicMock, signal: str) -> None:
        """Read the published coordinator snapshot during notification."""
        assert target_hass is hass
        assert signal == SIGNAL_DECO_ADDED
        data = coordinator.data
        observed.append(
            (set(data.decos), data.master_deco.mac if data.master_deco else None)
        )
        assert expected_mac in data.decos

    with patch(
        "custom_components.tplink_deco.coordinator.async_dispatcher_send",
        side_effect=_capture,
    ) as dispatch:
        result = await coordinator._async_update_data()
        assert result is coordinator.data
        repeated = await coordinator._async_update_data()

    assert repeated is coordinator.data
    assert observed == [(set(node["mac"] for node in devices), MASTER_MAC)]
    dispatch.assert_called_once_with(hass, SIGNAL_DECO_ADDED)
    if not late_master:
        assert result.master_deco is existing_master
        assert result.decos[MASTER_MAC] is existing_master
    api.async_list_devices.assert_awaited()


@pytest.mark.asyncio
async def test_discovery_creates_trackers_binary_sensors_and_node_sensors() -> None:
    """Discover a new satellite across all existing platforms exactly once."""
    hass = MagicMock()
    master = TpLinkDeco(MASTER_MAC)
    master.update(_payload(MASTER_MAC, master=True))
    coordinator, api = _coordinator(
        hass,
        TpLinkDecoData(master, {MASTER_MAC: master}),
    )
    api.async_list_devices.return_value = [
        _payload(MASTER_MAC, master=True),
        _payload(SATELLITE_MAC),
    ]
    # Capture the network-total listener without running HA's scheduler.
    coordinator.async_add_listener = MagicMock(return_value=MagicMock())
    clients_coordinator = MagicMock()
    clients_coordinator.data = {}
    entry = SimpleNamespace(
        entry_id="mesh-one",
        data={
            CONF_CLIENT_PREFIX: "",
            CONF_CLIENT_POSTFIX: "",
            CONF_DECO_PREFIX: "",
            CONF_DECO_POSTFIX: "Deco",
        },
    )
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: coordinator,
                COORDINATOR_CLIENTS_KEY: clients_coordinator,
            }
        }
    }
    handlers: dict[str, list[Callable[[], None]]] = defaultdict(list)
    notifications: list[str] = []

    def _connect(
        target_hass: MagicMock, signal: str, handler: Callable[[], None]
    ) -> Callable[[], None]:
        """Register handlers in a local dispatcher with shared signal state."""
        assert target_hass is hass
        handlers[signal].append(handler)
        return lambda: handlers[signal].remove(handler)

    def _send(target_hass: MagicMock, signal: str) -> None:
        """Synchronously notify every subscribed entity platform."""
        assert target_hass is hass
        notifications.append(signal)
        for handler in tuple(handlers[signal]):
            handler()

    added_tracker = MagicMock()
    added_binary = MagicMock()
    added_sensor = MagicMock()
    with ExitStack() as patches:
        for module in ("device_tracker", "binary_sensor", "sensor"):
            patches.enter_context(
                patch(
                    f"custom_components.tplink_deco.{module}.async_dispatcher_connect",
                    side_effect=_connect,
                )
            )
        patches.enter_context(
            patch(
                "custom_components.tplink_deco.coordinator.async_dispatcher_send",
                side_effect=_send,
            )
        )
        await device_tracker.async_setup_entry(hass, entry, added_tracker)
        await binary_sensor.async_setup_entry(hass, entry, added_binary)
        await sensor.async_setup_entry(hass, entry, added_sensor)

        initial_ids = [
            set(_unique_ids(add))
            for add in (added_tracker, added_binary, added_sensor)
        ]
        assert len(handlers[SIGNAL_DECO_ADDED]) == 3
        assert all(SATELLITE_MAC not in " ".join(ids) for ids in initial_ids)

        result = await coordinator._async_update_data()
        assert result is coordinator.data
        assert notifications == [SIGNAL_DECO_ADDED]

        tracker_ids = _unique_ids(added_tracker)
        binary_ids = _unique_ids(added_binary)
        sensor_ids = _unique_ids(added_sensor)
        assert SATELLITE_MAC in tracker_ids
        assert {
            f"{SATELLITE_MAC}_online",
            f"{SATELLITE_MAC}_internet_online",
        }.issubset(binary_ids)
        assert {
            f"{SATELLITE_MAC}_down",
            f"{SATELLITE_MAC}_up",
            f"{SATELLITE_MAC}_client_count",
        }.issubset(sensor_ids)
        for ids in (tracker_ids, binary_ids, sensor_ids):
            assert len(ids) == len(set(ids))

        # Identical device lists and repeated notifications must be idempotent.
        await coordinator._async_update_data()
        _send(hass, SIGNAL_DECO_ADDED)
        for add, previous in (
            (added_tracker, tracker_ids),
            (added_binary, binary_ids),
            (added_sensor, sensor_ids),
        ):
            assert _unique_ids(add) == previous
        assert notifications.count(SIGNAL_DECO_ADDED) == 2


@pytest.mark.asyncio
async def test_offline_decos_are_retained_without_new_discovery_signal() -> None:
    """Keep existing node identities while an incomplete mesh disappears."""
    hass = MagicMock()
    master = TpLinkDeco(MASTER_MAC)
    master.update(_payload(MASTER_MAC, master=True))
    satellite = TpLinkDeco(SATELLITE_MAC)
    satellite.update(_payload(SATELLITE_MAC))
    coordinator, api = _coordinator(
        hass,
        TpLinkDecoData(
            master,
            {MASTER_MAC: master, SATELLITE_MAC: satellite},
        ),
    )
    api.async_list_devices.return_value = [_payload(MASTER_MAC, master=True)]

    with patch(
        "custom_components.tplink_deco.coordinator.async_dispatcher_send"
    ) as dispatch:
        result = await coordinator._async_update_data()

    assert result is coordinator.data
    assert result.master_deco is master
    assert result.decos[SATELLITE_MAC] is satellite
    assert satellite.online is False
    assert satellite.internet_online is False
    dispatch.assert_not_called()
