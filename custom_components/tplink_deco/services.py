"""Privacy-conscious, integration-wide TP-Link Deco system-log action."""

from datetime import datetime
from datetime import timezone
import os
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.core import ServiceResponse
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .const import SERVICE_DOWNLOAD_SYSTEM_LOG
from .system_log import SystemLogLevel

ATTR_FILENAME = "filename"
ATTR_LOG_LEVEL = "log_level"
SYSTEM_LOG_DIR = "tplink_deco_logs"
SAFE_LOG_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,122}\.log", re.ASCII)
WINDOWS_RESERVED = re.compile(
    r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE
)

DOWNLOAD_SYSTEM_LOG_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_FILENAME): cv.string,
        vol.Optional(ATTR_LOG_LEVEL, default=SystemLogLevel.ALL.name): vol.All(
            vol.In(tuple(SystemLogLevel.__members__)), SystemLogLevel.__getitem__
        ),
    }
)


def _get_target_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry:
    """Select one loaded TP-Link Deco entry without cross-entry ambiguity."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if entry_id is None:
        if not entries:
            raise ServiceValidationError("No TP-Link Deco entry is loaded")
        if len(entries) != 1:
            raise ServiceValidationError(
                "Multiple TP-Link Deco entries loaded; supply config_entry_id"
            )
        return entries[0]

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError("Selected entry is not a TP-Link Deco entry")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("Selected TP-Link Deco entry is not loaded")
    return entry


def _log_filename(value: str | None) -> str:
    """Generate or validate one safe filename, without accepting directory parts."""
    filename = value or f"deco-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.log"
    if not SAFE_LOG_FILENAME.fullmatch(filename) or WINDOWS_RESERVED.match(filename):
        raise ServiceValidationError(
            "filename must be a plain ASCII .log filename without directory parts"
        )
    return filename


def _write_log_file(path: str, log_text: str) -> None:
    """Create a private log file atomically without overwriting existing data."""
    output_directory = os.path.dirname(path)
    os.makedirs(output_directory, mode=0o700, exist_ok=True)
    if os.path.islink(output_directory):
        raise OSError("System log directory must not be a symbolic link")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as log_file:
            log_file.write(log_text)
    except BaseException:
        # fdopen can fail before taking ownership of descriptor, while a
        # failed write or buffered close can leave an incomplete export.
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the manual action once, resolving its entry at call time."""

    async def async_download_system_log(call: ServiceCall) -> ServiceResponse:
        """Fetch a bounded snapshot only when the action is explicitly called."""
        entry = _get_target_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        filename = _log_filename(call.data.get(ATTR_FILENAME))
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if not isinstance(entry_data, dict):
            raise ServiceValidationError("Selected TP-Link Deco entry is unavailable")
        deco_coordinator = entry_data.get(COORDINATOR_DECOS_KEY)
        if deco_coordinator is None:
            raise ServiceValidationError("Selected TP-Link Deco entry is unavailable")
        log_text = await deco_coordinator.api.async_get_system_log(
            call.data[ATTR_LOG_LEVEL]
        )
        path = hass.config.path(SYSTEM_LOG_DIR, filename)
        write_failed = False
        try:
            await hass.async_add_executor_job(_write_log_file, path, log_text)
        except OSError:
            # Raise outside the handler to prevent private paths in exception context.
            write_failed = True
        if write_failed:
            raise ServiceValidationError(
                "Unable to save system log; filename already exists or storage is inaccessible"
            )
        return {"path": path, "line_count": len(log_text.splitlines())}

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_SYSTEM_LOG,
        async_download_system_log,
        schema=DOWNLOAD_SYSTEM_LOG_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
