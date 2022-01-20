"""TP-Link Deco Coordinator"""
import logging
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from typing import Any

from homeassistant.core import callback
from homeassistant.core import CALLBACK_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import TplinkDecoApi
from .const import DOMAIN
from .const import SIGNAL_CLIENT_ADDED

_LOGGER: logging.Logger = logging.getLogger(__package__)


class TPLinkDecoClient:
    """Class to manage TP-Link Deco Client."""

    def __init__(self, mac: str) -> None:
        self.mac = mac
        self.name = None
        self.ip_address = None
        self.online = False
        self.connection_type = None
        self.interface = None
        self.down_kb_per_s = None
        self.up_kb_per_s = None
        self.last_activity = None

    def update(
        self,
        data: dict[str:Any],
        utc_point_in_time: datetime,
    ) -> None:
        self.name = data["name"]
        self.ip_address = data["ip"]
        self.online = data["online"]
        self.connection_type = data["connection_type"]
        self.interface = data["interface"]
        self.down_kb_per_s = data["down_speed"]
        self.up_kb_per_s = data["up_speed"]
        self.last_activity = utc_point_in_time


class TplinkDecoDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        scan_interval_seconds: int,
        consider_home_seconds: int,
        data: dict[str:TPLinkDecoClient],
    ) -> None:
        """Initialize."""
        self._api = api
        self._consider_home_seconds = consider_home_seconds
        self._on_close: list[Callable] = []
        self.data = data

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds),
        )

    async def _async_update_data(self):
        """Update data via api."""
        new_clients = await self._api.async_list_clients()

        old_clients = self.data or {}
        data = {}
        utc_point_in_time = dt_util.utcnow()

        client_added = False
        for mac in new_clients:
            client = old_clients.get(mac)
            if client is None:
                client_added = True
                client = TPLinkDecoClient(mac)
                client.update(new_clients[mac], utc_point_in_time)
                data[mac] = client
            else:
                client.update(new_clients[mac], utc_point_in_time)

        # Copy over clients no longer online
        for client in old_clients.values():
            mac = client.mac
            if mac not in data:
                data[mac] = client
                client.online = (
                    utc_point_in_time - client.last_activity
                ).total_seconds() < self._consider_home_seconds

        if client_added:
            async_dispatcher_send(self.hass, SIGNAL_CLIENT_ADDED)

        return data

    @callback
    def on_close(self, func: CALLBACK_TYPE) -> None:
        """Add a function to call when coordinator is closed."""
        self._on_close.append(func)

    async def async_close(self) -> None:
        """Call functions on close."""
        for func in self._on_close:
            try:
                func()
            except Exception as err:
                _LOGGER.error("Error calling on_close function %s: %s", func, err)
        self._on_close.clear()
