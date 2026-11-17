"""TP-Link Deco Coordinator"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import ipaddress
import logging
from math import ceil
from math import isfinite
from time import monotonic
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import TplinkDecoApi
from .api import normalize_name
from .const import DEFAULT_SCAN_INTERVAL
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
MAX_CONCURRENT_CLIENT_REQUESTS = 2


@dataclass
class CoordinatorHealth:
    """Non-sensitive, per-entry metrics for real coordinator API polls."""

    last_successful_update: datetime | None = None
    response_time_ms: int | None = None
    timeout_count: int = 0
    consecutive_failures: int = 0
    last_error: str = "0"
    _listeners: list[CALLBACK_TYPE] = field(
        default_factory=list, repr=False, compare=False
    )

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Subscribe to health changes independently of coordinator updates."""
        self._listeners.append(listener)

        @callback
        def _unsubscribe() -> None:
            """Remove this listener safely when its entity is unloaded."""
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsubscribe

    @callback
    def _notify_listeners(self) -> None:
        """Publish each measured change without breaking the ongoing API poll."""
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception as error:
                _LOGGER.warning(
                    "Deco health listener update failed (%s)",
                    type(error).__name__,
                )

    def record_success(self, started: float, *, timed_out: bool = False) -> None:
        """Record successful data, optionally with a timed-out peer node."""
        self.last_successful_update = datetime.now(timezone.utc)
        self.response_time_ms = max(0, round((monotonic() - started) * 1000))
        self.consecutive_failures = 0
        if timed_out:
            self.timeout_count += 1
            self.last_error = "TimeoutException"
        self._notify_listeners()

    def record_failure(self, started: float, error: Exception) -> None:
        """Track failed polls by exception type, never by exception message."""
        self.response_time_ms = max(0, round((monotonic() - started) * 1000))
        self.consecutive_failures += 1
        self.last_error = type(error).__name__
        if isinstance(error, (TimeoutError, TimeoutException)):
            self.timeout_count += 1
        self._notify_listeners()

    def record_incomplete(self, started: float, *, timed_out: bool = False) -> None:
        """Record an all-failed poll and whether any node timed out."""
        self.response_time_ms = max(0, round((monotonic() - started) * 1000))
        self.consecutive_failures += 1
        if timed_out:
            self.timeout_count += 1
        self.last_error = "TimeoutException" if timed_out else "NoSuccessfulClientList"
        self._notify_listeners()


def _coerce_finite_float(value: object) -> float | None:
    """Parse legacy firmware numeric strings without accepting invalid values."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None

    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None

    return number if isfinite(number) else None


def bytes_to_bits(bytes_count: object) -> float | None:
    """Preserve the existing byte-rate conversion for finite JSON numbers."""
    numeric_value = _coerce_finite_float(bytes_count)
    return numeric_value / 8 if numeric_value is not None else None


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


async def async_call_and_propagate_config_error(func, *args, **kwargs):
    """Forward API arguments and keep the established auth-failure mapping."""
    try:
        return await func(*args, **kwargs)
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
        """Update Deco fields after validating optional signal data."""
        signal_level = data.get("signal_level")
        if signal_level is None:
            signal_level = {}
        elif not isinstance(signal_level, dict):
            # Validate before mutating any cached node fields.
            raise ValueError("Deco inventory contains invalid signal data")

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
        # Unknown rates contribute zero, not None, to live throughput totals.
        self.down_kilobytes_per_s = bytes_to_bits(data.get("down_speed", 0)) or 0.0
        self.up_kilobytes_per_s = bytes_to_bits(data.get("up_speed", 0)) or 0.0
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
        device_list_interval_seconds: int | None = None,
    ) -> None:
        """Initialize."""
        self.api = api
        self._on_close: list[Callable] = []
        self.device_list_interval_seconds = (
            device_list_interval_seconds
            if device_list_interval_seconds is not None
            else (
                int(update_interval.total_seconds())
                if update_interval is not None
                else DEFAULT_SCAN_INTERVAL
            )
        )
        self._last_device_list_update: float | None = None
        self._force_device_list_refresh = False

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
        if self.paused and not self._force_device_list_refresh:
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
        # Commit a validated inventory before optional performance. A slow or
        # failing performance API must not discard a successful device list.
        if self._device_list_refresh_due():
            new_decos = await async_call_and_propagate_config_error(
                self.api.async_list_devices
            )
            self._process_device_list(new_decos)
            self._last_device_list_update = monotonic()
            self._force_device_list_refresh = False

        try:
            performance_data = await async_call_and_propagate_config_error(
                self.api.async_get_performance
            )
        except (TransientConnectionException, TimeoutException, TimeoutError) as err:
            # Performance is optional. Authentication and unexpected failures
            # must still propagate. Never log upstream exception messages.
            _LOGGER.debug(
                "Optional Deco performance request failed (%s)",
                type(err).__name__,
            )
            performance_data = None

        master_deco = self.data.master_deco
        # Zet globale performance data op de master Deco
        if not isinstance(performance_data, dict):
            performance_data = None
        result = performance_data.get("result", {}) if performance_data else {}
        if not isinstance(result, dict):
            result = {}
        if master_deco is not None:
            cpu_raw = result.get("cpu_usage")
            mem_raw = result.get("mem_usage")

            cpu_value = _coerce_finite_float(cpu_raw)
            if cpu_value is not None:
                cpu_percent = cpu_value * 100
                master_deco.cpu_usage_raw = round(cpu_percent, 1)

                if master_deco.cpu_usage is not None:
                    master_deco.cpu_usage = round(
                        (master_deco.cpu_usage * 0.7) + (cpu_percent * 0.3), 1
                    )
                else:
                    master_deco.cpu_usage = round(cpu_percent, 1)

            mem_value = _coerce_finite_float(mem_raw)
            if mem_value is not None:
                mem_percent = mem_value * 100
                master_deco.mem_usage_raw = round(mem_percent, 1)

                if master_deco.mem_usage is not None:
                    master_deco.mem_usage = round(
                        (master_deco.mem_usage * 0.7) + (mem_percent * 0.3), 1
                    )
                else:
                    master_deco.mem_usage = round(mem_percent, 1)

        return self.data

    def _device_list_refresh_due(self) -> bool:
        """Check whether to refresh the mesh inventory this cycle."""
        if self._force_device_list_refresh or self._last_device_list_update is None:
            return True
        if self.device_list_interval_seconds == 0:
            return False
        return (
            monotonic() - self._last_device_list_update
            >= self.device_list_interval_seconds
        )

    def _process_device_list(self, new_decos: list[dict[str, Any]]) -> None:
        """Validate the complete inventory before modifying cached nodes."""
        if not isinstance(new_decos, list):
            raise ValueError("Deco inventory response must contain a device list")

        macs: list[str] = []
        for item in new_decos:
            if not isinstance(item, dict):
                raise ValueError("Deco inventory contains an invalid device")
            mac = item.get("mac")
            if not isinstance(mac, str) or not mac.strip():
                raise ValueError("Deco inventory contains an invalid device ID")
            signal_level = item.get("signal_level")
            if signal_level is not None and not isinstance(signal_level, dict):
                raise ValueError("Deco inventory contains invalid signal data")
            for name_key in ("nickname", "custom_nickname"):
                name_value = item.get(name_key)
                if name_value is not None and not isinstance(name_value, str):
                    raise ValueError("Deco inventory contains invalid name data")
            macs.append(mac)

        if len(macs) != len(set(macs)):
            raise ValueError("Deco inventory contains duplicate device IDs")

        old_decos = self.data.decos
        master_deco = None
        deco_added = False
        decos: dict[str, TpLinkDeco] = {}
        for new_deco in new_decos:
            mac = new_deco["mac"]
            deco = old_decos.get(mac)
            if deco is None:
                deco_added = True
                deco = TpLinkDeco(mac)
                _LOGGER.debug("New Deco node discovered during inventory refresh")
            deco.update(new_deco)
            decos[mac] = deco
            if deco.master:
                master_deco = deco

        for mac, old_deco in old_decos.items():
            if mac not in decos:
                _LOGGER.debug(
                    "Deco node not present in current inventory; marking offline"
                )
                old_deco.online = False
                old_deco.internet_online = False
                decos[mac] = old_deco

        # Discovery handlers inspect coordinator.data synchronously.
        self.data = TpLinkDecoData(master_deco, decos)
        if deco_added:
            async_dispatcher_send(self.hass, SIGNAL_DECO_ADDED)

    async def async_request_device_refresh(self) -> None:
        """Request a real device-list poll, even in startup-only mode."""
        self._force_device_list_refresh = True
        try:
            await self.async_refresh()
        except ConfigEntryAuthFailed:
            # Keep the HA auth failure type without exposing an API message.
            raise ConfigEntryAuthFailed(
                "Deco authentication failed; check integration credentials"
            ) from None
        except Exception:
            # A refresh can also propagate a raw upstream exception.
            # Do not expose its message, which may contain session tokens.
            raise HomeAssistantError(
                "Unable to refresh Deco status; check the router connection"
            ) from None
        finally:
            # A failed manual press must not silently unpause later polling.
            # A second press may force another request.
            self._force_device_list_refresh = False
        if not self.last_update_success:
            # DataUpdateCoordinator.async_refresh can absorb poll exceptions.
            # Raise a safe error so the manual button reports failure to HA.
            raise HomeAssistantError(
                "Unable to refresh Deco status; check the router connection"
            )

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
        self._poll_had_timeout = False
        self._client_query_mode = "per_node"

    @property
    def client_query_mode(self) -> str:
        """Return the active per-node or global client query strategy."""
        return self._client_query_mode

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
                self.api.async_list_clients,
                deco_mac,
                timeout_error_retries=0,
            )
        except TimeoutException:
            # One failed Deco must not trigger repeated per-node timeouts.
            self._poll_had_timeout = True
            _LOGGER.debug("Deco client poll timed out")
            return None, False
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

    async def _async_list_clients_globally(self) -> list[dict[str, Any]] | None:
        """Try one global query without masking authentication or invalid data."""
        try:
            response = await async_call_and_propagate_config_error(
                self.api.async_list_clients,
                "default",
                timeout_error_retries=0,
            )
        except TimeoutException:
            self._poll_had_timeout = True
            _LOGGER.debug("Global Deco client poll timed out")
            return None
        except TransientConnectionException:
            _LOGGER.debug("Global Deco client poll incomplete")
            return None
        except aiohttp.ClientResponseError as err:
            if not 500 <= err.status < 600:
                raise
            _LOGGER.debug("Global Deco client poll returned HTTP %d", err.status)
            return None
        if not isinstance(response, list) or any(
            not isinstance(item, dict) for item in response
        ):
            raise ValueError("Invalid global Deco client list response")
        return response

    async def _async_list_clients_per_deco(
        self, deco_macs: list[str]
    ) -> list[tuple[list[dict[str, Any]] | None, bool]]:
        """Poll at most two Decos concurrently and cancel pending work on error."""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLIENT_REQUESTS)

        async def _poll_one(deco_mac: str) -> tuple[list[dict[str, Any]] | None, bool]:
            """Bound the request without blocking the Home Assistant event loop."""
            async with semaphore:
                return await self._async_clients_for_deco(deco_mac)

        tasks = [asyncio.create_task(_poll_one(mac)) for mac in deco_macs]
        try:
            return await asyncio.gather(*tasks)
        except (Exception, asyncio.CancelledError):
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _async_update_data(self):
        """Measure actual client queries, excluding pause and backoff skips."""
        if self._deco_update_coordinator.paused:
            _LOGGER.debug("Deco client polling is paused")
            return self.data

        if not self._deco_update_coordinator.data.decos:
            return self.data

        if self.remaining_backoff_seconds and self._client_query_mode != "global":
            _LOGGER.debug(
                "Skipping per-node Deco polling during HTTP 5xx backoff (%ds remaining)",
                self.remaining_backoff_seconds,
            )
            return self.data

        started = monotonic()
        self._poll_had_valid_response = False
        self._poll_had_timeout = False
        try:
            data = await self._async_update_data_internal()
        except Exception as error:
            self.health.record_failure(started, error)
            raise

        if self._poll_had_valid_response:
            self.health.record_success(started, timed_out=self._poll_had_timeout)
        else:
            self.health.record_incomplete(started, timed_out=self._poll_had_timeout)
        return data

    async def _async_update_data_internal(self):
        """Fetch per-node or global clients while retaining last-known state."""
        old_clients = self.data
        clients = {}
        client_added = False
        deco_macs = list(self._deco_update_coordinator.data.decos)
        utc_point_in_time = dt_util.utcnow()

        # While per-node 5xx backoff is active, use the known-good global
        # strategy without reissuing broken per-node requests.
        global_only = (
            self._client_query_mode == "global" and self.remaining_backoff_seconds > 0
        )
        deco_client_responses = (
            [] if global_only else await self._async_list_clients_per_deco(deco_macs)
        )
        server_error = any(error for _, error in deco_client_responses)
        if server_error:
            self._apply_client_backoff()

        if global_only or server_error:
            master = self._deco_update_coordinator.data.master_deco
            if master is not None:
                global_clients = await self._async_list_clients_globally()
                if global_clients is not None:
                    # Global data lacks a reliable node identity. Use the
                    # real master MAC, never the API sentinel "default".
                    deco_macs = [master.mac]
                    deco_client_responses = [(global_clients, False)]
                    self._client_query_mode = "global"
                elif global_only:
                    return old_clients
            elif global_only:
                return old_clients

        if (
            not global_only
            and not server_error
            and all(response is not None for response, _ in deco_client_responses)
        ):
            self._reset_client_backoff()
            self._client_query_mode = "per_node"

        failed_deco_macs = {
            deco_mac
            for deco_mac, (response, _) in zip(deco_macs, deco_client_responses)
            if response is None
        }
        if len(failed_deco_macs) == len(deco_macs):
            # Unknown client-to-node assignments must also survive a poll
            # where no Deco returned a valid client list.
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
