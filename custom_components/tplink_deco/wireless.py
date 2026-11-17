"""Read-only WiFi network status for supported TP-Link Deco firmware."""

from dataclasses import dataclass
from datetime import timedelta
import logging
from math import ceil
from time import monotonic
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import TplinkDecoApi
from .api import decode_name_with_fallback
from .const import ATTR_SSID
from .const import DOMAIN
from .coordinator import TplinkDecoUpdateCoordinator
from .coordinator import async_call_and_propagate_config_error

_LOGGER = logging.getLogger(__name__)
WIRELESS_RETRY_INTERVAL_SECONDS = 300
WIRELESS_FAILURES_BEFORE_RETRY_DELAY = 2


@dataclass(frozen=True, kw_only=True)
class WirelessNetworkDescription(BinarySensorEntityDescription):
    """Describe a firmware-advertised WiFi network and its possible paths."""

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
    """Match a firmware key against one supported path segment."""
    if not isinstance(key, str):
        return False
    if pattern.endswith("*"):
        return key.startswith(pattern[:-1])
    return pattern == key


def _resolve_sections(
    config: object, paths: tuple[tuple[str, ...], ...]
) -> list[dict[str, Any]]:
    """Resolve known nested settings mappings without persisting raw data."""
    sections: list[dict[str, Any]] = []
    for path in paths:
        nodes: list[object] = [config]
        for segment in path:
            nodes = [
                value
                for node in nodes
                if isinstance(node, dict)
                for key, value in node.items()
                if _key_matches(segment, key)
            ]
        sections.extend(node for node in nodes if isinstance(node, dict))
    return sections


def _parse_enabled(value: object) -> bool | None:
    """Normalize known flags without assuming unknown means disabled."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        state = value.strip().lower()
        if state in {"1", "enable", "enabled", "on", "true"}:
            return True
        if state in {"0", "disable", "disabled", "off", "false"}:
            return False
    return None


def parse_wireless_states(config: object) -> dict[str, bool]:
    """Extract WiFi enabled flags only; omit SSIDs, passwords and unknowns."""
    states: dict[str, bool] = {}
    for network in WIRELESS_NETWORKS:
        values = [
            parsed
            for section in _resolve_sections(config, network.paths)
            if (parsed := _parse_enabled(section.get("enable"))) is not None
        ]
        if values:
            states[network.key] = any(values)
    return states


def _resolve_band_sections(
    config: object, paths: tuple[tuple[str, ...], ...]
) -> list[tuple[str, dict[str, Any]]]:
    """Resolve recognized network sections with their top-level band names."""
    sections: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(config, dict):
        return sections
    for path in paths:
        if not path:
            continue
        for key, value in config.items():
            if _key_matches(path[0], key):
                sections.extend(
                    (key, section) for section in _resolve_sections(value, (path[1:],))
                )
    return sections


def parse_wireless_ssids(config: object) -> dict[str, dict[str, str]]:
    """Extract only supported SSID strings from known firmware sections."""
    ssids: dict[str, dict[str, str]] = {}
    for network in WIRELESS_NETWORKS:
        names: dict[str, str] = {}
        for band, section in _resolve_band_sections(config, network.paths):
            raw_name = section.get("ssid")
            if not isinstance(raw_name, str) or not raw_name:
                continue
            decoded_name = decode_name_with_fallback(raw_name)
            if decoded_name:
                names[band] = decoded_name
        if names:
            ssids[network.key] = names
    return ssids


def wireless_ssid_attributes(names: dict[str, str]) -> dict[str, str]:
    """Expose a common name once, or individual names per band."""
    if len(set(names.values())) == 1:
        return {ATTR_SSID: next(iter(names.values()))}
    return {f"{ATTR_SSID}_{band}": name for band, name in sorted(names.items())}


class TplinkDecoWirelessUpdateCoordinator(DataUpdateCoordinator[dict[str, bool]]):
    """Poll optional WiFi status independently of mandatory Deco refreshes."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        config_entry: ConfigEntry | None,
        deco_coordinator: TplinkDecoUpdateCoordinator,
        update_interval: timedelta | None,
        expose_ssids: bool = False,
    ) -> None:
        """Initialize a separate per-config-entry WiFi coordinator."""
        self.api = api
        self.expose_ssids = expose_ssids is True
        self._deco_coordinator = deco_coordinator
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-wireless",
            update_interval=update_interval,
        )
        self.data = {}
        self.ssids: dict[str, dict[str, str]] = {}
        self._next_retry = 0.0
        self._consecutive_failures = 0

    @property
    def retry_remaining_seconds(self) -> int:
        """Return remaining optional-endpoint cooldown in seconds."""
        return max(0, ceil(self._next_retry - monotonic()))

    def reset_retry(self) -> None:
        """Clear the optional endpoint cooldown after a successful poll."""
        self._next_retry = 0.0
        self._consecutive_failures = 0

    async def _async_update_data(self) -> dict[str, bool]:
        """Read WiFi state without blocking Deco or client polling."""
        if self._deco_coordinator.paused:
            return self.data

        now = monotonic()
        if now < self._next_retry:
            raise UpdateFailed("Wireless status retry is deferred")

        try:
            response = await async_call_and_propagate_config_error(
                self.api.async_get_wireless
            )
            if not isinstance(response, dict):
                raise ValueError("Wireless status response must be a mapping")
            states = parse_wireless_states(response)
        except ConfigEntryAuthFailed:
            # Authentication is handled by the config-entry flow, not by
            # optional endpoint retry/backoff.
            raise
        except Exception as error:
            # Optional endpoint errors can include private router data in
            # their text. Contain even unexpected API exceptions, but never
            # cancellation or the config-entry auth failure above.
            self._consecutive_failures += 1
            if self._consecutive_failures >= WIRELESS_FAILURES_BEFORE_RETRY_DELAY:
                self._next_retry = now + WIRELESS_RETRY_INTERVAL_SECONDS
            _LOGGER.debug("Optional wireless request failed (%s)", type(error).__name__)
            raise UpdateFailed("Unable to read optional wireless status") from None

        self.reset_retry()
        # Never retain names without explicit consent; ignore unsupported networks.
        self.ssids = (
            {
                key: names
                for key, names in parse_wireless_ssids(response).items()
                if key in states
            }
            if self.expose_ssids
            else {}
        )
        _LOGGER.debug("Wireless network keys=%s", sorted(states))
        return states
