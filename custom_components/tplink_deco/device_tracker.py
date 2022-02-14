"""TP-Link Deco."""
import logging
from typing import Any

from homeassistant.components.device_tracker import SOURCE_TYPE_ROUTER
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.components.device_tracker.const import ATTR_IP
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .const import SIGNAL_CLIENT_ADDED
from .coordinator import TPLinkDecoClient
from .coordinator import TplinkDecoDataUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)

ATTR_CONNECTION_TYPE = "connection_type"
ATTR_DOWN_KILOBYTES_PER_S = "down_kilobytes_per_s"
ATTR_INTERFACE = "interface"
ATTR_UP_KILOBYTES_PER_S = "up_kilobytes_per_s"


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
                TplinkDecoDeviceTracker(coordinator, coordinator.data[mac])
            )
            tracked.add(mac)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.on_close(
        async_dispatcher_connect(hass, SIGNAL_CLIENT_ADDED, add_untracked_entities)
    )

    add_untracked_entities()


class TplinkDecoDeviceTracker(CoordinatorEntity, RestoreEntity, ScannerEntity):
    """TP Link Deco Entity."""

    def __init__(
        self, coordinator: TplinkDecoDataUpdateCoordinator, client: TPLinkDecoClient
    ) -> None:
        """Initialize a TP-Link Deco device."""
        self._attr_connection_type = None
        self._attr_interface = None
        self._attr_ip_address = None
        self._attr_name = None
        self._client = client
        self._mac_address = client.mac
        self._update_from_client()
        super().__init__(coordinator)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Restore old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            if self._attr_connection_type is None:
                self._attr_connection_type = old_state.attributes.get(
                    ATTR_CONNECTION_TYPE
                )
            if self._attr_interface is None:
                self._attr_interface = old_state.attributes.get(ATTR_INTERFACE)
            if self._attr_ip_address is None:
                self._attr_ip_address = old_state.attributes.get(ATTR_IP)
            self.async_write_ha_state()

    @property
    def mac_address(self) -> str:
        """Return the mac address of the device."""
        return self._mac_address

    @property
    def ip_address(self) -> str:
        """Return the primary ip address of the device."""
        return self._attr_ip_address

    @property
    def hostname(self) -> str:
        """Return hostname of the device."""
        return self._client.router_ip

    @property
    def source_type(self) -> str:
        """Return the source type."""
        return SOURCE_TYPE_ROUTER

    @property
    def icon(self) -> str:
        """Return device icon."""
        return "mdi:lan-connect" if self.is_connected else "mdi:lan-disconnect"

    @property
    def is_connected(self) -> bool:
        """Return true if the device is connected to the router."""
        return self._client.online

    @property
    def extra_state_attributes(self) -> dict[str:Any]:
        """Return extra state attributes."""
        return {
            ATTR_CONNECTION_TYPE: self._attr_connection_type,
            ATTR_INTERFACE: self._attr_interface,
            ATTR_DOWN_KILOBYTES_PER_S: self._client.down_kilobytes_per_s,
            ATTR_UP_KILOBYTES_PER_S: self._client.up_kilobytes_per_s,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._client.router_ip)},
            name="TP-Link Deco",
            manufacturer="TP-Link Deco",
        )

    @callback
    async def async_on_demand_update(self):
        """Request update from coordinator."""
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._update_from_client():
            self.async_write_ha_state()

    def _update_from_client(self) -> None:
        """Update data from client."""
        changed = False
        if self._client.connection_type is not None:
            self._attr_connection_type = self._client.connection_type
            changed = True
        if self._client.interface is not None:
            self._attr_interface = self._client.interface
            changed = True
        if self._client.ip_address is not None:
            self._attr_ip_address = self._client.ip_address
            changed = True
        if self._client.name is not None:
            self._attr_name = self._client.name
            changed = True
        return changed
