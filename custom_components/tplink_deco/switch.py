from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .device import create_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up switch."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR_DECOS_KEY]

    async_add_entities([DecoPollingSwitch(coordinator)])


class DecoPollingSwitch(SwitchEntity):
    """Switch to control Deco polling."""

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self._attr_name = "Polling"
        self._attr_unique_id = "tplink_deco_polling"
        self._attr_icon = "mdi:lan-connect"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach switch to the master Deco device."""
        master_deco = self.coordinator.data.master_deco
        return create_device_info(master_deco, master_deco)

    @property
    def is_on(self) -> bool:
        """Return True if polling is active."""
        return not self.coordinator.paused

    async def async_turn_off(self, **kwargs):
        """Pause polling."""
        self.coordinator.paused = True
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """Resume polling."""
        self.coordinator.paused = False
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
