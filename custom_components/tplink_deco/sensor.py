"""TP-Link Deco sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfDataRate
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    COORDINATOR_CLIENTS_KEY,
    COORDINATOR_DECOS_KEY,
    DOMAIN,
    SIGNAL_DECO_ADDED,
)
from .coordinator import (
    TpLinkDeco,
    TplinkDecoClientUpdateCoordinator,
    TplinkDecoUpdateCoordinator,
)
from .device import create_device_info

_LOGGER = logging.getLogger(__name__)


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
    TplinkDecoDiagnosticSensorDescription(
        key="cpu_usage",
        name="CPU usage",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda deco: deco.cpu_usage,
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="cpu_usage_raw",
        name="CPU usage raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda deco: deco.cpu_usage_raw,
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="mem_usage",
        name="Memory usage",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda deco: deco.mem_usage,
    ),
    TplinkDecoDiagnosticSensorDescription(
        key="mem_usage_raw",
        name="Memory usage raw",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda deco: deco.mem_usage_raw,
    ),
)


def _is_empty(value: Any) -> bool:
    """Return True if value should be treated as absent."""
    return value is None or value == "" or value == []


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator_decos: TplinkDecoUpdateCoordinator = data[COORDINATOR_DECOS_KEY]
    coordinator_clients: TplinkDecoClientUpdateCoordinator = data[COORDINATOR_CLIENTS_KEY]

    tracked_macs: set[str] = set()

    def _build_entities_for_deco(deco: TpLinkDeco | None) -> list[SensorEntity]:
        """Build the list of sensor entities for a single deco (or totals)."""
        if deco is None:
            master = coordinator_decos.data.master_deco
            if master is None:
                _LOGGER.warning(
                    "Master Deco not found; skipping total sensor creation"
                )
                return []
            name_prefix = "Total"
            unique_id_prefix = f"{master.mac}_total"
        else:
            name_prefix = deco.name
            unique_id_prefix = deco.mac

        entities: list[SensorEntity] = [
            TplinkTotalClientDataRateSensor(
                coordinator_decos=coordinator_decos,
                coordinator_clients=coordinator_clients,
                name=f"{name_prefix} Down",
                unique_id=f"{unique_id_prefix}_down",
                client_attribute="down_kilobytes_per_s",
                deco=deco,
            ),
            TplinkTotalClientDataRateSensor(
                coordinator_decos=coordinator_decos,
                coordinator_clients=coordinator_clients,
                name=f"{name_prefix} Up",
                unique_id=f"{unique_id_prefix}_up",
                client_attribute="up_kilobytes_per_s",
                deco=deco,
            ),
        ]

        if deco is not None:
            entities.append(
                TplinkDecoClientCountSensor(
                    coordinator_decos=coordinator_decos,
                    coordinator_clients=coordinator_clients,
                    deco_mac=deco.mac,
                )
            )
            entities.extend(
                TplinkDecoDiagnosticSensor(
                    coordinator_decos=coordinator_decos,
                    deco_mac=deco.mac,
                    description=description,
                )
                for description in DIAGNOSTIC_SENSOR_DESCRIPTIONS
                if not _is_empty(description.value_fn(deco))
            )

        return entities

    @callback
    def _add_untracked_deco_sensors() -> None:
        """Add sensor entities for any decos not yet tracked."""
        new_entities: list[SensorEntity] = []
        for mac, deco in coordinator_decos.data.decos.items():
            if mac in tracked_macs:
                continue
            _LOGGER.debug("Adding sensors for deco mac=%s", mac)
            new_entities.extend(_build_entities_for_deco(deco))
            tracked_macs.add(mac)

        if new_entities:
            async_add_entities(new_entities)

    # Total (network-wide) sensors
    total_entities = _build_entities_for_deco(None)
    if total_entities:
        async_add_entities(total_entities)

    # Per-deco sensors for already-known decos
    _add_untracked_deco_sensors()

    # Per-deco sensors for decos discovered later
    coordinator_decos.on_close(
        async_dispatcher_connect(hass, SIGNAL_DECO_ADDED, _add_untracked_deco_sensors)
    )


class TplinkTotalClientDataRateSensor(CoordinatorEntity, SensorEntity):
    """Sensor reporting the total data rate across all (or one) deco's clients."""

    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.KILOBYTES_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        coordinator_clients: TplinkDecoClientUpdateCoordinator,
        name: str,
        unique_id: str,
        client_attribute: str,
        deco: TpLinkDeco | None,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator_clients)
        self._coordinator_decos = coordinator_decos
        self._client_attribute = client_attribute
        self._deco = deco
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._update_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        master = self._coordinator_decos.data.master_deco
        return create_device_info(self._deco or master, master)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Recalculate the aggregated data rate."""
        self._attr_native_value = sum(
            getattr(client, self._client_attribute)
            for client in self.coordinator.data.values()
            if self._deco is None or client.deco_mac == self._deco.mac
        )


class TplinkDecoClientCountSensor(CoordinatorEntity, SensorEntity):
    """Sensor reporting the number of clients connected to a single deco."""

    _attr_has_entity_name = True
    _attr_name = "Connected clients"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        coordinator_clients: TplinkDecoClientUpdateCoordinator,
        deco_mac: str,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator_clients)
        self._coordinator_decos = coordinator_decos
        self._deco_mac = deco_mac
        self._attr_unique_id = f"{deco_mac}_client_count"
        self._update_state()

    @property
    def _deco(self) -> TpLinkDeco:
        """Return the current deco object."""
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
        """Count clients connected to this deco."""
        self._attr_native_value = sum(
            1
            for client in self.coordinator.data.values()
            if client.deco_mac == self._deco_mac
        )


class TplinkDecoDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing a single diagnostic attribute of a deco node."""

    _attr_has_entity_name = True
    entity_description: TplinkDecoDiagnosticSensorDescription

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        deco_mac: str,
        description: TplinkDecoDiagnosticSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator_decos)
        self._deco_mac = deco_mac
        self.entity_description = description
        self._attr_unique_id = f"{deco_mac}_{description.key}"

    @property
    def _deco(self) -> TpLinkDeco:
        """Return the current deco object."""
        return self.coordinator.data.decos[self._deco_mac]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return create_device_info(self._deco, self.coordinator.data.master_deco)

    @property
    def native_value(self) -> Any:
        """Return the sensor value, or None if absent."""
        value = self.entity_description.value_fn(self._deco)
        return None if _is_empty(value) else value
