"""TP-Link Deco."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfDataRate
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .const import SIGNAL_DECO_ADDED
from .coordinator import TpLinkDeco
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator
from .device import create_device_info

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator_decos = data[COORDINATOR_DECOS_KEY]
    coordinator_clients = data[COORDINATOR_CLIENTS_KEY]

    entities = []

    # 🔥 Sensor Internet Stats
    entities.append(TplinkInternetStatsSensor(coordinator_decos))

    # 🔥 Sensors existants (débits)
    def add_sensors_for_deco(deco):
        name_prefix = "Total" if deco is None else deco.name
        unique_id_prefix = (
            f"{coordinator_decos.data.master_deco.mac}_total"
            if deco is None else deco.mac
        )
        entities.extend([
            TplinkTotalClientDataRateSensor(
                coordinator_decos,
                coordinator_clients,
                f"{name_prefix} Down",
                f"{unique_id_prefix}_down",
                "down_kilobytes_per_s",
                deco,
            ),
            TplinkTotalClientDataRateSensor(
                coordinator_decos,
                coordinator_clients,
                f"{name_prefix} Up",
                f"{unique_id_prefix}_up",
                "up_kilobytes_per_s",
                deco,
            ),
        ])

    # Total
    add_sensors_for_deco(None)

    # Par Deco
    for deco in coordinator_decos.data.decos.values():
        add_sensors_for_deco(deco)

    async_add_entities(entities)

    tracked_decos = set()

    @callback
    def add_untracked_deco_sensors():
        """Add new tracker entities for clients."""
        new_entities = []

        for mac, deco in coordinator_decos.data.decos.items():
            if mac in tracked_decos:
                continue

            _LOGGER.debug(
                "add_untracked_deco_sensors: Adding deco sensors for mac=%s", deco.mac
            )
            add_sensors_for_deco(deco)
            tracked_decos.add(mac)

        if new_entities:
            async_add_entities(new_entities)

    add_sensors_for_deco(None)  # Total
    add_untracked_deco_sensors()

    coordinator_decos.on_close(
        async_dispatcher_connect(hass, SIGNAL_DECO_ADDED, add_untracked_deco_sensors)
    )

class TplinkTotalClientDataRateSensor(CoordinatorEntity, SensorEntity):
    """TP Link Total Client Data Rate Sensor Entity."""

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        coordinator_clients: TplinkDecoClientUpdateCoordinator,
        name: str,
        unique_id: str,
        client_attribute: str,
        deco: TpLinkDeco | None,
    ) -> None:
        self._coordinator_decos = coordinator_decos
        self._client_attribute = client_attribute
        self._deco = deco

        self._attr_device_class = SensorDeviceClass.DATA_RATE
        self._attr_name = name
        self._attr_native_unit_of_measurement = UnitOfDataRate.KILOBYTES_PER_SECOND
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = unique_id
        super().__init__(coordinator_clients)
        self._update_state()  # Must happen after init

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        master_deco = self._coordinator_decos.data.master_deco
        return create_device_info(self._deco or master_deco, master_deco)

    @callback
    async def async_on_demand_update(self):
        """Request update from coordinator."""
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Handle updated data from the coordinator."""
        state = 0.0
        for client in self.coordinator.data.values():
            if self._deco is None or client.deco_mac == self._deco.mac:
                state += getattr(client, self._client_attribute)
        self._attr_native_value = state
        
class TplinkInternetStatsSensor(CoordinatorEntity, SensorEntity):
    """Sensor regroupant toutes les stats internet du Deco."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Internet Stats"
        self._attr_unique_id = "internet_stats"

    @property
    def device_info(self):
        master = self.coordinator.data.master_deco
        return create_device_info(master, master)

    @property
    def native_value(self):
        # Valeur principale (tu peux choisir ce que tu veux)
        stats = self.coordinator.data.internet_stats
        return stats.get("download_speed")  # ou None

    @property
    def extra_state_attributes(self):
        # 🔥 Toutes les valeurs renvoyées par async_get_internet_stats()
        return self.coordinator.data.internet_stats
        
