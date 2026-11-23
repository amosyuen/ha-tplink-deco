"""Binary sensors for TP-Link Deco."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_DECOS_KEY
from .const import COORDINATOR_WIRELESS_KEY
from .const import DOMAIN
from .const import SIGNAL_DECO_ADDED
from .coordinator import TpLinkDeco
from .coordinator import TplinkDecoUpdateCoordinator
from .device import create_device_info
from .wireless import TplinkDecoWirelessUpdateCoordinator
from .wireless import WIRELESS_NETWORKS
from .wireless import WirelessNetworkDescription
from .wireless import wireless_ssid_attributes

STANDALONE_BINARY_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="standalone",
    name="Standalone Master",
    translation_key="standalone",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up binary sensor platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator_decos = data[COORDINATOR_DECOS_KEY]

    tracked_decos: set[str] = set()
    tracked_standalone: set[str] = set()

    @callback
    def add_untracked_deco_binary_sensors() -> None:
        """Register newly available binary sensors without duplicates."""
        entities: list[BinarySensorEntity] = []
        for mac, deco in coordinator_decos.data.decos.items():
            if mac not in tracked_decos:
                entities.extend(
                    (
                        TplinkDecoInternetOnlineBinarySensor(coordinator_decos, mac),
                        TplinkDecoOnlineBinarySensor(coordinator_decos, mac),
                    )
                )
                tracked_decos.add(mac)

            if mac not in tracked_standalone and isinstance(
                deco.diagnostic_values.get("standalone"), bool
            ):
                entities.append(
                    TplinkDecoStandaloneBinarySensor(coordinator_decos, mac)
                )
                tracked_standalone.add(mac)

        if entities:
            async_add_entities(entities)

    add_untracked_deco_binary_sensors()

    coordinator_decos.on_close(
        async_dispatcher_connect(
            hass, SIGNAL_DECO_ADDED, add_untracked_deco_binary_sensors
        )
    )
    # New validated roles may appear without a new-node dispatcher signal.
    coordinator_decos.on_close(
        coordinator_decos.async_add_listener(add_untracked_deco_binary_sensors)
    )

    wireless_coordinator = data.get(COORDINATOR_WIRELESS_KEY)
    if wireless_coordinator is None:
        return

    tracked_networks: set[tuple[str, str]] = set()

    @callback
    def add_wireless_binary_sensors() -> None:
        """Register only supported wireless networks once per master."""
        master_deco = coordinator_decos.data.master_deco
        if master_deco is None or not isinstance(wireless_coordinator.data, dict):
            return

        entities = []
        for network in WIRELESS_NETWORKS:
            identity = (master_deco.mac, network.key)
            if (
                network.key in wireless_coordinator.data
                and identity not in tracked_networks
            ):
                entities.append(
                    TplinkDecoWirelessBinarySensor(
                        wireless_coordinator, coordinator_decos, master_deco, network
                    )
                )
                tracked_networks.add(identity)

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        wireless_coordinator.async_add_listener(add_wireless_binary_sensors)
    )
    coordinator_decos.on_close(
        async_dispatcher_connect(hass, SIGNAL_DECO_ADDED, add_wireless_binary_sensors)
    )
    add_wireless_binary_sensors()


class TplinkDecoStandaloneBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Report whether a known Deco is the only master in its mesh."""

    _attr_has_entity_name = True
    entity_description = STANDALONE_BINARY_SENSOR_DESCRIPTION

    def __init__(
        self, coordinator_decos: TplinkDecoUpdateCoordinator, deco_mac: str
    ) -> None:
        """Bind the diagnostic to its Deco with a stable MAC-based unique ID."""
        super().__init__(coordinator_decos)
        self._deco_mac = deco_mac
        self._attr_unique_id = f"{deco_mac}_standalone"

    @property
    def _deco(self) -> TpLinkDeco | None:
        """Return the current Deco without inventing missing nodes."""
        return self.coordinator.data.decos.get(self._deco_mac)

    @property
    def is_on(self) -> bool | None:
        """Preserve confirmed true, false and unknown topology states."""
        deco = self._deco
        if deco is None:
            return None
        value = deco.diagnostic_values.get("standalone")
        return value if isinstance(value, bool) else None

    @property
    def available(self) -> bool:
        """Require a successful refresh and a confirmed standalone flag."""
        return super().available and self.is_on is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Associate the binary sensor with its original Deco device."""
        deco = self._deco
        if deco is None:
            return None
        return create_device_info(
            deco, self.coordinator.data.master_deco, self.coordinator
        )


class TplinkDecoInternetOnlineBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """TP-Link Deco internet online binary sensor."""

    _attr_has_entity_name = True
    _attr_name = "Internet online"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator_decos: TplinkDecoUpdateCoordinator,
        deco_mac: str,
    ) -> None:
        super().__init__(coordinator_decos)
        self._deco_mac = deco_mac
        self._attr_unique_id = f"{deco_mac}_internet_online"

    @property
    def _deco(self) -> TpLinkDeco | None:
        """Return current deco object."""
        return self.coordinator.data.decos.get(self._deco_mac)

    @property
    def is_on(self) -> bool:
        """Return true if internet is online."""
        deco = self._deco
        if deco is None:
            return False

        value = deco.internet_online

        if isinstance(value, str):
            return value.lower() in ("online", "true", "1", "yes")

        return bool(value)

    @property
    def available(self) -> bool:
        return True

    @property
    def device_info(self):
        """Return device info."""
        deco = self._deco
        if deco is None:
            return None

        return create_device_info(
            deco,
            self.coordinator.data.master_deco,
            self.coordinator,
        )


class TplinkDecoOnlineBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """TP-Link Deco online (mesh/backhaul) status."""

    _attr_has_entity_name = True
    _attr_name = "Deco online"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator_decos, deco_mac):
        super().__init__(coordinator_decos)
        self._deco_mac = deco_mac
        self._attr_unique_id = f"{deco_mac}_online"

    @property
    def _deco(self):
        return self.coordinator.data.decos.get(self._deco_mac)

    @property
    def is_on(self):
        deco = self._deco
        if deco is None:
            return False
        return bool(deco.online)

    @property
    def available(self):
        return True

    @property
    def device_info(self):
        deco = self._deco
        if deco is None:
            return None

        return create_device_info(
            deco,
            self.coordinator.data.master_deco,
            self.coordinator,
        )


class TplinkDecoWirelessBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Read-only enabled state for a known Deco WiFi network."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TplinkDecoWirelessUpdateCoordinator,
        deco_coordinator: TplinkDecoUpdateCoordinator,
        master_deco: TpLinkDeco,
        description: WirelessNetworkDescription,
    ) -> None:
        """Associate the network with the actual master Deco device."""
        super().__init__(coordinator)
        self._deco_coordinator = deco_coordinator
        self._master_deco = master_deco
        self.entity_description = description
        self._attr_unique_id = f"{master_deco.mac}_wifi_{description.key}"

    async def async_added_to_hass(self) -> None:
        """Listen for master changes independently of wireless updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._deco_coordinator.async_add_listener(self._handle_deco_update)
        )

    @callback
    def _handle_deco_update(self) -> None:
        """Re-evaluate availability when the master Deco changes."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Require both the original master and a supported current network."""
        deco_data = self._deco_coordinator.data
        active_master = getattr(deco_data, "master_deco", None)
        return (
            active_master is not None
            and active_master.mac == self._master_deco.mac
            and super().available
            and isinstance(self.coordinator.data, dict)
            and self.entity_description.key in self.coordinator.data
        )

    @property
    def is_on(self) -> bool | None:
        """Return the latest recognized enable flag."""
        data = self.coordinator.data
        return data.get(self.entity_description.key) if isinstance(data, dict) else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return opt-in WiFi names only when the current network is available."""
        if self.coordinator.expose_ssids is not True or not self.available:
            return None
        names = self.coordinator.ssid_names_for_master(
            self._master_deco.mac, self.entity_description.key
        )
        return wireless_ssid_attributes(names) if names else None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Re-use the master Deco's stable device-registry identity."""
        return create_device_info(
            self._master_deco, self._master_deco, self._deco_coordinator
        )
