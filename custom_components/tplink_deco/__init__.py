"""
Custom integration to integrate TP-Link Deco with Home Assistant.

For more details about this integration, please refer to
https://github.com/amosyuen/ha-tplink-deco
"""

import asyncio
from collections.abc import Mapping
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
from homeassistant.helpers.device_registry import DeviceEntry
import voluptuous as vol

from .api import TplinkDecoApi
from .const import ATTR_DEVICE_TYPE
from .const import CONF_CLIENT_POSTFIX
from .const import CONF_CLIENT_PREFIX
from .const import CONF_DECO_POSTFIX
from .const import CONF_DECO_PREFIX
from .const import CONF_DEVICE_LIST_INTERVAL
from .const import CONF_LINK_CLIENT_DEVICES
from .const import CONF_TIMEOUT_ERROR_RETRIES
from .const import CONF_TIMEOUT_SECONDS
from .const import CONF_VERIFY_SSL
from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import COORDINATOR_WIRELESS_KEY
from .const import DEFAULT_CONSIDER_HOME
from .const import DEFAULT_DECO_POSTFIX
from .const import DEFAULT_LINK_CLIENT_DEVICES
from .const import DEFAULT_SCAN_INTERVAL
from .const import DEFAULT_TIMEOUT_ERROR_RETRIES
from .const import DEFAULT_TIMEOUT_SECONDS
from .const import DEVICE_TYPE_CLIENT
from .const import DEVICE_TYPE_DECO
from .const import DOMAIN
from .const import PLATFORMS
from .const import SERVICE_PAUSE_POLLING
from .const import SERVICE_REBOOT_DECO
from .const import SERVICE_RESUME_POLLING
from .coordinator import TpLinkDeco
from .coordinator import TpLinkDecoClient
from .coordinator import TpLinkDecoData
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator
from .wireless import TplinkDecoWirelessUpdateCoordinator

_LOGGER: logging.Logger = logging.getLogger(__name__)


def _deco_mac_from_identifiers(identifiers: set[tuple[str, str]]) -> str | None:
    """Find a nonempty TP-Link Deco MAC among device-registry identifiers."""
    return next(
        (mac for domain, mac in identifiers if domain == DOMAIN and mac),
        None,
    )


def _remove_discovered_decos_from_clients(
    client_data: dict[str, TpLinkDecoClient],
    deco_data: TpLinkDecoData,
) -> None:
    """Reconcile provisional client trackers with confirmed Deco devices."""
    for deco_mac in deco_data.decos:
        client_data.pop(deco_mac, None)


def _get_device_list_interval(
    config_data: dict[str, Any], update_interval: timedelta | None
) -> int:
    """Keep legacy scan cadence when the new option is absent or invalid."""
    fallback = (
        int(update_interval.total_seconds())
        if update_interval is not None
        else DEFAULT_SCAN_INTERVAL
    )
    raw_value = config_data.get(CONF_DEVICE_LIST_INTERVAL, fallback)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, str)):
        return fallback
    try:
        value = int(raw_value)
    except ValueError:
        return fallback
    return value if value == 0 or value >= 10 else fallback


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
        hass,
        api,
        config_entry,
        update_interval,
        deco_data,
        device_list_interval_seconds=_get_device_list_interval(
            config_data, update_interval
        ),
    )
    if config_entry is None:
        await deco_coordinator._async_update_data()
    else:
        await deco_coordinator.async_config_entry_first_refresh()

    # Unavailable restored trackers may lack device_type. Reclassify any
    # provisional client that the first device refresh confirms is a Deco.
    if client_data:
        _remove_discovered_decos_from_clients(client_data, deco_coordinator.data)

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
    # A configured entry starts its first client refresh in the background
    # after platforms have loaded, rather than blocking coordinator creation.

    wireless_coordinator = TplinkDecoWirelessUpdateCoordinator(
        hass, api, config_entry, deco_coordinator, update_interval
    )
    return {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: clients_coordinator,
        COORDINATOR_WIRELESS_KEY: wireless_coordinator,
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

    # Restore clients that are no longer returned by the online-only API.
    # HA 2026.11 offers a registry-aware lookup; older releases use last_states.
    restore_data = restore_state.async_get(hass)
    get_stored_state = getattr(restore_data, "async_get_stored_state", None)
    if get_stored_state is None:
        get_stored_state = restore_data.last_states.get

    for entry in existing_entries:
        if entry.domain != DEVICE_TRACKER_DOMAIN or entry.disabled_by is not None:
            continue
        stored_state = get_stored_state(entry.entity_id)
        if stored_state is None:
            continue
        restored_state = getattr(stored_state, "state", None)
        attributes = getattr(restored_state, "attributes", None)
        if not isinstance(attributes, Mapping):
            # Skip corrupt records without leaking private state in logs.
            _LOGGER.warning("Skipping tracker with malformed restored-state attributes")
            continue
        device_type = attributes.get(ATTR_DEVICE_TYPE)
        if device_type not in (DEVICE_TYPE_DECO, DEVICE_TYPE_CLIENT):
            # An unavailable Deco can lack the state discriminator. Its
            # device-registry identity remains authoritative even while
            # the node is missing from the first router response.
            device_id = getattr(entry, "device_id", None)
            if device_id is not None:
                device = device_registry.async_get(hass).async_get(device_id)
                if (
                    device is not None
                    and (DOMAIN, entry.unique_id) in device.identifiers
                ):
                    device_type = DEVICE_TYPE_DECO
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


async def async_pause_polling(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Pause Deco polling."""
    coordinator_decos = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR_DECOS_KEY]

    if coordinator_decos.paused:
        _LOGGER.info("TP-Link Deco polling is already paused")
        return

    coordinator_decos.paused = True
    _LOGGER.info("TP-Link Deco polling paused")


async def async_resume_polling(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Resume Deco polling."""
    coordinator_decos = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR_DECOS_KEY]

    if not coordinator_decos.paused:
        _LOGGER.info("TP-Link Deco polling is already running")
        return

    coordinator_decos.paused = False
    _LOGGER.info("TP-Link Deco polling resumed")
    await coordinator_decos.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up this integration using UI."""
    _LOGGER.debug("async_setup_entry: Config entry %s", config_entry.entry_id)

    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})

    data = await async_create_config_data(hass, config_entry)
    hass.data[DOMAIN][config_entry.entry_id] = data
    deco_coordinator = data[COORDINATOR_DECOS_KEY]
    wireless_coordinator = data.get(COORDINATOR_WIRELESS_KEY)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    async def async_reboot_deco(service: ServiceCall) -> None:
        dr = device_registry.async_get(hass=hass)
        device_ids = cast([str], service.data.get(ATTR_DEVICE_ID))
        macs = []
        for device_id in device_ids:
            device = dr.async_get(device_id)
            if device is None:
                raise Exception(f"Device ID {device_id} is not a TP-Link Deco device")
            mac = _deco_mac_from_identifiers(device.identifiers)
            if mac is None:
                raise Exception(
                    f"Device ID {device_id} does not have {DOMAIN} MAC identifier"
                )
            macs.append(mac)
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

    async def handle_pause_polling(service: ServiceCall) -> None:
        """Handle pause polling service."""
        await async_pause_polling(hass, config_entry)

    async def handle_resume_polling(service: ServiceCall) -> None:
        """Handle resume polling service."""
        await async_resume_polling(hass, config_entry)

    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE_POLLING,
        handle_pause_polling,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME_POLLING,
        handle_resume_polling,
    )

    config_entry.async_on_unload(config_entry.add_update_listener(update_listener))

    # Use async_refresh directly: async_request_refresh may schedule a
    # foreground debouncer task even when called from a background task.
    config_entry.async_create_background_task(
        hass,
        data[COORDINATOR_CLIENTS_KEY].async_refresh(),
        name="tplink_deco initial client refresh",
    )
    if wireless_coordinator is not None:
        config_entry.async_create_background_task(
            hass,
            wireless_coordinator.async_refresh(),
            name="tplink_deco initial wireless refresh",
        )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    _LOGGER.debug("async_unload_entry: Config entry %s", config_entry.entry_id)

    domain_data = hass.data.get(DOMAIN, {})
    data = domain_data.get(config_entry.entry_id)

    if data is None:
        _LOGGER.debug(
            "async_unload_entry: No stored data for config entry %s",
            config_entry.entry_id,
        )
        return True

    deco_coordinator = data.get(COORDINATOR_DECOS_KEY)
    clients_coordinator = data.get(COORDINATOR_CLIENTS_KEY)
    wireless_coordinator = data.get(COORDINATOR_WIRELESS_KEY)

    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if not unloaded:
        return False

    # Platform unload must succeed before stopping polling or releasing callbacks.
    for coordinator in (deco_coordinator, clients_coordinator, wireless_coordinator):
        if coordinator is not None:
            await coordinator.async_shutdown()

    # Only fork-specific Deco/client coordinators implement async_close.
    # Home Assistant's wireless DataUpdateCoordinator does not.
    for coordinator in (deco_coordinator, clients_coordinator):
        if coordinator is not None:
            await coordinator.async_close()

    if deco_coordinator is not None:
        await deco_coordinator.api.async_logout()

    hass.data[DOMAIN].pop(config_entry.entry_id, None)
    hass.services.async_remove(DOMAIN, SERVICE_PAUSE_POLLING)
    hass.services.async_remove(DOMAIN, SERVICE_RESUME_POLLING)
    return True


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update options."""
    _LOGGER.debug("update_listener: Reloading %s", config_entry.entry_id)
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow cleanup only of this entry's legacy MAC-linked client devices."""
    if config_entry.data.get(CONF_LINK_CLIENT_DEVICES, DEFAULT_LINK_CLIENT_DEVICES):
        return False
    if device_entry.config_entries != {config_entry.entry_id}:
        return False
    if device_entry.identifiers:
        # Keep Deco devices and devices with identities from other integrations.
        return False
    return any(
        connection_type == device_registry.CONNECTION_NETWORK_MAC
        for connection_type, _ in device_entry.connections
    )


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Upgrade stored options using Home Assistant's immutable entry API."""
    version = config_entry.version
    _LOGGER.debug("Migrating from version %s", version)
    new = dict(config_entry.data)

    if version == 1:
        version = 2
        new[CONF_VERIFY_SSL] = True

    if version == 2:
        version = 3
        new[CONF_TIMEOUT_ERROR_RETRIES] = DEFAULT_TIMEOUT_ERROR_RETRIES

    if version == 3:
        version = 4
        new[CONF_TIMEOUT_SECONDS] = DEFAULT_TIMEOUT_SECONDS

    if version == 4:
        version = 5
        new[CONF_CLIENT_PREFIX] = ""
        new[CONF_CLIENT_POSTFIX] = ""
        new[CONF_DECO_PREFIX] = ""
        new[CONF_DECO_POSTFIX] = DEFAULT_DECO_POSTFIX

    if version == 5:
        version = 6
        new[CONF_HOST] = f"http://{new[CONF_HOST]}"

    if version == 6:
        version = 7
        new.setdefault(CONF_LINK_CLIENT_DEVICES, DEFAULT_LINK_CLIENT_DEVICES)

    hass.config_entries.async_update_entry(config_entry, data=new, version=version)
    _LOGGER.info("Migration to version %s successful", version)
    return True
