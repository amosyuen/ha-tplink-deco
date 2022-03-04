"""
Custom integration to integrate TP-Link Deco with Home Assistant.

For more details about this integration, please refer to
https://github.com/amosyuen/ha-tplink-deco
"""
import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.device_tracker.const import CONF_CONSIDER_HOME
from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.components.device_tracker.const import (
    DOMAIN as DEVICE_TRACKER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import Config
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TplinkDecoApi
from .const import DEFAULT_CONSIDER_HOME
from .const import DEFAULT_SCAN_INTERVAL
from .const import DOMAIN
from .const import PLATFORMS
from .const import STARTUP_MESSAGE
from .coordinator import TPLinkDecoClient
from .coordinator import TplinkDecoDataUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


def create_api(hass: HomeAssistant, data: dict[str:Any]):
    host = data.get(CONF_HOST)
    username = data.get(CONF_USERNAME)
    password = data.get(CONF_PASSWORD)
    session = async_get_clientsession(hass)

    return TplinkDecoApi(host, username, password, session)


async def async_create_coordinator(
    hass: HomeAssistant, entry: ConfigEntry, api: TplinkDecoApi
):
    consider_home_seconds = entry.data.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME)
    scan_interval_seconds = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    # Load tracked entities from registry
    existing_entries = entity_registry.async_entries_for_config_entry(
        entity_registry.async_get(hass),
        entry.entry_id,
    )
    data = {}

    # Populate client list with existing entries so that we keep track of disconnected clients
    # since deco list_clients only returns connected clients.
    for entry in existing_entries:
        if entry.domain == DEVICE_TRACKER_DOMAIN:
            client = TPLinkDecoClient(api.host, entry.unique_id)
            client.name = entry.original_name
            data[entry.unique_id] = client
    coordinator = TplinkDecoDataUpdateCoordinator(
        hass, api, timedelta(seconds=scan_interval_seconds), consider_home_seconds, data
    )
    await coordinator.async_config_entry_first_refresh()

    return coordinator


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    api = create_api(hass, entry.data)
    hass.data[DOMAIN][entry.entry_id] = await async_create_coordinator(hass, entry, api)

    for platform in PLATFORMS:
        hass.async_add_job(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    entry.async_on_unload(entry.add_update_listener(update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator is not None:
        await coordinator.async_close()

    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    if entry.data == entry.options:
        _LOGGER.debug("update_listener: No changes in options for %s", entry.entry_id)
        return

    _LOGGER.debug("update_listener: Updating options and reloading %s", entry.entry_id)
    hass.config_entries.async_update_entry(
        entry=entry,
        data=entry.options.copy(),
    )
    await async_reload_entry(hass, entry)
