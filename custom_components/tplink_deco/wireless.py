"""Wireless network status support for TP-Link Deco."""

from dataclasses import dataclass
from datetime import timedelta
import logging
from time import monotonic
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import TplinkDecoApi
from .const import DOMAIN
from .coordinator import TplinkDecoUpdateCoordinator
from .coordinator import async_call_and_propagate_config_error

_LOGGER: logging.Logger = logging.getLogger(__name__)
WIRELESS_RETRY_INTERVAL_SECONDS = 300
# Failures tolerated before retries are deferred, so a single slow response
# does not make the sensors unavailable for the whole retry interval.
WIRELESS_FAILURES_BEFORE_RETRY_DELAY = 2


@dataclass(frozen=True, kw_only=True)
class WirelessNetworkDescription(BinarySensorEntityDescription):
    """Describe a wireless network exposed by Deco firmware."""

    paths: tuple[tuple[str, ...], ...]


WIRELESS_NETWORKS = (
    WirelessNetworkDescription(
        key="main",
        name="Main WiFi",
        icon="mdi:wifi",
        paths=(("band*", "host"),),
        entity_registry_enabled_default=False,
    ),
    WirelessNetworkDescription(
        key="guest",
        name="Guest WiFi",
        icon="mdi:wifi-lock-open",
        paths=(("band*", "guest"),),
    ),
    WirelessNetworkDescription(
        key="iot",
        name="IoT WiFi",
        icon="mdi:home-automation",
        paths=(("iot", "host"),),
    ),
)


def _key_matches(pattern: str, key: object) -> bool:
    """Return whether a firmware key matches a path segment."""
    key_string = str(key)
    if pattern.endswith("*"):
        return key_string.startswith(pattern[:-1])
    return key_string == pattern


def _resolve_sections(
    config: object, paths: tuple[tuple[str, ...], ...]
) -> list[dict[str, Any]]:
    """Resolve dictionaries addressed by firmware-independent paths."""
    sections = []
    for path in paths:
        nodes = [config]
        for pattern in path:
            nodes = [
                value
                for node in nodes
                if isinstance(node, dict)
                for key, value in node.items()
                if _key_matches(pattern, key)
            ]
        sections.extend(node for node in nodes if isinstance(node, dict))
    return sections


def _is_enabled(value: object) -> bool:
    """Normalize enable flags used by different Deco firmwares."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {
        "1",
        "enable",
        "enabled",
        "on",
        "true",
    }


def parse_wireless_states(config: object) -> dict[str, bool]:
    """Extract only supported network states from a wireless response."""
    states = {}
    for network in WIRELESS_NETWORKS:
        values = [
            _is_enabled(section["enable"])
            for section in _resolve_sections(config, network.paths)
            if "enable" in section
        ]
        if values:
            states[network.key] = any(values)
    return states


class TplinkDecoWirelessUpdateCoordinator(DataUpdateCoordinator):
    """Coordinate optional wireless status requests."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        config_entry: ConfigEntry | None,
        deco_coordinator: TplinkDecoUpdateCoordinator,
        update_interval: timedelta | None,
    ) -> None:
        self.api = api
        self._deco_coordinator = deco_coordinator
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-wireless",
            update_interval=update_interval,
        )
        self.data = {}
        self._next_retry = 0.0
        self._consecutive_failures = 0

    @property
    def retry_remaining_seconds(self) -> int:
        """Return seconds remaining before the optional endpoint is retried."""
        return max(0, round(self._next_retry - monotonic()))

    def reset_retry(self) -> None:
        """Allow the next refresh to query the Deco immediately."""
        self._next_retry = 0.0
        self._consecutive_failures = 0

    async def _async_update_data(self) -> dict[str, bool]:
        """Fetch wireless states without affecting integration setup."""
        if self._deco_coordinator.paused:
            _LOGGER.debug("Wireless polling is paused")
            return self.data

        now = monotonic()
        if now < self._next_retry:
            raise UpdateFailed("Wireless status retry is deferred after a failure")

        try:
            config = await async_call_and_propagate_config_error(
                self.api.async_get_wireless, "wlan"
            )
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            self._consecutive_failures += 1
            if self._consecutive_failures >= WIRELESS_FAILURES_BEFORE_RETRY_DELAY:
                self._next_retry = now + WIRELESS_RETRY_INTERVAL_SECONDS
            reason = f"{type(err).__name__}: {err}" if str(err) else type(err).__name__
            raise UpdateFailed(f"Unable to read wireless status: {reason}") from err

        self.reset_retry()
        states = parse_wireless_states(config)
        _LOGGER.debug("Wireless status networks=%s", sorted(states))
        return states
