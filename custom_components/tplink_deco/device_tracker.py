"""TP-Link Deco."""
import logging
from typing import Any

from homeassistant.components.device_tracker import SOURCE_TYPE_ROUTER
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.components.device_tracker.const import ATTR_IP
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_HW_VERSION
from homeassistant.const import ATTR_SW_VERSION
from homeassistant.const import ATTR_VIA_DEVICE
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import DEVICE_CLASS_CLIENT
from .const import DEVICE_CLASS_DECO
from .const import DOMAIN
from .const import SIGNAL_CLIENT_ADDED
from .const import SIGNAL_DECO_ADDED
from .coordinator import TpLinkDeco
from .coordinator import TpLinkDecoClient
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)

ATTR_BSSID_BAND2_4 = "bssid_band2_4"
ATTR_BSSID_BAND5 = "bssid_band5"
ATTR_CONNECTION_TYPE = "connection_type"
ATTR_DECO_DEVICE = "deco_device"
ATTR_DECO_MAC = "deco_mac"
ATTR_DEVICE_MODEL = "device_model"
ATTR_DOWN_KILOBYTES_PER_S = "down_kilobytes_per_s"
ATTR_INTERFACE = "interface"
ATTR_INTERNET_ONLINE = "internet_online"
ATTR_MASTER = "master"
ATTR_SIGNAL_BAND2_4 = "signal_band2_4"
ATTR_SIGNAL_BAND5 = "signal_band5"
ATTR_UP_KILOBYTES_PER_S = "up_kilobytes_per_s"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Setup binary_sensor platform."""
    coordinator_decos = hass.data[DOMAIN][entry.entry_id][COORDINATOR_DECOS_KEY]
    coordinator_clients = hass.data[DOMAIN][entry.entry_id][COORDINATOR_CLIENTS_KEY]
    _async_setup_decos(hass, async_add_entities, coordinator_decos)
    _async_setup_clients(
        hass, async_add_entities, coordinator_decos, coordinator_clients
    )


def _async_setup_decos(hass, async_add_entities, coordinator):
    tracked_decos = set()

    @callback
    def add_untracked_decos():
        """Add new tracker entities for clients."""
        new_entities = []

        for mac, deco in coordinator.data.decos.items():
            if mac in tracked_decos:
                continue

            new_entities.append(TplinkDecoDeviceTracker(coordinator, deco))
            tracked_decos.add(mac)

        if new_entities:
            async_add_entities(new_entities)

    add_untracked_decos()
    coordinator.on_close(
        async_dispatcher_connect(hass, SIGNAL_DECO_ADDED, add_untracked_decos)
    )


def _async_setup_clients(
    hass, async_add_entities, coordinator_decos, coordinator_clients
):
    tracked_clients = set()

    @callback
    def add_untracked_clients():
        """Add new tracker entities for clients."""
        new_entities = []

        for mac, client in coordinator_clients.data.items():
            if mac in tracked_clients:
                continue

            new_entities.append(
                TplinkDecoClientDeviceTracker(
                    coordinator_decos, coordinator_clients, client
                )
            )
            tracked_clients.add(mac)

        if new_entities:
            async_add_entities(new_entities)

    add_untracked_clients()
    coordinator_clients.on_close(
        async_dispatcher_connect(hass, SIGNAL_CLIENT_ADDED, add_untracked_clients)
    )


def create_device_info(deco: TpLinkDeco, master_deco: TpLinkDeco) -> DeviceInfo:
    """Return device info."""
    if deco is None:
        return None
    device_info = DeviceInfo(
        id=deco.mac,
        identifiers={(DOMAIN, deco.mac)},
        name=f"{deco.name} Deco",
        manufacturer="TP-Link Deco",
        model=deco.device_model,
        sw_version=deco.sw_version,
        hw_version=deco.hw_version,
    )
    if deco != master_deco:
        device_info[ATTR_VIA_DEVICE] = (DOMAIN, master_deco.mac)

    return device_info


class TplinkDecoDeviceTracker(CoordinatorEntity, RestoreEntity, ScannerEntity):
    """TP Link Deco Entity."""

    def __init__(
        self, coordinator: TplinkDecoUpdateCoordinator, deco: TpLinkDeco
    ) -> None:
        """Initialize a TP-Link Deco device."""
        self._deco = deco
        self._mac_address = deco.mac

        self._attr_hw_version = None
        self._attr_sw_version = None
        self._attr_device_model = None

        self._attr_ip_address = None
        self._attr_name = None
        self._attr_online = None
        self._attr_internet_online = None
        self._attr_master = None
        self._attr_connection_type = None
        self._attr_bssid_band2_4 = None
        self._attr_bssid_band5 = None
        self._attr_signal_band2_4 = None
        self._attr_signal_band5 = None

        self._update_from_deco()
        super().__init__(coordinator)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Restore old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            if self._attr_hw_version is None:
                self._attr_hw_version = self._deco.hw_version
            if self._attr_sw_version is None:
                self._attr_sw_version = self._deco.sw_version
            if self._attr_device_model is None:
                self._attr_device_model = self._deco.device_model

            if self._attr_ip_address is None:
                self._attr_ip_address = self._deco.ip_address
            if self._attr_name is None:
                self._attr_name = self._deco.name
            if self._attr_master is None:
                self._attr_master = self._deco.master
            if self._attr_connection_type is None:
                self._attr_connection_type = self._deco.connection_type

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
        return self._deco.online

    @property
    def extra_state_attributes(self) -> dict[str:Any]:
        """Return extra state attributes."""
        return {
            ATTR_BSSID_BAND2_4: self._deco.bssid_band2_4,
            ATTR_BSSID_BAND5: self._deco.bssid_band5,
            ATTR_CONNECTION_TYPE: self._attr_connection_type,
            ATTR_DEVICE_MODEL: self._attr_device_model,
            ATTR_HW_VERSION: self._attr_hw_version,
            ATTR_INTERNET_ONLINE: self._deco.internet_online,
            ATTR_MASTER: self._attr_master,
            ATTR_SIGNAL_BAND2_4: self._deco.signal_band2_4,
            ATTR_SIGNAL_BAND5: self._deco.signal_band5,
            ATTR_SW_VERSION: self._attr_sw_version,
        }

    @property
    def device_class(self) -> str:
        """Return device class."""
        return DEVICE_CLASS_DECO

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return create_device_info(self._deco, self.coordinator.data.master_deco)

    @callback
    async def async_on_demand_update(self):
        """Request update from coordinator."""
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._update_from_deco():
            self.async_write_ha_state()

    def _update_from_deco(self) -> None:
        """Update data from deco."""
        changed = False
        if self._deco.hw_version is not None:
            self._attr_hw_version = self._deco.hw_version
            changed = True
        if self._deco.sw_version is not None:
            self._attr_sw_version = self._deco.sw_version
            changed = True
        if self._deco.device_model is not None:
            self._attr_device_model = self._deco.device_model
            changed = True

        if self._deco.ip_address is not None:
            self._attr_ip_address = self._deco.ip_address
            changed = True
        if self._deco.name is not None:
            self._attr_name = f"{self._deco.name} Deco"
            changed = True
        if self._deco.master is not None:
            self._attr_master = self._deco.master
            changed = True
        if self._deco.connection_type is not None:
            self._attr_connection_type = self._deco.connection_type
            changed = True

        return changed


class TplinkDecoClientDeviceTracker(CoordinatorEntity, RestoreEntity, ScannerEntity):
    """TP Link Deco Entity."""

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        coordinator_clients: TplinkDecoClientUpdateCoordinator,
        client: TpLinkDecoClient,
    ) -> None:
        """Initialize a TP-Link Deco device."""
        self._attr_connection_type = None
        self._attr_deco_mac = None
        self._attr_interface = None
        self._attr_ip_address = None
        self._attr_name = None
        self._client = client
        self._coordinator_decos = coordinator_decos
        self._mac_address = client.mac
        self._update_from_client()
        super().__init__(coordinator_clients)

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
            if self._attr_deco_mac is None:
                self._attr_deco_mac = old_state.attributes.get(ATTR_DECO_MAC)
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
        deco = self._coordinator_decos.data.decos.get(self._attr_deco_mac)
        return {
            ATTR_CONNECTION_TYPE: self._attr_connection_type,
            ATTR_INTERFACE: self._attr_interface,
            ATTR_DOWN_KILOBYTES_PER_S: self._client.down_kilobytes_per_s,
            ATTR_UP_KILOBYTES_PER_S: self._client.up_kilobytes_per_s,
            ATTR_DECO_DEVICE: None if deco is None else deco.name,
            ATTR_DECO_MAC: self._attr_deco_mac,
        }

    @property
    def device_class(self) -> str:
        """Return device class."""
        return DEVICE_CLASS_CLIENT

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        deco = self._coordinator_decos.data.decos.get(self._attr_deco_mac)
        return create_device_info(deco, self._coordinator_decos.data.master_deco)

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
        if self._client.deco_mac is not None:
            self._attr_deco_mac = self._client.deco_mac
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
