"""TP-Link Deco."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.device_tracker import SOURCE_TYPE_ROUTER
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SIGNAL_CLIENT_ADDED
from .coordinator import TPLinkDecoClient, TpLinkDecoDataUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Setup binary_sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    tracked = set()

    @callback
    def add_untracked_entities():
        """Add new tracker entities from the router."""
        new_entities = []

        for mac in coordinator.data:
            if mac in tracked:
                continue

            new_entities.append(
                TpLinkDecoDeviceTracker(coordinator, coordinator.data[mac])
            )
            tracked.add(mac)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.on_close(
        async_dispatcher_connect(hass, SIGNAL_CLIENT_ADDED, add_untracked_entities)
    )

    add_untracked_entities()


class TpLinkDecoDeviceTracker(CoordinatorEntity, ScannerEntity):
    """TP Link Deco Entity."""

    def __init__(
        self, coordinator: TpLinkDecoDataUpdateCoordinator, client: TPLinkDecoClient
    ) -> None:
        """Initialize a AsusWrt device."""
        self._client = client
        super().__init__(coordinator)

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self.mac_address

    @property
    def source_type(self):
        """Return the source type."""
        return SOURCE_TYPE_ROUTER

    @property
    def name(self):
        """Return the name for this entity."""
        return self._client.name

    @property
    def icon(self) -> str:
        """Return device icon."""
        return "mdi:lan-connect" if self.is_connected else "mdi:lan-disconnect"

    @property
    def is_connected(self):
        """Return true if the device is connected to the router."""
        return self._client.online

    @property
    def ip_address(self) -> str:
        """Return the primary ip address of the device."""
        return self._client.ip_address

    @property
    def mac_address(self) -> str:
        """Return the mac address of the device."""
        return self._client.mac

    # @property
    # def device_info(self):
    #     return DeviceInfo(
    #         connections={(CONNECTION_NETWORK_MAC, self.mac_address)},
    #         manufacturer="TP-Link",
    #         identifiers={(DOMAIN, self.mac_address)},
    #         default_model="Deco",
    #         name=self.name,
    #     )

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "connection_type": self._client.connection_type,
            "interface": self._client.interface,
            "down_kb_per_s": self._client.up_kb_per_s,
            "up_kb_per_s": self._client.up_kb_per_s,
        }

    @callback
    async def async_on_demand_update(self):
        """Update state."""
        await self.coordinator.async_request_refresh()
