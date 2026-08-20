"""Binary sensors for TP-Link Deco."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import wireless_is_enabled
from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .const import SIGNAL_DECO_ADDED
from .const import WIFI_NETWORKS
from .coordinator import TpLinkDeco
from .coordinator import TplinkDecoUpdateCoordinator
from .device import create_device_info

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up binary sensor platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator_decos = data[COORDINATOR_DECOS_KEY]

    tracked_decos = set()

    def add_binary_sensors_for_deco(deco: TpLinkDeco) -> None:
        async_add_entities(
            [
                TplinkDecoInternetOnlineBinarySensor(
                    coordinator_decos,
                    deco.mac,
                ),
                TplinkDecoOnlineBinarySensor(
                    coordinator_decos,
                    deco.mac,
                ),
            ]
        )

    def add_untracked_deco_binary_sensors():
        """Add binary sensors for newly discovered decos."""
        for mac, deco in coordinator_decos.data.decos.items():
            if mac in tracked_decos:
                continue

            add_binary_sensors_for_deco(deco)
            tracked_decos.add(mac)

    add_untracked_deco_binary_sensors()

    coordinator_decos.on_close(
        async_dispatcher_connect(
            hass, SIGNAL_DECO_ADDED, add_untracked_deco_binary_sensors
        )
    )

    await _async_add_wifi_binary_sensors(coordinator_decos, async_add_entities)


async def _async_add_wifi_binary_sensors(coordinator, async_add_entities) -> None:
    """Add read-only on/off status sensors for the Deco's WiFi networks.

    Enabling/disabling WiFi is not supported by the Deco local API (the write
    handler errors server-side), but reading the state works reliably.
    """
    # WiFi sensors attach to the master Deco; skip on satellite-only entries.
    if coordinator.data.master_deco is None:
        _LOGGER.debug("No master Deco for this entry, skipping WiFi status sensors")
        return

    try:
        config = await coordinator.api.async_get_wireless("wlan")
    except Exception as err:  # noqa: BLE001 - skip sensors, don't fail setup
        _LOGGER.warning("Could not read wireless config for WiFi sensors: %s", err)
        return

    entities = []
    for network in WIFI_NETWORKS:
        if wireless_is_enabled(config, network["paths"]) is None:
            continue
        entities.append(DecoWifiBinarySensor(coordinator, network))
    async_add_entities(entities)


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
        )


class DecoWifiBinarySensor(BinarySensorEntity):
    """Read-only on/off status of one of the Deco's WiFi networks."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, network: dict) -> None:
        self.coordinator = coordinator
        self._form = network["form"]
        self._paths = network["paths"]
        self._attr_name = network["name"]
        self._attr_icon = network["icon"]
        self._attr_unique_id = f"tplink_deco_wifi_{network['key']}"
        self._attr_is_on = None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Attach to the master Deco device."""
        master_deco = self.coordinator.data.master_deco
        return create_device_info(master_deco, master_deco)

    async def async_update(self) -> None:
        """Refresh the on/off state from the Deco."""
        # Respect the polling switch so we don't hit the router while paused.
        if self.coordinator.paused:
            return
        try:
            config = await self.coordinator.api.async_get_wireless(self._form)
            self._attr_is_on = wireless_is_enabled(config, self._paths)
            self._attr_available = self._attr_is_on is not None
        except Exception as err:  # noqa: BLE001 - keep last state, mark unavailable
            _LOGGER.debug("Error updating %s WiFi status: %s", self._form, err)
            self._attr_available = False
