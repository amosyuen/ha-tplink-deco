from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .device import create_device_info

LEGACY_POLLING_UNIQUE_ID = "tplink_deco_polling"


def polling_unique_id(config_entry_id: str) -> str:
    """Return the config-entry-scoped polling switch unique ID."""
    return f"{LEGACY_POLLING_UNIQUE_ID}_{config_entry_id}"


def _migrate_polling_switch_unique_id(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Migrate the legacy polling switch without changing its entity ID."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        SWITCH_DOMAIN, DOMAIN, LEGACY_POLLING_UNIQUE_ID
    )
    if entity_id is None:
        return

    entry = registry.async_get(entity_id)
    if entry is None or entry.config_entry_id != config_entry.entry_id:
        return

    registry.async_update_entity(
        entity_id,
        new_unique_id=polling_unique_id(config_entry.entry_id),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up switch."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR_DECOS_KEY]

    _migrate_polling_switch_unique_id(hass, config_entry)
    async_add_entities([DecoPollingSwitch(coordinator)])


class DecoPollingSwitch(SwitchEntity):
    """Switch to control Deco polling."""

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self._attr_name = "Polling"
        self._attr_unique_id = polling_unique_id(coordinator.config_entry.entry_id)
        self._attr_icon = "mdi:lan-connect"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach switch to the master Deco device."""
        master_deco = self.coordinator.data.master_deco
        return create_device_info(master_deco, master_deco, self.coordinator)

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
