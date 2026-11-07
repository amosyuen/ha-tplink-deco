"""Integration-wide actions for TP-Link Deco.

Actions are registered once and resolve their target config entry at call
time, so they work with any number of Deco entries.
"""

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.core import ServiceResponse
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .const import SERVICE_DOWNLOAD_SYSTEM_LOG
from .system_log import SystemLogLevel

ATTR_FILENAME = "filename"
ATTR_LOG_LEVEL = "log_level"
SYSTEM_LOG_DIR = "tplink_deco_logs"

_LOGGER: logging.Logger = logging.getLogger(__name__)

DOWNLOAD_SYSTEM_LOG_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_FILENAME): cv.string,
        vol.Optional(ATTR_LOG_LEVEL, default=SystemLogLevel.ALL.name): vol.All(
            vol.In(SystemLogLevel.__members__), SystemLogLevel.__getitem__
        ),
    }
)


def _async_only_loaded_entry(hass: HomeAssistant) -> ConfigEntry:
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not loaded:
        raise ServiceValidationError("No TP-Link Deco entry is loaded")
    if len(loaded) > 1:
        raise ServiceValidationError(
            f"{len(loaded)} TP-Link Deco entries are loaded; set {ATTR_CONFIG_ENTRY_ID}"
            " to choose one"
        )
    return loaded[0]


def async_get_target_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    """Return the loaded entry an action targets.

    entry_id may be None only when exactly one entry is loaded.
    """
    if entry_id is None:
        return _async_only_loaded_entry(hass)

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"{entry_id} is not a TP-Link Deco entry")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"TP-Link Deco entry {entry.title} is not loaded")
    return entry


def _system_log_filename(filename: str | None) -> str:
    """Return filename, or a timestamped default, refusing any directory part."""
    filename = filename or f"deco-{dt_util.now():%Y%m%d-%H%M%S}.log"
    if os.path.basename(filename) != filename or filename in (".", ".."):
        raise ServiceValidationError(f"{ATTR_FILENAME} must not contain a directory")
    return filename


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def async_setup_services(hass: HomeAssistant) -> None:
    async def async_download_system_log(call: ServiceCall) -> ServiceResponse:
        entry = async_get_target_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        filename = _system_log_filename(call.data.get(ATTR_FILENAME))
        path = hass.config.path(SYSTEM_LOG_DIR, filename)

        api = hass.data[DOMAIN][entry.entry_id][COORDINATOR_DECOS_KEY].api
        text = await api.async_get_system_log(call.data[ATTR_LOG_LEVEL])

        await hass.async_add_executor_job(_write_text, path, text)
        line_count = len(text.splitlines())
        _LOGGER.info("Saved %d Deco system log lines to %s", line_count, path)
        return {"path": path, "line_count": line_count}

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_SYSTEM_LOG,
        async_download_system_log,
        schema=DOWNLOAD_SYSTEM_LOG_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
