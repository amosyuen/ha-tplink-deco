from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .device import create_device_info

POLLING_INTERVAL_OPTIONS = ["10", "30", "60", "120"]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up select entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR_DECOS_KEY]
    async_add_entities([DecoPollingIntervalSelect(hass, config_entry, coordinator)])


class DecoPollingIntervalSelect(SelectEntity):
    """Select entity to control Deco polling interval."""

    _attr_has_entity_name = True
    _attr_name = "Polling interval"
    _attr_icon = "mdi:timer-cog"
    _attr_options = POLLING_INTERVAL_OPTIONS

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, coordinator):
        self.hass = hass
        self.config_entry = config_entry
        self.coordinator = coordinator
        self._attr_unique_id = f"{config_entry.entry_id}_polling_interval"

    @property
    def current_option(self) -> str:
        """Return current polling interval as string."""
        value = self.config_entry.data.get(CONF_SCAN_INTERVAL, 30)
        return str(value)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Attach select to the master Deco device."""
        master_deco = self.coordinator.data.master_deco
        if master_deco is None:
            return None
        return create_device_info(master_deco, master_deco)

    async def async_select_option(self, option: str) -> None:
        """Change polling interval."""
        new_value = int(option)

        data = dict(self.config_entry.data)
        data[CONF_SCAN_INTERVAL] = new_value

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=data,
        )

        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
