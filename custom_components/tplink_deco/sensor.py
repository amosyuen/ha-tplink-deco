"""TP-Link Deco."""

import logging
from dataclasses import dataclass
from typing import Any
from typing import Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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


@dataclass(frozen=True, kw_only=True)
class TplinkDecoDiagnosticSensorDescription(SensorEntityDescription):
    """Description of a TP-Link Deco diagnostic sensor."""

    value_fn: Callable[[TpLinkDeco], Any]


DIAGNOSTIC_SENSOR_DESCRIPTIONS: tuple[TplinkDecoDiagnosticSensorDescription, ...] = (
    TplinkDecoDiagnosticSensorDescription(
        key="ip_address",
        name="IP address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda deco: deco.ip_address,
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="bssid_2_4ghz",
        name="BSSID 2.4 GHz",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda deco: deco.bssid_band2_4,
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="bssid_5ghz",
        name="BSSID 5 GHz",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda deco: deco.bssid_band5,
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="connection_type",
        name="Backhaul type",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda deco: (
            deco.connection_type[0]
            if isinstance(deco.connection_type, list) and deco.connection_type
            else deco.connection_type
        ),    
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="backhaul_speed",
        name="Backhaul speed",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        value_fn=lambda deco: deco.backhaul_speed,
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="backhaul_max_speed",
        name="Backhaul max speed",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        value_fn=lambda deco: deco.backhaul_max_speed,
    ),
)   
    
        
async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Setup sensor platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator_decos = data[COORDINATOR_DECOS_KEY]
    coordinator_clients = data[COORDINATOR_CLIENTS_KEY]

    def add_sensors_for_deco(
        deco: TpLinkDeco | None,
    ):
        name_prefix = "Total" if deco is None else deco.name
        unique_id_prefix = (
            f"{coordinator_decos.data.master_deco.mac}_total"
            if deco is None
            else deco.mac
        )

        entities = [
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
        ]


        if deco is not None:
            entities.append(
                TplinkDecoClientCountSensor(
                    coordinator_decos,
                    coordinator_clients,
                    deco.mac,
                )
            )

            for description in DIAGNOSTIC_SENSOR_DESCRIPTIONS:
                value = description.value_fn(deco)

                if value is None or value == "" or value == []:
                    continue

                entities.append(
                    TplinkDecoDiagnosticSensor(
                        coordinator_decos,
                        deco.mac,
                        description,
                    )
                )

        async_add_entities(entities)

    tracked_decos = set()

    @callback
    def add_untracked_deco_sensors():
        """Add new tracker entities for decos."""
        for mac, deco in coordinator_decos.data.decos.items():
            if mac in tracked_decos:
                continue

            _LOGGER.debug(
                "add_untracked_deco_sensors: Adding deco sensors for mac=%s", deco.mac
            )
            add_sensors_for_deco(deco)
            tracked_decos.add(mac)

    add_sensors_for_deco(None)  # Total sensors
    add_untracked_deco_sensors()

    coordinator_decos.on_close(
        async_dispatcher_connect(hass, SIGNAL_DECO_ADDED, add_untracked_deco_sensors)
    )


class TplinkTotalClientDataRateSensor(CoordinatorEntity, SensorEntity):
    """TP-Link total client data rate sensor entity."""

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
        self._update_state()

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

class TplinkDecoClientCountSensor(CoordinatorEntity, SensorEntity):
    """TP-Link Deco connected client count sensor."""

    _attr_has_entity_name = True
    _attr_name = "Connected clients"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        coordinator_clients: TplinkDecoClientUpdateCoordinator,
        deco_mac: str,
    ) -> None:
        self._coordinator_decos = coordinator_decos
        self._deco_mac = deco_mac
        self._attr_unique_id = f"{deco_mac}_client_count"
        super().__init__(coordinator_clients)
        self._update_state()

    @property
    def _deco(self) -> TpLinkDeco:
        """Return current deco object."""
        return self._coordinator_decos.data.decos[self._deco_mac]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return create_device_info(self._deco, self._coordinator_decos.data.master_deco)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Update sensor state."""
        count = 0
        for client in self.coordinator.data.values():
            if client.deco_mac == self._deco_mac:
                count += 1
        self._attr_native_value = count


class TplinkDecoDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """TP-Link Deco diagnostic sensor entity."""

    entity_description: TplinkDecoDiagnosticSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        deco_mac: str,
        description: TplinkDecoDiagnosticSensorDescription,
    ) -> None:
        super().__init__(coordinator_decos)
        self._deco_mac = deco_mac
        self.entity_description = description
        self._attr_unique_id = f"{deco_mac}_{description.key}"
        self._attr_has_entity_name = True

    @property
    def _deco(self) -> TpLinkDeco:
        """Return current deco object."""
        return self.coordinator.data.decos[self._deco_mac]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return create_device_info(self._deco, self.coordinator.data.master_deco)

    @property
    def native_value(self):
        value = self.entity_description.value_fn(self._deco)
        if value is None or value == "" or value == []:
            return None
        return value    
        
