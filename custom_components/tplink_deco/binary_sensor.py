"""Binary sensors for TP-Link Deco."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .const import SIGNAL_DECO_ADDED
from .coordinator import TpLinkDeco
from .coordinator import TplinkDecoUpdateCoordinator
from .device import create_device_info


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
