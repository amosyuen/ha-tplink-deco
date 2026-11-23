"""Manual refresh and reboot controls for a TP-Link Deco mesh."""

import asyncio

from homeassistant.components.button import ButtonDeviceClass
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import HomeAssistantError
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .coordinator import TpLinkDeco
from .coordinator import TplinkDecoUpdateCoordinator
from .device import create_device_info
from .exceptions import EmptyDataException
from .exceptions import ForbiddenException
from .exceptions import LoginForbiddenException
from .exceptions import LoginInvalidException


def _registered_node(
    registry: dr.DeviceRegistry, entry_id: str, mac: str
) -> dr.DeviceEntry | None:
    """Look up a node within its entry on both supported registry APIs."""
    identifier = (DOMAIN, mac)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, entry_id)
    device = registry.async_get_device(identifiers={identifier})
    return device if device is not None and entry_id in device.config_entries else None


@callback
def _relink_mesh_button(
    hass: HomeAssistant,
    entry: ConfigEntry,
    unique_id: str,
    master: TpLinkDeco,
    *,
    newly_discovered: bool,
) -> bool:
    """Move the existing button once its new master is registered in this entry."""
    entities = er.async_get(hass)
    entity_id = entities.async_get_entity_id("button", DOMAIN, unique_id)
    row = entities.async_get(entity_id) if entity_id else None
    if row is None or row.config_entry_id != entry.entry_id:
        return False
    registry = dr.async_get(hass)
    device = _registered_node(registry, entry.entry_id, master.mac)
    if device is None and newly_discovered:
        # EntityPlatform will register the freshly discovered node asynchronously.
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, master.mac)}
        )
    if device is None:
        return False
    if row.device_id != device.id:
        entities.async_update_entity(row.entity_id, device_id=device.id)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register the refresh button and discover reboot targets in this entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR_DECOS_KEY]
    async_add_entities([DecoRefreshStatusButton(coordinator)])
    known_macs: set[str] = set()
    reboot_lock = asyncio.Lock()
    mesh_button: DecoRebootButton | None = None
    master_mac: str | None = None

    @callback
    def discover_reboot_buttons() -> None:
        """Add each button once and follow role changes on existing nodes."""
        nonlocal mesh_button, master_mac
        if not coordinator.last_update_success:
            return
        new_macs = [mac for mac in coordinator.data.decos if mac not in known_macs]
        new_buttons = [
            DecoRebootButton(coordinator, reboot_lock, mac) for mac in new_macs
        ]
        known_macs.update(new_macs)
        master = coordinator.data.confirmed_online_master
        if master is not None and len(coordinator.data.decos) > 1:
            if mesh_button is None:
                mesh_button = DecoRebootButton(coordinator, reboot_lock)
                new_buttons.append(mesh_button)
                master_mac = master.mac
            elif master_mac != master.mac and _relink_mesh_button(
                hass,
                config_entry,
                mesh_button.unique_id,
                master,
                newly_discovered=master.mac in new_macs,
            ):
                master_mac = master.mac
        if new_buttons:
            async_add_entities(new_buttons)

    discover_reboot_buttons()
    config_entry.async_on_unload(
        coordinator.async_add_listener(discover_reboot_buttons)
    )


class DecoRefreshStatusButton(ButtonEntity):
    """Refresh the Deco inventory even in startup-only polling mode."""

    _attr_has_entity_name = True
    _attr_name = "Refresh Deco status"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: TplinkDecoUpdateCoordinator) -> None:
        """Keep the button attached to its owning config entry."""
        self.coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_refresh_deco_status"
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        """Link to the master Deco when its identity is known."""
        master_deco = self.coordinator.data.master_deco
        return create_device_info(master_deco, master_deco, self.coordinator)

    async def async_press(self) -> None:
        """Request a real device-list refresh without debouncer delays."""
        await self.coordinator.async_request_device_refresh()


class DecoRebootButton(CoordinatorEntity[TplinkDecoUpdateCoordinator], ButtonEntity):
    """Restart one Deco or all known nodes of its own mesh."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(
        self,
        coordinator: TplinkDecoUpdateCoordinator,
        reboot_lock: asyncio.Lock,
        deco_mac: str | None = None,
    ) -> None:
        """Keep the original per-node or per-entry registry identifier."""
        super().__init__(coordinator)
        self._deco_mac = deco_mac
        self._reboot_lock = reboot_lock
        self._attr_translation_key = "reboot" if deco_mac is not None else "reboot_all"
        self._attr_unique_id = (
            f"{deco_mac}_reboot"
            if deco_mac is not None
            else f"{coordinator.config_entry.entry_id}_reboot_all"
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        """Attach a node button to its Deco and the mesh button to its master."""
        data = self.coordinator.data
        node = (
            data.decos.get(self._deco_mac)
            if self._deco_mac is not None
            else data.confirmed_online_master
        )
        return create_device_info(node, data.master_deco, self.coordinator)

    def _target_macs(self) -> list[str]:
        """Validate a single online node independently of mesh-wide reboot."""
        if not self.coordinator.last_update_success:
            return []

        data = self.coordinator.data
        if self._deco_mac is not None:
            node = data.decos.get(self._deco_mac)
            return [self._deco_mac] if node is not None and node.online else []

        # Reboot All must still have one confirmed, online master and a
        # complete set of online mesh nodes. An individual satellite does not.
        if (
            data.confirmed_online_master is not None
            and len(data.decos) > 1
            and all(node.online for node in data.decos.values())
        ):
            return list(data.decos)
        return []

    @property
    def available(self) -> bool:
        """Report availability from the last successful mesh inventory."""
        return bool(self._target_macs())

    async def async_press(self) -> None:
        """Verify the current inventory and registry before one reboot request."""
        if self._reboot_lock.locked():
            raise ServiceValidationError(
                "A restart is already in progress for this mesh"
            )
        async with self._reboot_lock:
            await self.coordinator.async_request_device_refresh()
            targets = self._target_macs()
            entry_id = self.coordinator.config_entry.entry_id
            entry_data = self.hass.data.get(DOMAIN, {}).get(entry_id, {})
            if entry_data.get(COORDINATOR_DECOS_KEY) is not self.coordinator:
                raise ServiceValidationError(
                    "This Deco configuration is no longer active"
                )
            if not targets:
                raise ServiceValidationError(
                    "Restart unavailable. Check that the master and selected Decos are online"
                )
            registry = dr.async_get(self.hass)
            for mac in targets:
                if _registered_node(registry, entry_id, mac) is None:
                    raise ServiceValidationError(
                        "A selected Deco is missing from this configuration's device registry"
                    )
            await self._async_send_reboot(targets)

    async def _async_send_reboot(self, targets: list[str]) -> None:
        """Report actionable errors without leaking upstream messages or identifiers."""
        try:
            await self.coordinator.api.async_reboot_decos(targets)
        except (
            ConfigEntryAuthFailed,
            EmptyDataException,
            ForbiddenException,
            LoginForbiddenException,
            LoginInvalidException,
        ):
            error = ConfigEntryAuthFailed(
                "Deco authentication failed. Check the integration credentials"
            )
        except Exception:
            error = HomeAssistantError(
                "Deco did not confirm the restart. Check the router status and firmware support before trying again"
            )
        else:
            return
        raise error
