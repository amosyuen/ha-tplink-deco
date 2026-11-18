"""TP-Link Deco sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.const import UnitOfDataRate
from homeassistant.const import UnitOfInformation
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import COORDINATOR_MOBILE_KEY
from .const import DOMAIN
from .const import SIGNAL_DECO_ADDED
from .coordinator import TpLinkDeco
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator
from .device import create_device_info
from .mobile import TplinkDecoMobileDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TplinkDecoDiagnosticSensorDescription(SensorEntityDescription):
    """Description of a TP-Link Deco diagnostic sensor."""

    value_fn: Callable[[TpLinkDeco], Any]
    requires_value: bool = False


@dataclass(frozen=True, kw_only=True)
class TplinkCoordinatorHealthSensorDescription(SensorEntityDescription):
    """Describe a privacy-safe, opt-in coordinator health metric."""

    coordinator_key: str
    value_fn: Callable[[Any], Any]


def _restored_diagnostic_description(
    key: str, name: str
) -> TplinkDecoDiagnosticSensorDescription:
    """Keep the extra branch's sensor identity with validated optional values."""
    return TplinkDecoDiagnosticSensorDescription(
        key=key,
        name=name,
        translation_key=key,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        requires_value=True,
        value_fn=lambda deco: deco.diagnostic_values.get(key),
    )


RESTORED_DIAGNOSTIC_SENSOR_DESCRIPTIONS = tuple(
    _restored_diagnostic_description(key, name)
    for key, name in (
        ("group_status", "Group Status"),
        ("inet", "Internet Status"),
        ("nickname", "Nickname"),
        ("role", "Role"),
        ("master", "Master Deco"),
        ("slave", "Slave Deco"),
        ("standalone", "Standalone Master"),
        ("signal_level", "Signal level"),
        ("signal_level24", "Signal level 2.4Ghz"),
        ("signal_level5", "Signal level 5Ghz"),
        ("interface", "Interface"),
        ("previous", "MAC of upstream node"),
        ("client_mesh", "Client mesh"),
        ("bssid_sta_2g", "BSSID 2.4 GHz (Station)"),
        ("bssid_sta_5g", "BSSID 5 GHz (Station)"),
        ("set_gateway_support", "Set gateway support"),
        ("topology", "Topology"),
    )
)


DIAGNOSTIC_SENSOR_DESCRIPTIONS: tuple[TplinkDecoDiagnosticSensorDescription, ...] = (
    TplinkDecoDiagnosticSensorDescription(
        key="device_type",
        name="Device Type",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda deco: deco.device_type,
    ),
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
    *RESTORED_DIAGNOSTIC_SENSOR_DESCRIPTIONS,
)


COORDINATOR_HEALTH_SENSOR_DESCRIPTIONS: tuple[
    TplinkCoordinatorHealthSensorDescription, ...
] = (
    TplinkCoordinatorHealthSensorDescription(
        key="deco_last_successful_update",
        name="Deco last successful update",
        coordinator_key=COORDINATOR_DECOS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator: coordinator.health.last_successful_update,
    ),
    TplinkCoordinatorHealthSensorDescription(
        key="deco_response_time",
        name="Deco API response time",
        coordinator_key=COORDINATOR_DECOS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.health.response_time_ms,
    ),
    TplinkCoordinatorHealthSensorDescription(
        key="deco_last_error",
        name="Deco last error",
        coordinator_key=COORDINATOR_DECOS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.health.last_error,
    ),
    TplinkCoordinatorHealthSensorDescription(
        key="client_last_successful_update",
        name="Client last successful update",
        coordinator_key=COORDINATOR_CLIENTS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator: coordinator.health.last_successful_update,
    ),
    TplinkCoordinatorHealthSensorDescription(
        key="client_response_time",
        name="Client API response time",
        coordinator_key=COORDINATOR_CLIENTS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator: coordinator.health.response_time_ms,
    ),
    TplinkCoordinatorHealthSensorDescription(
        key="client_timeout_count",
        name="Client timeouts",
        coordinator_key=COORDINATOR_CLIENTS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.health.timeout_count,
    ),
    TplinkCoordinatorHealthSensorDescription(
        key="client_query_mode",
        name="Client query mode",
        coordinator_key=COORDINATOR_CLIENTS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.client_query_mode,
    ),
    TplinkCoordinatorHealthSensorDescription(
        key="client_last_error",
        name="Client last error",
        coordinator_key=COORDINATOR_CLIENTS_KEY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.health.last_error,
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
    coordinator_clients: TplinkDecoClientUpdateCoordinator = data[
        COORDINATOR_CLIENTS_KEY
    ]
    coordinator_mobile: TplinkDecoMobileDataUpdateCoordinator | None = data.get(
        COORDINATOR_MOBILE_KEY
    )

    tracked_macs: set[str] = set()
    tracked_diagnostics: set[tuple[str, str]] = set()
    tracked_client_count_macs: set[str] = set()

    def _build_entities_for_deco(deco: TpLinkDeco | None) -> list[SensorEntity]:
        """Build the list of sensor entities for a single deco (or totals)."""
        if deco is None:
            master = coordinator_decos.data.master_deco
            if master is None:
                _LOGGER.warning("Master Deco not found; skipping total sensor creation")
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

        return entities

    @callback
    def _add_untracked_deco_sensors() -> None:
        """Discover new Deco throughput and newly supported diagnostic sensors."""
        new_entities: list[SensorEntity] = []
        for mac, deco in coordinator_decos.data.decos.items():
            if mac not in tracked_macs:
                _LOGGER.debug("Adding sensors for a discovered Deco node")
                new_entities.extend(_build_entities_for_deco(deco))
                tracked_macs.add(mac)

            for description in DIAGNOSTIC_SENSOR_DESCRIPTIONS:
                sensor_key = (mac, description.key)
                if sensor_key in tracked_diagnostics or _is_empty(
                    description.value_fn(deco)
                ):
                    continue
                new_entities.append(
                    TplinkDecoDiagnosticSensor(
                        coordinator_decos=coordinator_decos,
                        deco_mac=mac,
                        description=description,
                    )
                )
                tracked_diagnostics.add(sensor_key)

        if new_entities:
            async_add_entities(new_entities)

    # The initial inventory can omit optional fields which appear on later
    # device-list/performance updates. Retry only unregistered diagnostics.
    coordinator_decos.on_close(
        coordinator_decos.async_add_listener(_add_untracked_deco_sensors)
    )

    total_sensors_added = False

    @callback
    def _add_totals_when_master_available() -> None:
        """Register network totals once a master Deco is available."""
        nonlocal total_sensors_added

        if total_sensors_added or coordinator_decos.data.master_deco is None:
            return

        total_entities = _build_entities_for_deco(None)
        master = coordinator_decos.data.master_deco
        health_entities: list[SensorEntity] = [
            TplinkCoordinatorHealthSensor(
                coordinator_decos=coordinator_decos,
                coordinator=data[description.coordinator_key],
                master_deco_mac=master.mac,
                description=description,
            )
            for description in COORDINATOR_HEALTH_SENSOR_DESCRIPTIONS
        ]
        if total_entities:
            async_add_entities([*total_entities, *health_entities])
            total_sensors_added = True

    # The coordinator listener runs after the new device-list data is stored.
    # SIGNAL_DECO_ADDED can fire before that data is assigned.
    _add_totals_when_master_available()
    coordinator_decos.on_close(
        coordinator_decos.async_add_listener(_add_totals_when_master_available)
    )

    # Per-deco sensors for already-known decos
    _add_untracked_deco_sensors()

    # Per-deco sensors for decos discovered later
    coordinator_decos.on_close(
        async_dispatcher_connect(hass, SIGNAL_DECO_ADDED, _add_untracked_deco_sensors)
    )

    @callback
    def _add_untracked_client_counts() -> None:
        """Publish client counts only after a valid poll of the same Deco."""
        if not coordinator_clients.has_successful_refresh:
            return

        new_entities: list[SensorEntity] = []
        for mac in coordinator_decos.data.decos:
            if (
                mac in tracked_client_count_macs
                or mac not in coordinator_clients.successfully_polled_deco_macs
            ):
                continue
            new_entities.append(
                TplinkDecoClientCountSensor(
                    coordinator_decos=coordinator_decos,
                    coordinator_clients=coordinator_clients,
                    deco_mac=mac,
                )
            )
            tracked_client_count_macs.add(mac)

        if new_entities:
            async_add_entities(new_entities)

    # The first client refresh can complete before sensor-platform setup.
    # Later client refreshes can confirm a newly discovered or recovering node.
    _add_untracked_client_counts()
    coordinator_clients.on_close(
        coordinator_clients.async_add_listener(_add_untracked_client_counts)
    )

    # Register mobile usage only after a supported master's successful read.
    # Each master receives a stable unique ID and previous owners go unavailable.
    if coordinator_mobile is not None:
        mobile_sensor_macs: set[str] = set()

        @callback
        def _add_mobile_sensor() -> None:
            """Discover supported mobile usage without duplicate entities."""
            master = coordinator_decos.data.master_deco
            if (
                master is None
                or master.mac in mobile_sensor_macs
                or not coordinator_mobile.has_current_usage(master.mac)
            ):
                return
            mobile_sensor_macs.add(master.mac)
            async_add_entities(
                [
                    TplinkMobileDataUsageSensor(
                        coordinator_decos, coordinator_mobile, master.mac
                    )
                ]
            )

        entry.async_on_unload(coordinator_mobile.async_add_listener(_add_mobile_sensor))
        _add_mobile_sensor()


class TplinkMobileDataUsageSensor(CoordinatorEntity, SensorEntity):
    """Read-only mobile WAN usage for the master that supplied the value."""

    _attr_has_entity_name = True
    _attr_translation_key = "mobile_data_usage"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.KIBIBYTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        coordinator_mobile: TplinkDecoMobileDataUpdateCoordinator,
        master_mac: str,
    ) -> None:
        """Keep the per-master sensor's MAC-based entity ID stable."""
        super().__init__(coordinator_mobile)
        self._deco_coordinator = coordinator_decos
        self._master_mac = master_mac
        self._attr_unique_id = f"{master_mac}_mobile_data_usage"

    async def async_added_to_hass(self) -> None:
        """Update availability immediately if the mesh master changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._deco_coordinator.async_add_listener(self._handle_deco_update)
        )

    @callback
    def _handle_deco_update(self) -> None:
        """Re-evaluate the current owner without exposing a stale value."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Hide old-master values after any master-generation transition."""
        return super().available and self.coordinator.has_current_usage(
            self._master_mac
        )

    @property
    def native_value(self) -> int | None:
        """Return a current, validated usage value, including genuine zero."""
        return self.coordinator.data if self.available else None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Associate usage with the existing master Deco device."""
        master = self._deco_coordinator.data.decos.get(self._master_mac)
        return (
            create_device_info(master, master, self._deco_coordinator)
            if master is not None
            else None
        )


class TplinkCoordinatorHealthSensor(SensorEntity):
    """Optional coordinator health diagnostic linked to the master Deco."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: TplinkCoordinatorHealthSensorDescription

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        coordinator: TplinkDecoUpdateCoordinator | TplinkDecoClientUpdateCoordinator,
        master_deco_mac: str,
        description: TplinkCoordinatorHealthSensorDescription,
    ) -> None:
        """Create a stable, per-master coordinator health sensor."""
        super().__init__()
        self._coordinator = coordinator
        self._coordinator_decos = coordinator_decos
        self._master_deco_mac = master_deco_mac
        self.entity_description = description
        self._attr_unique_id = f"{master_deco_mac}_{description.key}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to health-only updates without polling unrelated entities."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.health.async_add_listener(self._handle_health_update)
        )

    @callback
    def _handle_health_update(self) -> None:
        """Write a fresh state on every health change, including repeated errors."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Expose the last recorded error even when coordinator polling fails."""
        return True

    @property
    def device_info(self) -> DeviceInfo | None:
        """Associate the diagnostic with its original master Deco."""
        master = self._coordinator_decos.data.decos.get(self._master_deco_mac)
        return create_device_info(master, master, self._coordinator_decos)

    @property
    def native_value(self) -> Any:
        """Return recorded coordinator metadata, never raw API responses."""
        return self.entity_description.value_fn(self._coordinator)


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
        return create_device_info(self._deco or master, master, self._coordinator_decos)

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
            if client.online
            and (self._deco is None or client.deco_mac == self._deco.mac)
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
        return create_device_info(
            self._deco,
            self._coordinator_decos.data.master_deco,
            self._coordinator_decos,
        )

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
            if client.deco_mac == self._deco_mac and client.online
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
    def _deco(self) -> TpLinkDeco | None:
        """Return the current deco object."""
        return self.coordinator.data.decos.get(self._deco_mac)

    @property
    def available(self) -> bool:
        """Keep restored diagnostics unavailable without a live, usable value."""
        return super().available and (
            not self.entity_description.requires_value or self.native_value is not None
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info."""
        return create_device_info(
            self._deco, self.coordinator.data.master_deco, self.coordinator
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value, or None if absent."""
        deco = self._deco
        if deco is None:
            return None
        value = self.entity_description.value_fn(deco)
        return None if _is_empty(value) else value
