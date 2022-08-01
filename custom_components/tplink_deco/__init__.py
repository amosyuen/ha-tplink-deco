"""
Custom integration to integrate TP-Link Deco with Home Assistant.

For more details about this integration, please refer to
https://github.com/amosyuen/ha-tplink-deco
"""
import asyncio
import logging
from datetime import timedelta
from typing import Any
from typing import cast

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.device_tracker.const import CONF_CONSIDER_HOME
from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.components.device_tracker.const import (
    DOMAIN as DEVICE_TRACKER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import Config
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.helpers import entity_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TplinkDecoApi
from .const import CONFIG_VERIFY_SSL
from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import DEFAULT_CONSIDER_HOME
from .const import DEFAULT_SCAN_INTERVAL
from .const import DEVICE_CLASS_DECO
from .const import DOMAIN
from .const import PLATFORMS
from .const import SERVICE_REBOOT_DECO
from .coordinator import TpLinkDeco
from .coordinator import TpLinkDecoClient
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TpLinkDecoData
from .coordinator import TplinkDecoUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_create_and_refresh_coordinators(
    hass: HomeAssistant,
    config_data: dict[str:Any],
    consider_home_seconds,
    update_interval: timedelta = None,
    deco_data: TpLinkDecoData = TpLinkDecoData(),
    client_data: dict[str:TpLinkDecoClient] = {},
):
    host = config_data.get(CONF_HOST)
    username = config_data.get(CONF_USERNAME)
    password = config_data.get(CONF_PASSWORD)
    verify_ssl = config_data.get(CONFIG_VERIFY_SSL)
    session = async_get_clientsession(hass)

    api = TplinkDecoApi(host, username, password, verify_ssl, session)
    deco_coordinator = TplinkDecoUpdateCoordinator(
        hass, api, update_interval, deco_data
    )
    await deco_coordinator.async_config_entry_first_refresh()
    clients_coordinator = TplinkDecoClientUpdateCoordinator(
        hass,
        api,
        deco_coordinator,
        consider_home_seconds,
        update_interval,
        client_data,
    )
    await clients_coordinator.async_config_entry_first_refresh()

    return {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: clients_coordinator,
    }


async def async_create_coordinators(hass: HomeAssistant, config_entry: ConfigEntry):
    consider_home_seconds = config_entry.data.get(
        CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME
    )
    scan_interval_seconds = config_entry.data.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )
    update_interval = timedelta(seconds=scan_interval_seconds)

    # Load tracked entities from registry
    existing_entries = entity_registry.async_entries_for_config_entry(
        entity_registry.async_get(hass),
        config_entry.entry_id,
    )
    deco_data = TpLinkDecoData()
    client_data = {}

    # Populate client list with existing entries so that we keep track of disconnected clients
    # since deco list_clients only returns connected clients.
    for entry in existing_entries:
        if entry.domain == DEVICE_TRACKER_DOMAIN:
            if entry.original_device_class == DEVICE_CLASS_DECO:
                deco = TpLinkDeco(entry.unique_id)
                deco.name = entry.original_name
                deco_data.decos[entry.unique_id] = deco
            else:
                client = TpLinkDecoClient(entry.unique_id)
                client.name = entry.original_name
                client_data[entry.unique_id] = client

    return await async_create_and_refresh_coordinators(
        hass,
        config_entry.data,
        consider_home_seconds,
        update_interval,
        deco_data,
        client_data,
    )


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})

    data = await async_create_coordinators(hass, config_entry)
    hass.data[DOMAIN][config_entry.entry_id] = data
    deco_coordinator = data[COORDINATOR_DECOS_KEY]

    for platform in PLATFORMS:
        hass.async_add_job(
            hass.config_entries.async_forward_entry_setup(config_entry, platform)
        )

    async def async_reboot_deco(service: ServiceCall) -> None:
        entity_ids = cast([int], service.data.get(ATTR_ENTITY_ID))
        macs = []
        for entity_id in entity_ids:
            state = hass.states.get(entity_id)
            mac = state.attributes.get("mac") if state else None
            if mac is None:
                raise Exception(f"Entity ID {entity_id} does not have attributes.mac")
            macs.append(mac)
        await deco_coordinator.api.async_reboot_decos(macs)

    hass.services.async_register(
        DOMAIN,
        SERVICE_REBOOT_DECO,
        async_reboot_deco,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.All(
                    cv.ensure_list(cv.entity_id), [cv.entity_id]
                ),
            }
        ),
    )

    config_entry.async_on_unload(config_entry.add_update_listener(update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    deco_coordinator = data.get(COORDINATOR_DECOS_KEY)
    clients_coordinator = data.get(COORDINATOR_CLIENTS_KEY)
    if deco_coordinator is not None:
        await deco_coordinator.async_close()
    if clients_coordinator is not None:
        await clients_coordinator.async_close()

    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unloaded:
        hass.data[DOMAIN].pop(config_entry.entry_id)

    return unloaded


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, config_entry)
    await async_setup_entry(hass, config_entry)


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update options."""
    if config_entry.data == config_entry.options:
        _LOGGER.debug(
            "update_listener: No changes in options for %s", config_entry.entry_id
        )
        return

    _LOGGER.debug(
        "update_listener: Updating options and reloading %s", config_entry.entry_id
    )
    hass.config_entries.async_update_entry(
        entry=config_entry,
        data=config_entry.options.copy(),
    )
    await async_reload_entry(hass, config_entry)


async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:

        new = {**config_entry.data}
        # TODO: modify Config Entry data

        config_entry.version = 2
        new[CONFIG_VERIFY_SSL] = True
        hass.config_entries.async_update_entry(config_entry, data=new)

    _LOGGER.info("Migration to version %s successful", config_entry.version)

    return True
