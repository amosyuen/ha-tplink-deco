"""TP-Link Deco Coordinator"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import ipaddress
import logging
from math import ceil
from time import monotonic
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import TplinkDecoApi
from .api import normalize_name
from .const import DOMAIN
from .const import SIGNAL_CLIENT_ADDED
from .const import SIGNAL_DECO_ADDED
from .exceptions import LoginForbiddenException
from .exceptions import LoginInvalidException
from .exceptions import TimeoutException
from .exceptions import TransientConnectionException

_LOGGER: logging.Logger = logging.getLogger(__name__)
CLIENT_BACKOFF_INITIAL_SECONDS = 30
CLIENT_BACKOFF_MAX_SECONDS = 300


@dataclass
class CoordinatorHealth:
    """Non-sensitive, per-entry metrics for real coordinator API polls."""

    last_successful_update: datetime | None = None
    response_time_ms: int | None = None
    timeout_count: int = 0
    consecutive_failures: int = 0
    last_error: str = "0"

    def record_success(self, started: float) -> None:
        """Record a completed poll without logging or retaining payloads."""
        self.last_successful_update = datetime.now(timezone.utc)
        self.response_time_ms = max(0, round((monotonic() - started) * 1000))
        self.consecutive_failures = 0

    def record_failure(self, started: float, error: Exception) -> None:
        """Track failed polls by exception type, never by exception message."""
        self.response_time_ms = max(0, round((monotonic() - started) * 1000))
        self.consecutive_failures += 1
        self.last_error = type(error).__name__
        if isinstance(error, (TimeoutError, TimeoutException)):
            self.timeout_count += 1

    def record_incomplete(self, started: float) -> None:
        """Track a poll where none of the queried nodes returned valid data."""
        self.response_time_ms = max(0, round((monotonic() - started) * 1000))
        self.consecutive_failures += 1
        self.last_error = "NoSuccessfulClientList"


def bytes_to_bits(bytes_count):
    return bytes_count / 8 if bytes_count is not None else bytes_count


def filter_invalid_ip(ip_address):
    try:
        # Check that it parsed to an IP address
        ipaddress.ip_address(ip_address)
        return ip_address
    except ValueError:
        return None


def snake_case_to_title_space(name: str) -> str:
    """Convert firmware identifiers to display names."""
    return " ".join(word.title() for word in name.split("_"))


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
        self.backhaul_bssid_band2_4 = None
        self.backhaul_bssid_band5 = None
        self.signal_band2_4 = None
        self.signal_band5 = None
        self.backhaul_speed = None
        self.backhaul_max_speed = None
        self.cpu_usage = None
        self.cpu_usage_raw = None
        self.mem_usage = None
        self.mem_usage_raw = None

    def update(
        self,
        data: dict[str, Any],
    ) -> None:
        self.hw_version = data.get("hardware_ver")
        self.sw_version = data.get("software_ver")
        self.device_model = data.get("device_model")

        custom_nickname = data.get("custom_nickname")
        nickname = data.get("nickname")
        name = normalize_name(custom_nickname) if custom_nickname else None
        if not name and nickname:
            name = normalize_name(snake_case_to_title_space(nickname))
        self.name = name or self.mac
        self.ip_address = filter_invalid_ip(data.get("device_ip"))
        self.online = data.get("group_status") == "connected"
        inet = data.get("inet_status")
        if inet is None:
            self.internet_online = None
        elif isinstance(inet, str):
            self.internet_online = inet.lower() in ("online", "connected", "up")
        else:
            self.internet_online = bool(inet)
        self.master = data.get("role") == "master"
        self.connection_type = data.get("connection_type")
        self.bssid_band2_4 = data.get("bssid_2g")
        self.bssid_band5 = data.get("bssid_5g")
        self.backhaul_bssid_band2_4 = data.get("bssid_sta_2g")
        self.backhaul_bssid_band5 = data.get("bssid_sta_5g")
        signal_level = data.get("signal_level", {})
        self.signal_band2_4 = signal_level.get("band2_4")
        self.signal_band5 = signal_level.get("band5")
        self.backhaul_speed = data.get("backhual_speed")
        self.backhaul_max_speed = data.get("backhual_max_speed")


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
        config_entry: ConfigEntry,
        update_interval: timedelta = None,
        data: TpLinkDecoData = None,
    ) -> None:
        """Initialize."""
        self.api = api
        self._on_close: list[Callable] = []

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-decos",
            update_interval=update_interval,
        )
        # Must happen after super().__init__
        self.data = TpLinkDecoData() if data is None else data

        self.paused = False
        self.health = CoordinatorHealth()

    async def _async_update_data(self):
        """Measure an actual Deco poll without changing pause semantics."""
        if self.paused:
            _LOGGER.debug("Deco polling is paused")
            return self.data

        started = monotonic()
        try:
            data = await self._async_update_data_internal()
        except Exception as error:
            self.health.record_failure(started, error)
            raise

        self.health.record_success(started)
        return data

    async def _async_update_data_internal(self):
        """Fetch and reconcile the Deco inventory and optional performance."""
        new_decos = await async_call_and_propagate_config_error(
            self.api.async_list_devices
        )

        try:
            performance_data = await async_call_and_propagate_config_error(
                self.api.async_get_performance
            )
        except TransientConnectionException:
            # Keep previously sampled CPU/memory data if an optional request
            # is still incomplete after its bounded transport retries.
            _LOGGER.debug("Deco performance unavailable after transport retries")
            performance_data = None

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

        for mac, old_deco in old_decos.items():
            if mac not in decos:
                _LOGGER.debug(
                    "_async_update_data: Deco mac=%s not returned by API, marking offline",
                    mac,
                )
                old_deco.online = False
                old_deco.internet_online = False
                decos[mac] = old_deco

        # Zet globale performance data op de master Deco
        result = performance_data.get("result", {}) if performance_data else {}
        if master_deco is not None:
            cpu_raw = result.get("cpu_usage")
            mem_raw = result.get("mem_usage")

            if cpu_raw is not None:
                cpu_percent = cpu_raw * 100
                master_deco.cpu_usage_raw = round(cpu_percent, 1)

                if master_deco.cpu_usage is not None:
                    master_deco.cpu_usage = round(
                        (master_deco.cpu_usage * 0.7) + (cpu_percent * 0.3), 1
                    )
                else:
                    master_deco.cpu_usage = round(cpu_percent, 1)

            if mem_raw is not None:
                mem_percent = mem_raw * 100
                master_deco.mem_usage_raw = round(mem_percent, 1)

                if master_deco.mem_usage is not None:
                    master_deco.mem_usage = round(
                        (master_deco.mem_usage * 0.7) + (mem_percent * 0.3), 1
                    )
                else:
                    master_deco.mem_usage = round(mem_percent, 1)

        updated_data = TpLinkDecoData(master_deco, decos)
        # Discovery callbacks inspect coordinator.data synchronously.
        self.data = updated_data
        if deco_added:
            async_dispatcher_send(self.hass, SIGNAL_DECO_ADDED)

        return updated_data

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
        config_entry: ConfigEntry,
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
            config_entry=config_entry,
            name=f"{DOMAIN}-clients",
            update_interval=update_interval,
        )
        # Must happen after super().__init__
        self.data = {} if data is None else data
        self._client_backoff_until = 0.0
        self._client_backoff_seconds = 0
        self.has_successful_refresh = False
        self.successfully_polled_deco_macs: set[str] = set()
        self.health = CoordinatorHealth()
        self._poll_had_valid_response = False

    @property
    def client_query_mode(self) -> str:
        """Describe the currently implemented per-Deco client query strategy."""
        return "per_node"

    @property
    def remaining_backoff_seconds(self) -> int:
        """Return the remaining 5xx client-polling delay, rounded up."""
        return max(0, ceil(self._client_backoff_until - monotonic()))

    def _apply_client_backoff(self) -> None:
        """Double the delay after an HTTP 5xx polling cycle, up to five minutes."""
        self._client_backoff_seconds = min(
            self._client_backoff_seconds * 2 or CLIENT_BACKOFF_INITIAL_SECONDS,
            CLIENT_BACKOFF_MAX_SECONDS,
        )
        self._client_backoff_until = monotonic() + self._client_backoff_seconds
        _LOGGER.warning(
            "Deco client polling hit HTTP 5xx; pausing for %d seconds",
            self._client_backoff_seconds,
        )

    def _reset_client_backoff(self) -> None:
        """Reset the delay once every queried Deco returned a valid response."""
        if self._client_backoff_seconds:
            _LOGGER.info("Deco client polling recovered after HTTP 5xx backoff")
        self._client_backoff_seconds = 0
        self._client_backoff_until = 0.0

    async def _async_clients_for_deco(
        self, deco_mac: str
    ) -> tuple[list[dict[str, Any]] | None, bool]:
        """Return clients and whether an HTTP 5xx response occurred."""
        try:
            clients = await async_call_and_propagate_config_error(
                self.api.async_list_clients, deco_mac
            )
        except TransientConnectionException:
            # A failed request is not equivalent to a valid empty client list.
            _LOGGER.debug("Deco client poll incomplete after transport retries")
            return None, False
        except aiohttp.ClientResponseError as err:
            if not 500 <= err.status < 600:
                raise
            _LOGGER.debug("Deco client poll returned HTTP %d", err.status)
            return None, True
        return clients, False

    async def _async_update_data(self):
        """Measure actual client queries, excluding pause and backoff skips."""
        if self._deco_update_coordinator.paused:
            _LOGGER.debug("Deco client polling is paused")
            return self.data

        if not self._deco_update_coordinator.data.decos:
            return self.data

        if self.remaining_backoff_seconds:
            _LOGGER.debug(
                "Skipping Deco client polling during HTTP 5xx backoff (%ds remaining)",
                self.remaining_backoff_seconds,
            )
            return self.data

        started = monotonic()
        self._poll_had_valid_response = False
        try:
            data = await self._async_update_data_internal()
        except Exception as error:
            self.health.record_failure(started, error)
            raise

        if self._poll_had_valid_response:
            self.health.record_success(started)
        else:
            self.health.record_incomplete(started)
        return data

    async def _async_update_data_internal(self):
        """Fetch per-node clients while preserving existing failure recovery."""
        old_clients = self.data
        clients = {}
        client_added = False
        deco_macs = list(self._deco_update_coordinator.data.decos)
        utc_point_in_time = dt_util.utcnow()

        # Retain successful per-node responses even when a peer fails.
        deco_client_responses = await asyncio.gather(
            *(self._async_clients_for_deco(deco_mac) for deco_mac in deco_macs)
        )
        failed_deco_macs = {
            deco_mac
            for deco_mac, (response, _) in zip(deco_macs, deco_client_responses)
            if response is None
        }
        if len(failed_deco_macs) == len(deco_macs):
            # Unknown client-to-node assignments must also survive a poll
            # where no Deco returned a valid client list.
            if any(server_error for _, server_error in deco_client_responses):
                self._apply_client_backoff()
            return old_clients

        # An empty but successful response still confirms this Deco's count.
        # Do not create a misleading zero-count entity for an unpolled peer.
        self.successfully_polled_deco_macs.update(
            mac
            for mac, (response, _) in zip(deco_macs, deco_client_responses)
            if response is not None
        )
        self.has_successful_refresh = True
        self._poll_had_valid_response = True

        for deco_mac, (deco_clients, _) in zip(deco_macs, deco_client_responses):
            if deco_clients is None:
                continue
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

        # Retain previous association, state and activity when its node was
        # not polled successfully; apply the usual grace policy otherwise.
        for client in old_clients.values():
            mac = client.mac
            if mac not in clients:
                clients[mac] = client
                if client.deco_mac in failed_deco_macs:
                    continue
                if client.last_activity is None:
                    client.online = False
                else:
                    client.online = (
                        utc_point_in_time - client.last_activity
                    ).total_seconds() < self._consider_home_seconds

        if any(server_error for _, server_error in deco_client_responses):
            self._apply_client_backoff()
        elif all(response is not None for response, _ in deco_client_responses):
            self._reset_client_backoff()

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
