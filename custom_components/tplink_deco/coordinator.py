"""TP-Link Deco Coordinator"""
import asyncio
import ipaddress
import logging
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from typing import Any

from homeassistant.core import callback
from homeassistant.core import CALLBACK_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import TplinkDecoApi
from .const import DOMAIN
from .const import SIGNAL_CLIENT_ADDED
from .const import SIGNAL_DECO_ADDED
from .exceptions import LoginForbiddenException
from .exceptions import LoginInvalidException

_LOGGER: logging.Logger = logging.getLogger(__name__)


def bytes_to_bits(bytes_count):
    return bytes_count / 8 if bytes_count is not None else bytes_count


def filter_invalid_ip(ip_address):
    try:
        # Check that it parsed to an IP address
        ipaddress.ip_address(ip_address)
        return ip_address
    except ValueError:
        return None


def snake_case_to_title_space(str):
    return " ".join([w.title() for w in str.split("_")])


async def async_call_and_propagate_config_error(func, *args):
    try:
        return await func(*args)
    except (LoginForbiddenException, LoginInvalidException) as err:
        raise ConfigEntryAuthFailed from err


class TpLinkDeco:
    """Class to manage TP-Link Deco device."""

    def __init__(self, mac: str) -> None:
        self.mac = mac

        self.hw_version = None
        self.sw_version = None
        self.device_model = None

        self.name = None
        self.ip_address = None
        self.online = None
        self.internet_online = None
        self.master = None
        self.connection_type = None
        self.interface = None
        self.bssid_band2_4 = None
        self.bssid_band5 = None
        self.signal_band2_4 = None
        self.signal_band5 = None

    def update(
        self,
        data: dict[str:Any],
    ) -> None:
        self.hw_version = data.get("hardware_ver")
        self.sw_version = data.get("software_ver")
        self.device_model = data.get("device_model")

        self.name = data.get("custom_nickname")  # Only set if custom value
        if self.name is None:
            self.name = snake_case_to_title_space(data.get("nickname"))
        self.ip_address = filter_invalid_ip(data.get("device_ip"))
        self.online = data.get("group_status") == "connected"
        self.internet_online = data.get("inet_status") == "online"
        self.master = data.get("role") == "master"
        self.connection_type = data.get("connection_type")
        self.bssid_band2_4 = data.get("bssid_2g")
        self.bssid_band5 = data.get("bssid_5g")
        signal_level = data.get("signal_level", {})
        self.signal_band2_4 = signal_level.get("band2_4")
        self.signal_band5 = signal_level.get("band5")


class TpLinkDecoClient:
    """Class to manage TP-Link Deco Client."""

    def __init__(self, mac: str) -> None:
        self.mac = mac
        self.name = None
        self.ip_address = None
        self.online = False
        self.connection_type = None
        self.interface = None
        self.down_kilobytes_per_s = 0
        self.up_kilobytes_per_s = 0
        self.deco_mac = None
        self.last_activity = None

    def update(
        self,
        data: dict[str:Any],
        deco_mac: str,
        utc_point_in_time: datetime,
    ) -> None:
        self.deco_mac = deco_mac
        self.name = data.get("name")
        self.ip_address = filter_invalid_ip(data.get("ip"))
        self.online = data.get("online")
        self.connection_type = data.get("connection_type")
        self.interface = data.get("interface")
        self.down_kilobytes_per_s = bytes_to_bits(data.get("down_speed", 0))
        self.up_kilobytes_per_s = bytes_to_bits(data.get("up_speed", 0))
        self.last_activity = utc_point_in_time


class TpLinkDecoData:
    """Class for coordinator data."""

    def __init__(
        self,
        master_deco: TpLinkDeco = None,
        decos: dict[str:TpLinkDeco] = None,
    ) -> None:
        self.master_deco = master_deco
        self.decos = {} if decos is None else decos


class TplinkDecoUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        update_interval: timedelta = None,
        data: TpLinkDecoData = None,
    ) -> None:
        """Initialize."""
        self.api = api
        self._on_close: list[Callable] = []

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-decos",
            update_interval=update_interval,
        )
        # Must happen after super().__init__
        self.data = TpLinkDecoData() if data is None else data

    async def _async_update_data(self):
        """Update data via api."""
        new_decos = await async_call_and_propagate_config_error(
            self.api.async_list_devices
        )

        old_decos = self.data.decos
        master_deco = None
        deco_added = False
        decos = {}
        for new_deco in new_decos:
            mac = new_deco["mac"]
            deco = old_decos.get(mac)
            if deco is None:
                deco_added = True
                deco = TpLinkDeco(mac)
                _LOGGER.debug("_async_update_data: Found new deco mac=%s", deco.mac)
            deco.update(new_deco)
            decos[mac] = deco
            if deco.master:
                master_deco = deco

        if deco_added:
            async_dispatcher_send(self.hass, SIGNAL_DECO_ADDED)

        return TpLinkDecoData(master_deco, decos)

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


class TplinkDecoClientUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        deco_update_coordinator: TplinkDecoUpdateCoordinator,
        consider_home_seconds: int,
        update_interval: timedelta = None,
        data: dict[str:TpLinkDecoClient] = None,
    ) -> None:
        """Initialize."""
        self.api = api
        self._deco_update_coordinator = deco_update_coordinator
        self._consider_home_seconds = consider_home_seconds
        self._on_close: list[Callable] = []

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-clients",
            update_interval=update_interval,
        )
        # Must happen after super().__init__
        self.data = {} if data is None else data

    async def _async_update_data(self):
        """Update data via api."""
        if len(self._deco_update_coordinator.data.decos) == 0:
            return

        old_clients = self.data
        clients = {}
        client_added = False
        # List clients for all decos if _deco_update_coordinator is not provided
        deco_macs = self._deco_update_coordinator.data.decos.keys()
        utc_point_in_time = dt_util.utcnow()
        # Send list client requests in parallel for each deco

        deco_client_responses = await asyncio.gather(
            *[
                async_call_and_propagate_config_error(
                    self.api.async_list_clients, deco_mac
                )
                for deco_mac in deco_macs
            ]
        )

        if len(deco_client_responses) > 0:
            # deco_macs is not subscriptable, must be iterated
            for deco_mac, deco_clients in zip(deco_macs, deco_client_responses):
                for deco_client in deco_clients:
                    client_mac = deco_client["mac"]
                    client = old_clients.get(client_mac)
                    if client is None:
                        client_added = True
                        client = TpLinkDecoClient(client_mac)
                        _LOGGER.debug(
                            "_async_update_data: Found new client mac=%s", client.mac
                        )
                    client.update(deco_client, deco_mac, utc_point_in_time)
                    clients[client_mac] = client

        # Copy over clients no longer online
        for client in old_clients.values():
            mac = client.mac
            if mac not in clients:
                clients[mac] = client
                if client.last_activity is None:
                    client.online = False
                else:
                    client.online = (
                        utc_point_in_time - client.last_activity
                    ).total_seconds() < self._consider_home_seconds

        if client_added:
            async_dispatcher_send(self.hass, SIGNAL_CLIENT_ADDED)

        return clients

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
