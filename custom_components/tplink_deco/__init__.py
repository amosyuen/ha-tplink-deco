"""
Custom integration to integrate TP-Link Deco with Home Assistant.

For more details about this integration, please refer to
https://github.com/amosyuen/ha-tplink-deco
"""

import asyncio
from datetime import timedelta
import logging
from typing import Any
from typing import cast

from homeassistant.components.device_tracker.const import (
    DOMAIN as DEVICE_TRACKER_DOMAIN,
)
from homeassistant.components.device_tracker.const import CONF_CONSIDER_HOME
from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.helpers import device_registry
from homeassistant.helpers import entity_registry
from homeassistant.helpers import restore_state
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .api import TplinkDecoApi
from .const import ATTR_DEVICE_TYPE
from .const import CONF_CLIENT_POSTFIX
from .const import CONF_CLIENT_PREFIX
from .const import CONF_DECO_POSTFIX
from .const import CONF_DECO_PREFIX
from .const import CONF_TIMEOUT_ERROR_RETRIES
from .const import CONF_TIMEOUT_SECONDS
from .const import CONF_VERIFY_SSL
from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import DEFAULT_CONSIDER_HOME
from .const import DEFAULT_DECO_POSTFIX
from .const import DEFAULT_SCAN_INTERVAL
from .const import DEFAULT_TIMEOUT_ERROR_RETRIES
from .const import DEFAULT_TIMEOUT_SECONDS
from .const import DEVICE_TYPE_DECO
from .const import DOMAIN
from .const import PLATFORMS
from .const import SERVICE_REBOOT_DECO
from .coordinator import TpLinkDeco
from .coordinator import TpLinkDecoClient
from .coordinator import TpLinkDecoData
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_create_and_refresh_coordinators(
    hass: HomeAssistant,
    config_data: dict[str:Any],
    config_entry: ConfigEntry = None,
    consider_home_seconds=1,
    update_interval: timedelta = None,
    deco_data: TpLinkDecoData = None,
    client_data: dict[str:TpLinkDecoClient] = None,
):
    host = config_data.get(CONF_HOST)
    username = config_data.get(CONF_USERNAME)
    password = config_data.get(CONF_PASSWORD)
    timeout_error_retries = config_data.get(CONF_TIMEOUT_ERROR_RETRIES)
    timeout_seconds = config_data.get(CONF_TIMEOUT_SECONDS)
    verify_ssl = config_data.get(CONF_VERIFY_SSL)
    session = async_get_clientsession(hass)

    api = TplinkDecoApi(
        session,
        host,
        username,
        password,
        verify_ssl,
        timeout_error_retries,
        timeout_seconds,
    )
    deco_coordinator = TplinkDecoUpdateCoordinator(
        hass, api, config_entry, update_interval, deco_data
    )
    if config_entry is None:
        await deco_coordinator._async_update_data()
    else:
        await deco_coordinator.async_config_entry_first_refresh()
    clients_coordinator = TplinkDecoClientUpdateCoordinator(
        hass,
        api,
        config_entry,
        deco_coordinator,
        consider_home_seconds,
        update_interval,
        client_data,
    )
    if config_entry is None:
        await deco_coordinator._async_update_data()
    else:
        await clients_coordinator.async_config_entry_first_refresh()

    return {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: clients_coordinator,
    }


async def async_create_config_data(hass: HomeAssistant, config_entry: ConfigEntry):
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
    last_states = restore_state.async_get(hass).last_states
    for entry in existing_entries:
        if entry.domain != DEVICE_TRACKER_DOMAIN:
            continue
        state = last_states.get(entry.entity_id)
        if state is None:
            continue
        device_type = state.state.attributes.get(ATTR_DEVICE_TYPE)
        if device_type is None:
            continue
        if device_type == DEVICE_TYPE_DECO:
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
        config_entry,
        consider_home_seconds,
        update_interval,
        deco_data,
        client_data,
    )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up this integration using UI."""
    _LOGGER.debug("async_setup_entry: Config entry %s", config_entry.entry_id)

    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})

    data = await async_create_config_data(hass, config_entry)
    hass.data[DOMAIN][config_entry.entry_id] = data
    deco_coordinator = data[COORDINATOR_DECOS_KEY]

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    )

    async def async_reboot_deco(service: ServiceCall) -> None:
        dr = device_registry.async_get(hass=hass)
        device_ids = cast([str], service.data.get(ATTR_DEVICE_ID))
        macs = []
        for device_id in device_ids:
            device = dr.async_get(device_id)
            if device is None:
                raise Exception(f"Device ID {device_id} is not a TP-Link Deco device")
            ids = device.identifiers
            id = next(iter(ids)) if len(ids) == 1 else None
            if id[0] != DOMAIN:
                raise Exception(
                    f"Device ID {device_id} does not have {DOMAIN} MAC identifier"
                )
            macs.append(id[1])
        await deco_coordinator.api.async_reboot_decos(macs)

    hass.services.async_register(
        DOMAIN,
        SERVICE_REBOOT_DECO,
        async_reboot_deco,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list(str), [str]),
            }
        ),
    )

    config_entry.async_on_unload(config_entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    _LOGGER.debug("async_unload_entry: Config entry %s", config_entry.entry_id)
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
    _LOGGER.debug("async_reload_entry: Config entry %s", config_entry)
    await async_unload_entry(hass, config_entry)
    await async_setup_entry(hass, config_entry)


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update options."""
    _LOGGER.debug("update_listener: Reloading %s", config_entry.entry_id)
    await async_reload_entry(hass, config_entry)


async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    new = {**config_entry.data}

    if config_entry.version == 1:
        config_entry.version = 2
        new[CONF_VERIFY_SSL] = True

    if config_entry.version == 2:
        config_entry.version = 3
        new[CONF_TIMEOUT_ERROR_RETRIES] = DEFAULT_TIMEOUT_ERROR_RETRIES

    if config_entry.version == 3:
        config_entry.version = 4
        new[CONF_TIMEOUT_SECONDS] = DEFAULT_TIMEOUT_SECONDS

    if config_entry.version == 4:
        config_entry.version = 5
        new[CONF_CLIENT_PREFIX] = ""
        new[CONF_CLIENT_POSTFIX] = ""
        new[CONF_DECO_PREFIX] = ""
        new[CONF_DECO_POSTFIX] = DEFAULT_DECO_POSTFIX

    if config_entry.version == 5:
        config_entry.version = 6
        new[CONF_HOST] = f"http://{new[CONF_HOST]}"

    hass.config_entries.async_update_entry(config_entry, data=new)

    _LOGGER.info("Migration to version %s successful", config_entry.version)

    return True
