"""Exercise reboot buttons with Home Assistant registries and a simulated Deco API."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
import logging
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import HomeAssistantError
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
import pytest
import pytest_asyncio

from custom_components.tplink_deco.button import async_setup_entry
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator
from custom_components.tplink_deco.exceptions import LoginForbiddenException
from custom_components.tplink_deco.exceptions import UnexpectedApiException

MASTER = "02:00:00:00:66:01"
SATELLITE = "02:00:00:00:66:02"
OTHER_MASTER = "02:00:00:00:66:03"
PRIVATE = "synthetic-private-response"


def _node(mac: str, role: str = "master", status: str = "connected") -> dict[str, str]:
    """Build an anonymous firmware inventory item."""
    return {"mac": mac, "role": role, "group_status": status, "nickname": "deco"}


@pytest_asyncio.fixture
async def ha(tmp_path: Path) -> AsyncIterator[HomeAssistant]:
    """Provide the real state machine and entry-scoped device/entity registries."""
    hass = HomeAssistant(str(tmp_path))
    hass.data[DOMAIN] = {}
    hass.config_entries = MagicMock(spec=ConfigEntries)
    hass.config_entries.async_get_entry.side_effect = lambda entry_id: (
        hass.data[DOMAIN][entry_id][COORDINATOR_DECOS_KEY].config_entry
    )
    if hasattr(dr, "async_setup"):
        dr.async_setup(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    try:
        yield hass
    finally:
        for data in hass.data[DOMAIN].values():
            coordinator = data[COORDINATOR_DECOS_KEY]
            await data["platform"].async_reset()
            await coordinator.config_entry._async_process_on_unload(hass)
            await coordinator.async_shutdown()
        await hass.async_stop()


@dataclass
class Mesh:
    """Keep the simulated router and actual Home Assistant button platform together."""

    coordinator: TplinkDecoUpdateCoordinator
    api: MagicMock
    platform: EntityPlatform
    queued: list[ButtonEntity]
    buttons: dict[str, ButtonEntity]

    async def add_discovered(self) -> None:
        """Register pending entities with Home Assistant and check for duplicate IDs."""
        pending = list(self.queued)
        self.queued.clear()
        for entity in pending:
            assert entity.unique_id not in self.buttons
            self.buttons[entity.unique_id] = entity
        await self.platform.async_add_entities(pending)


async def _mesh(
    hass: HomeAssistant, entry_id: str, nodes: list[dict[str, str]]
) -> Mesh:
    """Run entry setup and button discovery with startup-only inventory polling."""
    entry = ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id=entry_id,
        minor_version=1,
        options={},
        source="user",
        subentries_data=None,
        title=entry_id,
        unique_id=None,
        version=7,
    )
    api = MagicMock()
    api.async_list_devices = AsyncMock(return_value=nodes)
    api.async_get_performance = AsyncMock(return_value={})
    api.async_reboot_decos = AsyncMock()
    coordinator = TplinkDecoUpdateCoordinator(
        hass, api, entry, device_list_interval_seconds=0
    )
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain=Platform.BUTTON,
        platform_name=DOMAIN,
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    hass.data[DOMAIN][entry_id] = {
        COORDINATOR_DECOS_KEY: coordinator,
        "platform": platform,
    }
    await coordinator.async_request_device_refresh()
    mesh = Mesh(coordinator, api, platform, [], {})
    await async_setup_entry(hass, entry, mesh.queued.extend)
    await mesh.add_discovered()
    return mesh


@pytest.mark.asyncio
async def test_scoped_single_and_mesh_buttons_discover_once_and_recover(
    ha: HomeAssistant,
) -> None:
    """Target only the owning entry, preserve paused state and wait for observed recovery."""
    mesh = await _mesh(ha, "first", [_node(MASTER)])
    other = await _mesh(ha, "second", [_node(OTHER_MASTER)])
    assert mesh.buttons.keys() == {"first_refresh_deco_status", f"{MASTER}_reboot"}
    master_button = mesh.buttons[f"{MASTER}_reboot"]
    mesh.coordinator.paused = True
    await master_button.async_press()
    mesh.api.async_reboot_decos.assert_awaited_once_with([MASTER])
    assert mesh.api.async_list_devices.await_count == 2
    assert mesh.coordinator.paused and master_button.available

    mesh.api.async_list_devices.return_value = [
        _node(MASTER),
        _node(SATELLITE, "slave"),
    ]
    await mesh.coordinator.async_request_device_refresh()
    await mesh.add_discovered()
    mesh_button = mesh.buttons["first_reboot_all"]
    satellite_button = mesh.buttons[f"{SATELLITE}_reboot"]
    assert mesh_button.device_info["identifiers"] == {(DOMAIN, MASTER)}
    assert satellite_button.device_info["identifiers"] == {(DOMAIN, SATELLITE)}
    await satellite_button.async_press()
    mesh.api.async_reboot_decos.assert_awaited_with([SATELLITE])
    await mesh_button.async_press()
    mesh.api.async_reboot_decos.assert_awaited_with([MASTER, SATELLITE])
    assert not mesh.queued
    other.api.async_reboot_decos.assert_not_awaited()

    mesh.api.async_list_devices.return_value = [_node(MASTER)]
    with pytest.raises(ServiceValidationError, match="online"):
        await mesh_button.async_press()
    assert not mesh_button.available and not satellite_button.available
    assert mesh.api.async_reboot_decos.await_count == 3
    mesh.api.async_list_devices.return_value = [
        _node(MASTER),
        _node(SATELLITE, "slave"),
    ]
    await mesh.coordinator.async_request_device_refresh()
    assert mesh_button.available and satellite_button.available and not mesh.queued
    assert mesh.coordinator.paused


@pytest.mark.asyncio
async def test_reboot_all_follows_master_in_real_registry(ha: HomeAssistant) -> None:
    """Move the same user-named mesh button when roles swap without new MACs."""
    mesh = await _mesh(ha, "mesh", [_node(MASTER), _node(SATELLITE, "slave")])
    entities = er.async_get(ha)
    row = entities.async_get(mesh.buttons["mesh_reboot_all"].entity_id)
    original = entities.async_update_entity(row.entity_id, name="My mesh restart")
    mesh.api.async_list_devices.return_value = [
        _node(MASTER, "slave"),
        _node(SATELLITE),
    ]
    await mesh.coordinator.async_request_device_refresh()
    current = entities.async_get(original.entity_id)
    new_master_button = entities.async_get(
        mesh.buttons[f"{SATELLITE}_reboot"].entity_id
    )
    assert (
        current.device_id == new_master_button.device_id
        and current.device_id != original.device_id
    )
    assert (current.id, current.name, current.unique_id) == (
        original.id,
        original.name,
        "mesh_reboot_all",
    )
    assert mesh.buttons["mesh_reboot_all"].device_info["identifiers"] == {
        (DOMAIN, SATELLITE)
    }
    assert not mesh.queued


@pytest.mark.asyncio
async def test_mesh_button_moves_immediately_to_a_newly_discovered_master(
    ha: HomeAssistant,
) -> None:
    """A new master takes ownership even when startup-only polling cannot run again."""
    mesh = await _mesh(ha, "mesh", [_node(MASTER), _node(SATELLITE, "slave")])
    button = mesh.buttons["mesh_reboot_all"]
    registry = er.async_get(ha)
    initial = registry.async_get(button.entity_id)
    mesh.api.async_list_devices.return_value = [
        _node(MASTER, "slave"),
        _node(SATELLITE, "slave"),
        _node(OTHER_MASTER),
    ]
    await mesh.coordinator.async_request_device_refresh()
    moved = registry.async_get(button.entity_id)
    assert moved.id == initial.id and moved.device_id != initial.device_id
    assert dr.async_get(ha).async_get(moved.device_id).identifiers == {
        (DOMAIN, OTHER_MASTER)
    }
    await mesh.add_discovered()
    assert (
        registry.async_get(mesh.buttons[f"{OTHER_MASTER}_reboot"].entity_id).device_id
        == moved.device_id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nodes",
    [
        [_node(MASTER, "slave"), _node(SATELLITE, "slave")],
        [_node(MASTER), _node(SATELLITE)],
        [_node(MASTER, status="disconnected"), _node(SATELLITE)],
        [_node(MASTER, status="disconnected"), _node(SATELLITE, "slave")],
        [_node(MASTER), _node(SATELLITE, "slave", "disconnected")],
        [],
    ],
)
async def test_fresh_inventory_rejects_incomplete_or_ambiguous_batch(
    ha: HomeAssistant, nodes: list[dict[str, str]]
) -> None:
    """An earlier healthy snapshot cannot authorize a partial or stale reboot."""
    mesh = await _mesh(ha, "mesh", [_node(MASTER), _node(SATELLITE, "slave")])
    button = mesh.buttons["mesh_reboot_all"]
    assert button.available
    mesh.api.async_list_devices.return_value = nodes
    with pytest.raises(ServiceValidationError, match="online"):
        await button.async_press()
    assert not button.available
    mesh.api.async_reboot_decos.assert_not_awaited()


@pytest.mark.asyncio
async def test_unload_while_refreshing_prevents_the_write(ha: HomeAssistant) -> None:
    """Do not send a command on a former coordinator after an entry reload."""
    mesh = await _mesh(ha, "mesh", [_node(MASTER)])
    original_data = ha.data[DOMAIN]["mesh"]

    async def reload_entry() -> list[dict[str, str]]:
        """Replace entry ownership during the last awaited inventory call."""
        ha.data[DOMAIN]["mesh"] = {COORDINATOR_DECOS_KEY: MagicMock()}
        return [_node(MASTER)]

    mesh.api.async_list_devices.side_effect = reload_entry
    try:
        with pytest.raises(ServiceValidationError, match="no longer active"):
            await mesh.buttons[f"{MASTER}_reboot"].async_press()
    finally:
        ha.data[DOMAIN]["mesh"] = original_data
    mesh.api.async_reboot_decos.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("incorrect_owner", [False, True])
async def test_entire_registry_selection_is_checked_before_reboot(
    ha: HomeAssistant, incorrect_owner: bool
) -> None:
    """Abort the entire batch if the last registry device is gone or belongs elsewhere."""
    mesh = await _mesh(ha, "mesh", [_node(MASTER), _node(SATELLITE, "slave")])
    await _mesh(ha, "elsewhere", [_node(OTHER_MASTER)])
    registry = dr.async_get(ha)
    row = er.async_get(ha).async_get(mesh.buttons[f"{SATELLITE}_reboot"].entity_id)
    registry.async_remove_device(row.device_id)
    if incorrect_owner:
        registry.async_get_or_create(
            config_entry_id="elsewhere", identifiers={(DOMAIN, SATELLITE)}
        )
    with pytest.raises(ServiceValidationError, match="registry"):
        await mesh.buttons["mesh_reboot_all"].async_press()
    mesh.api.async_reboot_decos.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (LoginForbiddenException(PRIVATE), ConfigEntryAuthFailed),
        (UnexpectedApiException(PRIVATE), HomeAssistantError),
    ],
)
async def test_rejected_reboot_is_private_and_can_recover(
    ha: HomeAssistant,
    failure: Exception,
    error_type: type[Exception],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep authentication and unsupported firmware errors private and actionable."""
    mesh = await _mesh(ha, "mesh", [_node(MASTER)])
    button = mesh.buttons[f"{MASTER}_reboot"]
    mesh.api.async_reboot_decos.side_effect = failure
    with pytest.raises(error_type) as raised:
        await button.async_press()
    assert PRIVATE not in str(raised.value) and PRIVATE not in caplog.text
    assert raised.value.__context__ is None
    assert button.available and not mesh.coordinator.paused
    mesh.api.async_reboot_decos.side_effect = None
    await button.async_press()
    assert mesh.api.async_reboot_decos.await_count == 2


@pytest.mark.asyncio
async def test_failed_preflight_and_overlapping_or_cancelled_press(
    ha: HomeAssistant,
) -> None:
    """A failed read sends no write, and cancellation releases the mesh's shared lock."""
    mesh = await _mesh(ha, "mesh", [_node(MASTER), _node(SATELLITE, "slave")])
    button = mesh.buttons["mesh_reboot_all"]
    mesh.api.async_list_devices.side_effect = TimeoutError()
    with pytest.raises(HomeAssistantError, match="refresh"):
        await button.async_press()
    mesh.api.async_reboot_decos.assert_not_awaited()
    mesh.api.async_list_devices.side_effect = None
    started = asyncio.Event()
    resume = asyncio.Event()

    async def pending_write(targets: list[str]) -> None:
        """Pause the simulated write so a second press can overlap."""
        assert targets == [MASTER, SATELLITE]
        started.set()
        await resume.wait()

    mesh.api.async_reboot_decos.side_effect = pending_write
    task = asyncio.create_task(button.async_press())
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        with pytest.raises(ServiceValidationError, match="already in progress"):
            await mesh.buttons[f"{SATELLITE}_reboot"].async_press()
        mesh.api.async_reboot_decos.assert_awaited_once_with([MASTER, SATELLITE])
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    mesh.api.async_reboot_decos.side_effect = None
    await button.async_press()
    assert mesh.api.async_reboot_decos.await_count == 2
