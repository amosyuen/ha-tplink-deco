"""Optional mobile data usage coordinator for TP-Link Deco."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import TplinkDecoApi
from .const import DOMAIN
from .coordinator import TplinkDecoUpdateCoordinator
from .coordinator import async_call_and_propagate_config_error

_LOGGER: logging.Logger = logging.getLogger(__name__)
MOBILE_DATA_UPDATE_INTERVAL = timedelta(minutes=5)


def supports_mobile_data(device_model: str | None) -> bool:
    """Return whether the model is expected to expose mobile WAN data."""
    normalized_model = (device_model or "").upper()
    return "4G" in normalized_model or "5G" in normalized_model


class TplinkDecoMobileDataUpdateCoordinator(DataUpdateCoordinator[int | None]):
    """Fetch optional mobile data usage without affecting normal polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        config_entry: ConfigEntry | None,
        deco_coordinator: TplinkDecoUpdateCoordinator,
    ) -> None:
        """Initialize the coordinator."""
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

    async def _async_update_data(self) -> int | None:
        """Fetch mobile usage when polling is active."""
        if self._deco_coordinator.paused:
            _LOGGER.debug("Mobile data usage polling is paused")
            return self.data

        master_deco = self._deco_coordinator.data.master_deco
        if master_deco is None or not supports_mobile_data(master_deco.device_model):
            return None

        return await async_call_and_propagate_config_error(
            self.api.async_get_mobile_data_usage
        )
