"""Tests for restoring disconnected Deco client trackers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco import _remove_discovered_decos_from_clients
from custom_components.tplink_deco import async_create_config_data
from custom_components.tplink_deco.const import ATTR_DEVICE_TYPE
from custom_components.tplink_deco.const import DEVICE_TYPE_CLIENT
from custom_components.tplink_deco.const import DEVICE_TYPE_DECO


def _entry(
    unique_id: str,
    *,
    domain: str = "device_tracker",
    disabled_by=None,
):
    return SimpleNamespace(
        domain=domain,
        disabled_by=disabled_by,
        entity_id=f"{domain}.{unique_id.lower().replace(':', '_')}",
        unique_id=unique_id,
        original_name=f"  {unique_id}  ",
    )


def _stored_state(device_type=DEVICE_TYPE_CLIENT):
    attributes = {} if device_type is None else {ATTR_DEVICE_TYPE: device_type}
    return SimpleNamespace(state=SimpleNamespace(attributes=attributes))


def _capture_coordinator_data(coordinator_data):
    async def capture_coordinators(
        hass,
        config_data,
        config_entry,
        consider_home_seconds,
        update_interval,
        deco_data,
        client_data,
    ):
        coordinator_data.update(deco_data=deco_data, client_data=client_data)
        return {}

    return capture_coordinators


def test_discovered_decos_are_removed_from_provisional_clients():
    client_data = {
        "AA:BB:CC:DD:EE:01": MagicMock(),
        "AA:BB:CC:DD:EE:02": MagicMock(),
    }
    deco_data = SimpleNamespace(decos={"AA:BB:CC:DD:EE:01": MagicMock()})

    _remove_discovered_decos_from_clients(client_data, deco_data)

    assert list(client_data) == ["AA:BB:CC:DD:EE:02"]


@pytest.mark.asyncio
async def test_restore_seeds_unavailable_tracker_without_device_type():
    entry = _entry("AA:BB:CC:DD:EE:01")
    coordinator_data = {}

    restore_data = SimpleNamespace(
        async_get_stored_state=lambda entity_id: _stored_state(None)
    )

    with (
        patch(
            "custom_components.tplink_deco.entity_registry.async_entries_for_config_entry",
            return_value=[entry],
        ),
        patch("custom_components.tplink_deco.entity_registry.async_get"),
        patch(
            "custom_components.tplink_deco.restore_state.async_get",
            return_value=restore_data,
        ),
        patch(
            "custom_components.tplink_deco.async_create_and_refresh_coordinators",
            new=AsyncMock(side_effect=_capture_coordinator_data(coordinator_data)),
        ),
    ):
        config_entry = MagicMock()
        config_entry.entry_id = "entry"
        config_entry.data = {}
        await async_create_config_data(MagicMock(), config_entry)

    assert list(coordinator_data["client_data"]) == [entry.unique_id]
    assert coordinator_data["client_data"][entry.unique_id].name == entry.unique_id


@pytest.mark.asyncio
async def test_restore_keeps_known_deco_out_of_client_data():
    entry = _entry("AA:BB:CC:DD:EE:02")
    coordinator_data = {}

    restore_data = SimpleNamespace(
        async_get_stored_state=lambda entity_id: _stored_state(DEVICE_TYPE_DECO)
    )

    with (
        patch(
            "custom_components.tplink_deco.entity_registry.async_entries_for_config_entry",
            return_value=[entry],
        ),
        patch("custom_components.tplink_deco.entity_registry.async_get"),
        patch(
            "custom_components.tplink_deco.restore_state.async_get",
            return_value=restore_data,
        ),
        patch(
            "custom_components.tplink_deco.async_create_and_refresh_coordinators",
            new=AsyncMock(side_effect=_capture_coordinator_data(coordinator_data)),
        ),
    ):
        config_entry = MagicMock()
        config_entry.entry_id = "entry"
        config_entry.data = {}
        await async_create_config_data(MagicMock(), config_entry)

    assert entry.unique_id in coordinator_data["deco_data"].decos
    assert entry.unique_id not in coordinator_data["client_data"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry,state",
    [
        (_entry("AA:BB:CC:DD:EE:03", disabled_by="user"), _stored_state(None)),
        (_entry("AA:BB:CC:DD:EE:04", domain="sensor"), _stored_state(None)),
        (_entry("AA:BB:CC:DD:EE:05"), None),
    ],
)
async def test_restore_skips_ineligible_registry_entries(entry, state):
    coordinator_data = {}

    restore_data = SimpleNamespace(async_get_stored_state=lambda entity_id: state)

    with (
        patch(
            "custom_components.tplink_deco.entity_registry.async_entries_for_config_entry",
            return_value=[entry],
        ),
        patch("custom_components.tplink_deco.entity_registry.async_get"),
        patch(
            "custom_components.tplink_deco.restore_state.async_get",
            return_value=restore_data,
        ),
        patch(
            "custom_components.tplink_deco.async_create_and_refresh_coordinators",
            new=AsyncMock(side_effect=_capture_coordinator_data(coordinator_data)),
        ),
    ):
        config_entry = MagicMock()
        config_entry.entry_id = "entry"
        config_entry.data = {}
        await async_create_config_data(MagicMock(), config_entry)

    assert coordinator_data["deco_data"].decos == {}
    assert coordinator_data["client_data"] == {}
