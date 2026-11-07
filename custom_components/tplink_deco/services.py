"""Integration-wide actions for TP-Link Deco.

Actions are registered once for the integration and resolve their target
config entry at call time, so they work with any number of Deco entries.
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
from .const import SYSTEM_LOG_LEVELS

ATTR_FILENAME = "filename"
ATTR_LOG_LEVEL = "log_level"
DEFAULT_LOG_LEVEL = "ALL"
SYSTEM_LOG_DIR = "tplink_deco_logs"

_LOGGER: logging.Logger = logging.getLogger(__name__)

DOWNLOAD_SYSTEM_LOG_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_FILENAME): cv.string,
        vol.Optional(ATTR_LOG_LEVEL, default=DEFAULT_LOG_LEVEL): vol.In(
            list(SYSTEM_LOG_LEVELS)
        ),
    }
)


def async_get_target_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    """Return the loaded entry an action targets.

    entry_id may be omitted only when exactly one entry is loaded.
    """
    if entry_id is None:
        loaded = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        if len(loaded) == 1:
            return loaded[0]
        if not loaded:
            raise ServiceValidationError("No TP-Link Deco entry is loaded")
        raise ServiceValidationError(
            f"{len(loaded)} TP-Link Deco entries are loaded; set {ATTR_CONFIG_ENTRY_ID}"
            " to choose one"
        )

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"{entry_id} is not a TP-Link Deco entry")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"TP-Link Deco entry {entry.title} is not loaded")
    return entry


def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration-wide actions."""

    async def async_download_system_log(call: ServiceCall) -> ServiceResponse:
        """Save the Deco system log to a file in the config directory."""
        entry = async_get_target_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))

        filename = call.data.get(ATTR_FILENAME) or (
            f"deco-{dt_util.now():%Y%m%d-%H%M%S}.log"
        )
        if os.path.basename(filename) != filename or filename in (".", ".."):
            raise ServiceValidationError(
                f"{ATTR_FILENAME} must not contain a directory"
            )
        path = hass.config.path(SYSTEM_LOG_DIR, filename)

        api = hass.data[DOMAIN][entry.entry_id][COORDINATOR_DECOS_KEY].api
        system_log = await api.async_get_system_log(
            SYSTEM_LOG_LEVELS[call.data[ATTR_LOG_LEVEL]]
        )
        lines = system_log.lines

        def write_file():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("".join(f"{line}\n" for line in lines))

        await hass.async_add_executor_job(write_file)
        _LOGGER.info("Saved %d Deco system log lines to %s", len(lines), path)
        return {
            "path": path,
            "line_count": len(lines),
            "complete": system_log.complete,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_SYSTEM_LOG,
        async_download_system_log,
        schema=DOWNLOAD_SYSTEM_LOG_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
