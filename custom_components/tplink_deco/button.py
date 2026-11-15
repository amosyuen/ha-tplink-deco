"""Manual refresh controls for TP-Link Deco mesh status."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .coordinator import TplinkDecoUpdateCoordinator
from .device import create_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register the entry-scoped manual Deco inventory refresh button."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR_DECOS_KEY]
    async_add_entities([DecoRefreshStatusButton(coordinator)])


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
