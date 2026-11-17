"""Optional read-only mobile WAN usage polling for supported TP-Link Deco models."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import TplinkDecoApi
from .const import DOMAIN
from .coordinator import TplinkDecoUpdateCoordinator
from .coordinator import async_call_and_propagate_config_error

_LOGGER = logging.getLogger(__name__)
MOBILE_DATA_UPDATE_INTERVAL = timedelta(minutes=5)


def supports_mobile_data(device_model: object) -> bool:
    """Detect only router models explicitly marked as mobile 4G/5G."""
    if not isinstance(device_model, str):
        return False
    model = device_model.upper()
    return "4G" in model or "5G" in model


class TplinkDecoMobileDataUpdateCoordinator(DataUpdateCoordinator[int | None]):
    """Refresh optional usage independently of required mesh/client polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        config_entry: ConfigEntry | None,
        deco_coordinator: TplinkDecoUpdateCoordinator,
    ) -> None:
        """Initialize a five-minute, per-config-entry read-only coordinator."""
        self.api = api
        self._deco_coordinator = deco_coordinator
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-mobile-data",
            update_interval=MOBILE_DATA_UPDATE_INTERVAL,
        )
        self.data = None
        self._observed_master_mac = self._current_master_mac()
        self._master_generation = 0
        self._data_owner_mac: str | None = None
        self._data_owner_generation: int | None = None
        if config_entry is not None:
            config_entry.async_on_unload(
                deco_coordinator.async_add_listener(self._handle_deco_update)
            )

    def _current_master_mac(self) -> str | None:
        """Return only a validated current master identifier."""
        snapshot = getattr(self._deco_coordinator, "data", None)
        master = getattr(snapshot, "master_deco", None)
        mac = getattr(master, "mac", None)
        return mac if isinstance(mac, str) and mac else None

    @callback
    def _observe_master(self) -> tuple[str | None, int]:
        """Invalidate a previous owner's usage on every master transition."""
        master_mac = self._current_master_mac()
        if master_mac != self._observed_master_mac:
            self._observed_master_mac = master_mac
            self._master_generation += 1
            self.data = None
            self._data_owner_mac = None
            self._data_owner_generation = None
        return master_mac, self._master_generation

    @callback
    def _handle_deco_update(self) -> None:
        """Invalidate stale usage before master-dependent sensors publish."""
        self._observe_master()

    def has_current_usage(self, master_mac: str) -> bool:
        """Accept a value only from the matching master and refresh generation."""
        active_mac, generation = self._observe_master()
        return (
            active_mac == master_mac
            and self._data_owner_mac == master_mac
            and self._data_owner_generation == generation
            and isinstance(self.data, int)
            and not isinstance(self.data, bool)
        )

    async def _async_update_data(self) -> int | None:
        """Read usage only for a known mobile master without blocking setup."""
        master_mac, generation = self._observe_master()
        if self._deco_coordinator.paused:
            return self.data

        snapshot = getattr(self._deco_coordinator, "data", None)
        master = getattr(snapshot, "master_deco", None)
        if master_mac is None or not supports_mobile_data(
            getattr(master, "device_model", None)
        ):
            self._data_owner_mac = None
            self._data_owner_generation = None
            return None

        try:
            usage = await async_call_and_propagate_config_error(
                self.api.async_get_mobile_data_usage
            )
            if usage is not None and (
                isinstance(usage, bool) or not isinstance(usage, int) or usage < 0
            ):
                raise ValueError("Invalid mobile usage value")
        except ConfigEntryAuthFailed:
            raise
        except Exception as error:
            _LOGGER.debug(
                "Optional mobile usage read failed (%s)", type(error).__name__
            )
        else:
            # An A -> B -> A transition must not revalidate a stale response.
            current_mac, current_generation = self._observe_master()
            if (current_mac, current_generation) == (master_mac, generation):
                if usage is not None:
                    self._data_owner_mac = master_mac
                    self._data_owner_generation = generation
                else:
                    self._data_owner_mac = None
                    self._data_owner_generation = None
                return usage
            return None

        # Never retain sensitive upstream exception text in __context__.
        raise UpdateFailed("Unable to read optional mobile data")
