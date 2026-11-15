"""Tests for the anonymized Deco config-entry diagnostics download."""

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import CoordinatorHealth
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.diagnostics import (
    async_get_config_entry_diagnostics,
)

PRIVATE_VALUES = (
    "PRIVATE-ROUTER-PASSWORD",
    "PRIVATE-CLIENT-NAME",
    "PRIVATE-SESSION-TOKEN",
    "PRIVATE-SSID-NAME",
    "192.0.2.88",
    "AA:BB:CC:DD:EE:88",
)


def _register_entry(
    hass: MagicMock,
    entry_id: str,
    *,
    online: bool,
) -> tuple[SimpleNamespace, MagicMock, MagicMock]:
    """Set up cached coordinator data without using a live router."""
    deco = TpLinkDeco("AA:BB:CC:DD:EE:88")
    deco.name = PRIVATE_VALUES[1]
    deco.ip_address = PRIVATE_VALUES[4]
    deco.online = online

    client = TpLinkDecoClient("AA:BB:CC:DD:EE:99")
    client.name = PRIVATE_VALUES[1]
    client.online = online

    deco_coordinator = MagicMock()
    deco_coordinator.data = TpLinkDecoData(deco, {deco.mac: deco})
    deco_coordinator.health = CoordinatorHealth()
    deco_coordinator.health.record_success(0.0)
    deco_coordinator.paused = False
    deco_coordinator.last_update_success = True
    deco_coordinator.update_interval = timedelta(seconds=60)

    client_coordinator = MagicMock()
    client_coordinator.data = {client.mac: client}
    client_coordinator.health = CoordinatorHealth()
    client_coordinator.health.record_failure(
        0.0, TimeoutError(PRIVATE_VALUES[2])
    )
    client_coordinator.last_update_success = False
    client_coordinator.update_interval = timedelta(seconds=30)
    client_coordinator.client_query_mode = "per_node"
    client_coordinator.remaining_backoff_seconds = 27
    client_coordinator.has_successful_refresh = False

    hass.data.setdefault(DOMAIN, {})[entry_id] = {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: client_coordinator,
    }
    config_entry = SimpleNamespace(
        entry_id=entry_id,
        data={"password": PRIVATE_VALUES[0], "ssid": PRIVATE_VALUES[3]},
        options={"access_token": PRIVATE_VALUES[2]},
        version=7,
    )
    return config_entry, deco_coordinator, client_coordinator


@pytest.mark.asyncio
async def test_diagnostics_redacts_network_and_configuration_information() -> None:
    """Export health and anonymized counts without names, addresses or tokens."""
    hass = MagicMock()
    hass.data = {}
    entry, deco_coordinator, client_coordinator = _register_entry(
        hass, "mesh-one", online=True
    )

    result = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(result)

    assert result["schema_version"] == 1
    assert result["deco_coordinator"]["known_decos"] == 1
    assert result["deco_coordinator"]["online_decos"] == 1
    assert result["deco_coordinator"]["master_present"] is True
    assert result["deco_coordinator"]["update_interval_seconds"] == 60
    assert result["client_coordinator"]["known_clients"] == 1
    assert result["client_coordinator"]["online_clients"] == 1
    assert result["client_coordinator"]["query_mode"] == "per_node"
    assert result["client_coordinator"]["backoff_remaining_seconds"] == 27
    assert result["client_coordinator"]["timeout_count"] == 1
    assert result["client_coordinator"]["last_error"] == "TimeoutError"
    assert result["client_coordinator"]["last_update_success"] is False
    assert result["deco_coordinator"]["last_update_success"] is True
    assert result["deco_coordinator"]["response_time_ms"] is not None
    for secret in PRIVATE_VALUES:
        assert secret not in dumped

    deco_coordinator.api.assert_not_called()
    client_coordinator.api.assert_not_called()
    assert not any(key in result for key in ("config_entry", "clients", "decos"))


@pytest.mark.asyncio
async def test_diagnostics_uses_aware_timestamp_and_keeps_per_entry_isolation() -> None:
    """Keep timestamp semantics and separate two independently configured meshes."""
    hass = MagicMock()
    hass.data = {}
    first_entry, _, first_client = _register_entry(hass, "first", online=True)
    second_entry, _, second_client = _register_entry(
        hass, "second", online=False
    )
    timestamp = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    first_client.health.last_successful_update = timestamp
    second_client.health.timeout_count = 5
    second_client.health.last_error = "NoSuccessfulClientList"

    first = await async_get_config_entry_diagnostics(hass, first_entry)
    second = await async_get_config_entry_diagnostics(hass, second_entry)

    assert first["client_coordinator"]["last_successful_update"] == (
        "2026-11-15T12:00:00+00:00"
    )
    assert first["client_coordinator"]["online_clients"] == 1
    assert first["client_coordinator"]["timeout_count"] == 1
    assert second["client_coordinator"]["online_clients"] == 0
    assert second["client_coordinator"]["timeout_count"] == 5
    assert second["client_coordinator"]["last_error"] == "NoSuccessfulClientList"
    assert json.dumps(first) != json.dumps(second)


@pytest.mark.asyncio
async def test_diagnostics_handles_empty_and_uninitialized_coordinator_data() -> None:
    """Export complete JSON without inventing nodes or making network requests."""
    hass = MagicMock()
    hass.data = {}
    entry, deco_coordinator, client_coordinator = _register_entry(
        hass, "mesh-empty", online=False
    )
    deco_coordinator.data = None
    client_coordinator.data = None
    deco_coordinator.health = CoordinatorHealth()
    client_coordinator.health = CoordinatorHealth()
    deco_coordinator.update_interval = None
    client_coordinator.update_interval = None

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["deco_coordinator"]["known_decos"] == 0
    assert result["deco_coordinator"]["master_present"] is False
    assert result["deco_coordinator"]["last_successful_update"] is None
    assert result["deco_coordinator"]["update_interval_seconds"] is None
    assert result["client_coordinator"]["known_clients"] == 0
    assert result["client_coordinator"]["online_clients"] == 0
    assert result["client_coordinator"]["last_error"] == "0"
    json.dumps(result)


@pytest.mark.asyncio
async def test_diagnostics_rejects_non_class_error_text() -> None:
    """Prevent accidental export of a raw upstream error if health is corrupted."""
    hass = MagicMock()
    hass.data = {}
    entry, _, client_coordinator = _register_entry(
        hass, "mesh-bad-error", online=False
    )
    client_coordinator.health.last_error = "token=" + PRIVATE_VALUES[2]

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["client_coordinator"]["last_error"] == "UnknownError"
    assert PRIVATE_VALUES[2] not in json.dumps(result)
