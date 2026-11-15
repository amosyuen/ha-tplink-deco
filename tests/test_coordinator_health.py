"""Regression tests for privacy-safe Deco coordinator health diagnostics."""

from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import CoordinatorHealth
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoClientUpdateCoordinator
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.sensor import (
    COORDINATOR_HEALTH_SENSOR_DESCRIPTIONS,
)
from custom_components.tplink_deco.sensor import TplinkCoordinatorHealthSensor
from custom_components.tplink_deco.sensor import async_setup_entry

MASTER_MAC = "02:00:00:00:31:01"
SECOND_MAC = "02:00:00:00:32:01"


def _coordinators() -> tuple[
    TplinkDecoUpdateCoordinator,
    TplinkDecoClientUpdateCoordinator,
]:
    """Create independent real coordinator objects with no live API access."""
    hass = MagicMock()
    deco = TpLinkDeco(MASTER_MAC)
    deco.name = "Test Deco"
    mesh = TplinkDecoData(deco, {deco.mac: deco})
    deco_coordinator = TplinkDecoUpdateCoordinator(
        hass=hass, api=MagicMock(), config_entry=MagicMock(), data=mesh
    )
    client_coordinator = TplinkDecoClientUpdateCoordinator(
        hass=hass,
        api=MagicMock(),
        config_entry=MagicMock(),
        deco_update_coordinator=deco_coordinator,
        consider_home_seconds=300,
        data={},
    )
    return deco_coordinator, client_coordinator


def _health_entities(added: MagicMock) -> list[TplinkCoordinatorHealthSensor]:
    """Collect coordinator health sensors registered by the platform."""
    return [
        item
        for call in added.call_args_list
        for item in call.args[0]
        if isinstance(item, TplinkCoordinatorHealthSensor)
    ]


def test_health_reports_aware_timestamps_without_sensitive_error_text() -> None:
    """Capture durations and sanitized error names, not credentials."""
    health = CoordinatorHealth()
    assert health.last_successful_update is None
    assert health.last_error == "0"
    assert health.response_time_ms is None

    health.record_failure(0.0, TimeoutException("private-session-token"))
    assert health.timeout_count == 1
    assert health.consecutive_failures == 1
    assert health.last_error == "TimeoutException"
    assert "private-session-token" not in repr(health)

    health.record_incomplete(0.0)
    assert health.consecutive_failures == 2
    assert health.last_error == "NoSuccessfulClientList"

    health.record_success(0.0)
    assert health.consecutive_failures == 0
    assert health.last_successful_update is not None
    assert health.last_successful_update.tzinfo == timezone.utc
    assert health.response_time_ms is not None
    assert health.response_time_ms >= 0


@pytest.mark.asyncio
async def test_deco_health_counts_only_actual_attempts() -> None:
    """Skip timing when paused and retain the last successful timestamp."""
    deco_coordinator, _ = _coordinators()
    original_data = deco_coordinator.data
    fetch = AsyncMock(return_value=original_data)
    deco_coordinator._async_update_data_internal = fetch

    assert await deco_coordinator._async_update_data() is original_data
    assert deco_coordinator.health.last_successful_update is not None
    previous_timestamp = deco_coordinator.health.last_successful_update
    assert fetch.await_count == 1

    deco_coordinator.paused = True
    assert await deco_coordinator._async_update_data() is original_data
    assert fetch.await_count == 1

    deco_coordinator.paused = False
    fetch.side_effect = TimeoutError("sensitive api payload")
    with pytest.raises(TimeoutError):
        await deco_coordinator._async_update_data()

    assert deco_coordinator.health.last_successful_update == previous_timestamp
    assert deco_coordinator.health.timeout_count == 1
    assert deco_coordinator.health.last_error == "TimeoutError"
    assert deco_coordinator.health.consecutive_failures == 1


@pytest.mark.asyncio
async def test_client_health_distinguishes_skips_and_failed_polls() -> None:
    """Never report a skipped or completely failed poll as successful."""
    _, client_coordinator = _coordinators()
    client_coordinator._async_update_data_internal = AsyncMock(return_value={})

    client_coordinator._deco_update_coordinator.paused = True
    assert await client_coordinator._async_update_data() == {}
    assert client_coordinator._async_update_data_internal.await_count == 0
    assert client_coordinator.health.consecutive_failures == 0

    client_coordinator._deco_update_coordinator.paused = False
    assert await client_coordinator._async_update_data() == {}
    assert client_coordinator.health.last_successful_update is None
    assert client_coordinator.health.last_error == "NoSuccessfulClientList"

    async def _successful_poll() -> dict[str, object]:
        """Simulate a valid empty client list without any API request."""
        client_coordinator._poll_had_valid_response = True
        return {}

    client_coordinator._async_update_data_internal = AsyncMock(
        side_effect=_successful_poll
    )
    assert await client_coordinator._async_update_data() == {}
    assert client_coordinator.health.last_successful_update is not None
    assert client_coordinator.health.consecutive_failures == 0
    assert client_coordinator.client_query_mode == "per_node"

    client_coordinator._async_update_data_internal = AsyncMock(
        side_effect=TimeoutException("hidden query contents")
    )
    with pytest.raises(TimeoutException):
        await client_coordinator._async_update_data()
    assert client_coordinator.health.timeout_count == 1
    assert client_coordinator.health.last_error == "TimeoutException"


@pytest.mark.asyncio
async def test_health_tracks_real_partial_and_all_failed_node_polls() -> None:
    """Count partial success and preserve last success on all-failed polls."""
    deco_coordinator, client_coordinator = _coordinators()
    second_deco = TpLinkDeco(SECOND_MAC)
    deco_coordinator.data.decos[SECOND_MAC] = second_deco

    client_coordinator._async_clients_for_deco = AsyncMock(
        side_effect=[([], False), (None, False)]
    )
    assert await client_coordinator._async_update_data() == {}
    assert client_coordinator.health.last_successful_update is not None
    last_success = client_coordinator.health.last_successful_update
    assert client_coordinator.health.consecutive_failures == 0

    client_coordinator._async_clients_for_deco = AsyncMock(
        side_effect=[(None, False), (None, False)]
    )
    assert await client_coordinator._async_update_data() == {}
    assert client_coordinator.health.last_successful_update == last_success
    assert client_coordinator.health.consecutive_failures == 1
    assert client_coordinator.health.last_error == "NoSuccessfulClientList"

    # Two valid empty replies recover without creating client tracker state.
    client_coordinator._async_clients_for_deco = AsyncMock(
        side_effect=[([], False), ([], False)]
    )
    assert await client_coordinator._async_update_data() == {}
    assert client_coordinator.health.consecutive_failures == 0
    assert client_coordinator.health.last_successful_update is not None


@pytest.mark.asyncio
async def test_health_sensors_register_once_and_keep_existing_ids() -> None:
    """Attach eight disabled diagnostics to the master without new API calls."""
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    expected_keys = {item.key for item in COORDINATOR_HEALTH_SENSOR_DESCRIPTIONS}
    assert len(expected_keys) == 8
    assert all(
        item.entity_registry_enabled_default is False
        for item in COORDINATOR_HEALTH_SENSOR_DESCRIPTIONS
    )

    for entry_id, mac in (("mesh-one", MASTER_MAC), ("mesh-two", SECOND_MAC)):
        master = TpLinkDeco(mac)
        master.name = "Test Deco"
        deco_coordinator = MagicMock()
        deco_coordinator.health = CoordinatorHealth()
        deco_coordinator.data = TpLinkDecoData(master, {mac: master})
        client_coordinator = MagicMock()
        client_coordinator.health = CoordinatorHealth()
        client_coordinator.client_query_mode = "per_node"
        client_coordinator.has_successful_refresh = False
        client_coordinator.successfully_polled_deco_macs = set()
        client_coordinator.data = {}
        hass.data[DOMAIN][entry_id] = {
            COORDINATOR_DECOS_KEY: deco_coordinator,
            COORDINATOR_CLIENTS_KEY: client_coordinator,
        }
        add_entities = MagicMock()
        with patch(
            "custom_components.tplink_deco.sensor.async_dispatcher_connect",
            return_value=MagicMock(),
        ):
            await async_setup_entry(
                hass, SimpleNamespace(entry_id=entry_id), add_entities
            )

        health_sensors = _health_entities(add_entities)
        assert len(health_sensors) == 8
        assert {entity.unique_id for entity in health_sensors} == {
            f"{mac}_{key}" for key in expected_keys
        }
        assert all(
            entity.device_info["identifiers"] == {(DOMAIN, mac)}
            for entity in health_sensors
        )
        assert all(entity.available for entity in health_sensors)
        assert not client_coordinator.api.called

        listener = deco_coordinator.async_add_listener.call_args.args[0]
        listener()
        assert _health_entities(add_entities) == health_sensors


@pytest.mark.asyncio
async def test_health_sensors_wait_for_master_then_register_once() -> None:
    """Expose diagnostics for a master discovered after initial setup."""
    hass = MagicMock()
    deco_coordinator = MagicMock()
    deco_coordinator.data = TpLinkDecoData()
    client_coordinator = MagicMock()
    client_coordinator.has_successful_refresh = False
    client_coordinator.data = {}
    hass.data = {
        DOMAIN: {
            "mesh-one": {
                COORDINATOR_DECOS_KEY: deco_coordinator,
                COORDINATOR_CLIENTS_KEY: client_coordinator,
            }
        }
    }
    added = MagicMock()
    with patch(
        "custom_components.tplink_deco.sensor.async_dispatcher_connect",
        return_value=MagicMock(),
    ):
        await async_setup_entry(
            hass, SimpleNamespace(entry_id="mesh-one"), added
        )

    listener = deco_coordinator.async_add_listener.call_args.args[0]
    assert _health_entities(added) == []
    master = TpLinkDeco(MASTER_MAC)
    master.name = "Late Master"
    deco_coordinator.data = TpLinkDecoData(master, {master.mac: master})
    listener()
    listener()
    assert len(_health_entities(added)) == 8
