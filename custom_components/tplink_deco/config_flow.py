"""Adds config flow for TP-Link Deco."""

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from homeassistant import config_entries
from homeassistant.components.device_tracker.const import CONF_CONSIDER_HOME
from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import selector
import voluptuous as vol

from .__init__ import async_create_and_refresh_coordinators
from .const import CONF_CLIENT_POSTFIX
from .const import CONF_CLIENT_PREFIX
from .const import CONF_DECO_POSTFIX
from .const import CONF_DECO_PREFIX
from .const import CONF_DEVICE_LIST_INTERVAL
from .const import CONF_EXPOSE_WIFI_SSIDS
from .const import CONF_LINK_CLIENT_DEVICES
from .const import CONF_TIMEOUT_ERROR_RETRIES
from .const import CONF_TIMEOUT_SECONDS
from .const import CONF_USE_HTTPS
from .const import CONF_VERIFY_SSL
from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import COORDINATOR_MOBILE_KEY
from .const import COORDINATOR_WIRELESS_KEY
from .const import DEFAULT_CONSIDER_HOME
from .const import DEFAULT_DECO_POSTFIX
from .const import DEFAULT_EXPOSE_WIFI_SSIDS
from .const import DEFAULT_LINK_CLIENT_DEVICES
from .const import DEFAULT_SCAN_INTERVAL
from .const import DEFAULT_TIMEOUT_ERROR_RETRIES
from .const import DEFAULT_TIMEOUT_SECONDS
from .const import DEFAULT_USE_HTTPS
from .const import DOMAIN
from .exceptions import HttpsRequiredException
from .exceptions import TimeoutException
from .exceptions import UnsafeRedirectException

_LOGGER: logging.Logger = logging.getLogger(__name__)

SCAN_INTERVAL_OPTIONS = (10, 30, 60, 120)
SCAN_INTERVAL_SELECTOR_OPTIONS = [str(value) for value in SCAN_INTERVAL_OPTIONS]


def _parse_scan_interval(value: Any) -> int | None:
    """Parse a supported interval without accepting booleans or floats."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        interval = int(value)
    except ValueError:
        return None
    return interval if interval in SCAN_INTERVAL_OPTIONS else None


def _get_scan_interval(data: dict[str, Any]) -> str:
    """Return a supported scan interval as a string for the form selector."""
    interval = _parse_scan_interval(data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    return str(interval if interval is not None else DEFAULT_SCAN_INTERVAL)


def _normalize_scan_interval(data: dict[str, Any]) -> bool:
    """Validate a submitted interval and preserve integer config storage."""
    if CONF_SCAN_INTERVAL not in data:
        return True
    interval = _parse_scan_interval(data[CONF_SCAN_INTERVAL])
    if interval is None:
        return False
    data[CONF_SCAN_INTERVAL] = interval
    return True


def _parse_device_list_interval(value: Any) -> int | None:
    """Accept startup-only zero or a positive interval of at least ten seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        interval = int(value)
    except ValueError:
        return None
    return interval if interval == 0 or interval >= 10 else None


def _normalize_device_list_interval(data: dict[str, Any]) -> bool:
    """Normalize the independent interval without changing the main cadence."""
    if CONF_DEVICE_LIST_INTERVAL not in data:
        return True
    interval = _parse_device_list_interval(data[CONF_DEVICE_LIST_INTERVAL])
    if interval is None:
        return False
    data[CONF_DEVICE_LIST_INTERVAL] = interval
    return True


def _valid_ssid_choice(data: dict[str, Any]) -> bool:
    """Reject non-boolean SSID consent before network access or persistence."""
    return CONF_EXPOSE_WIFI_SSIDS not in data or isinstance(
        data[CONF_EXPOSE_WIFI_SSIDS], bool
    )


def _transport_errors(data: dict[str, Any]) -> dict[str, str]:
    """Validate protocol consent and origin before any authentication attempt."""
    use_https = data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)
    if not isinstance(use_https, bool):
        return {CONF_USE_HTTPS: "invalid_use_https"}

    host = data.get(CONF_HOST)
    if not isinstance(host, str):
        return {CONF_HOST: "invalid_host_scheme"}
    try:
        parsed = urlsplit(host)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return {CONF_HOST: "invalid_host_scheme"}
        _ = parsed.port
    except ValueError:
        return {CONF_HOST: "invalid_host_scheme"}

    if not use_https and parsed.scheme != "http":
        return {CONF_HOST: "http_only_requires_http"}
    return {}


def _get_auth_schema(data: dict[str, Any]):
    if data is None:
        data = {}
    return {
        vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "admin")): str,
        vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
    }


def _get_schema(data: dict[str:Any]):
    if data is None:
        data = {}
    schema = _get_auth_schema(data)
    scan_interval = _get_scan_interval(data)
    device_list_interval = _parse_device_list_interval(
        data.get(CONF_DEVICE_LIST_INTERVAL, scan_interval)
    )
    if device_list_interval is None:
        device_list_interval = int(scan_interval)

    schema.update(
        {
            vol.Required(
                CONF_HOST, default=data.get(CONF_HOST, "http://192.168.0.1")
            ): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=scan_interval,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=SCAN_INTERVAL_SELECTOR_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_DEVICE_LIST_INTERVAL,
                default=device_list_interval,
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required(
                CONF_CONSIDER_HOME,
                default=data.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required(
                CONF_TIMEOUT_ERROR_RETRIES,
                default=data.get(
                    CONF_TIMEOUT_ERROR_RETRIES, DEFAULT_TIMEOUT_ERROR_RETRIES
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required(
                CONF_TIMEOUT_SECONDS,
                default=data.get(CONF_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
            ): vol.All(vol.Coerce(int), vol.Range(min=5)),
            vol.Required(
                CONF_VERIFY_SSL,
                default=data.get(CONF_VERIFY_SSL, True),
            ): bool,
            vol.Required(
                CONF_USE_HTTPS,
                default=data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS),
            ): bool,
            vol.Required(
                CONF_LINK_CLIENT_DEVICES,
                default=data.get(CONF_LINK_CLIENT_DEVICES, DEFAULT_LINK_CLIENT_DEVICES),
            ): bool,
            vol.Required(
                CONF_EXPOSE_WIFI_SSIDS,
                default=data.get(CONF_EXPOSE_WIFI_SSIDS, DEFAULT_EXPOSE_WIFI_SSIDS)
                is True,
            ): bool,
            vol.Optional(
                CONF_CLIENT_PREFIX,
                description={"suggested_value": data.get(CONF_CLIENT_PREFIX, "")},
            ): str,
            vol.Optional(
                CONF_CLIENT_POSTFIX,
                description={"suggested_value": data.get(CONF_CLIENT_POSTFIX, "")},
            ): str,
            vol.Optional(
                CONF_DECO_PREFIX,
                description={"suggested_value": data.get(CONF_DECO_PREFIX, "")},
            ): str,
            vol.Optional(
                CONF_DECO_POSTFIX,
                description={
                    "suggested_value": data.get(CONF_DECO_POSTFIX, DEFAULT_DECO_POSTFIX)
                },
            ): str,
        }
    )
    return schema


# We need to make sure the optional keys are set so that they get updated in update_listener async_update_entry() call
def _ensure_user_input_optionals(data: dict[str:Any]) -> None:
    for key in [
        CONF_CLIENT_PREFIX,
        CONF_CLIENT_POSTFIX,
        CONF_DECO_PREFIX,
        CONF_DECO_POSTFIX,
    ]:
        if key not in data:
            data[key] = ""


async def _async_test_credentials(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, str]:
    """Check credentials and expose only sanitized form errors."""
    try:
        coordinators = await async_create_and_refresh_coordinators(hass, data)
    except (TimeoutException, asyncio.TimeoutError):
        _LOGGER.debug("Deco credential check timed out")
        return {"base": "timeout_connect"}
    except HttpsRequiredException:
        _LOGGER.debug("Deco router enforces HTTPS for this connection")
        return {"base": "https_required"}
    except UnsafeRedirectException:
        _LOGGER.debug("Deco router returned a disallowed redirect")
        return {"base": "unsafe_redirect"}
    except ConfigEntryAuthFailed:
        _LOGGER.debug("Deco credentials rejected")
        return {"base": "invalid_auth"}
    except (ConfigEntryNotReady, aiohttp.ClientConnectionError):
        _LOGGER.debug("Deco host unavailable during credential check")
        return {"base": "invalid_host"}
    except Exception as err:
        # Upstream error messages may contain passwords, tokens or router URLs.
        _LOGGER.error(
            "Unexpected Deco credential check failure (%s)", type(err).__name__
        )
        return {"base": "unknown"}

    shutdown_results = await asyncio.gather(
        *(
            coordinator.async_shutdown()
            for key, coordinator in coordinators.items()
            if key
            in (
                COORDINATOR_DECOS_KEY,
                COORDINATOR_CLIENTS_KEY,
                COORDINATOR_MOBILE_KEY,
                COORDINATOR_WIRELESS_KEY,
            )
        ),
        return_exceptions=True,
    )
    for result in shutdown_results:
        if isinstance(result, asyncio.CancelledError):
            raise result

    for result in shutdown_results:
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result
            _LOGGER.error(
                "Unexpected Deco temporary coordinator shutdown failure (%s)",
                type(result).__name__,
            )
            return {"base": "unknown"}
    return {}


class TplinkDecoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for tplink_deco."""

    VERSION = 7
    reauth_entry: ConfigEntry = None

    def __init__(self):
        """Initialize."""
        self._errors = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if user_input is not None:
            candidate_data = dict(user_input)
            if not _normalize_scan_interval(candidate_data):
                self._errors = {CONF_SCAN_INTERVAL: "invalid_scan_interval"}
            elif not _normalize_device_list_interval(candidate_data):
                self._errors = {
                    CONF_DEVICE_LIST_INTERVAL: "invalid_device_list_interval"
                }
            elif not _valid_ssid_choice(candidate_data):
                self._errors = {CONF_EXPOSE_WIFI_SSIDS: "invalid_expose_wifi_ssids"}
            elif transport_errors := _transport_errors(candidate_data):
                self._errors = transport_errors
            else:
                candidate_data.setdefault(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)
                self._errors = await _async_test_credentials(self.hass, candidate_data)
            if not self._errors:
                _ensure_user_input_optionals(candidate_data)
                return self.async_create_entry(
                    title=candidate_data[CONF_HOST], data=candidate_data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(_get_schema(user_input)),
            errors=self._errors,
        )

    async def async_step_reauth(self, user_input=None):
        """Perform reauth upon an API authentication error."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Dialog that informs the user that reauth is required."""
        self._errors = {}

        if user_input is not None:
            data = dict(self.reauth_entry.data)
            data.update(user_input)

            self._errors = await _async_test_credentials(self.hass, data)
            if len(self._errors) == 0:
                self.hass.config_entries.async_update_entry(
                    self.reauth_entry, data=data
                )
                await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(_get_auth_schema(self.reauth_entry.data)),
            errors=self._errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return TplinkDecoOptionsFlowHandler(config_entry)


class TplinkDecoOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for tplink_deco."""

    def __init__(self, config_entry: ConfigEntry):
        """Initialize HACS options flow."""
        self.data = dict(config_entry.data)
        self._errors = {}

    async def async_step_init(self, user_input: dict[str:Any] = None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if user_input is not None:
            submitted_data = dict(user_input)
            if not _normalize_scan_interval(submitted_data):
                self._errors = {CONF_SCAN_INTERVAL: "invalid_scan_interval"}
            elif not _normalize_device_list_interval(submitted_data):
                self._errors = {
                    CONF_DEVICE_LIST_INTERVAL: "invalid_device_list_interval"
                }
            elif not _valid_ssid_choice(submitted_data):
                self._errors = {CONF_EXPOSE_WIFI_SSIDS: "invalid_expose_wifi_ssids"}
            elif transport_errors := _transport_errors({**self.data, **submitted_data}):
                self._errors = transport_errors
            else:
                _ensure_user_input_optionals(submitted_data)
                candidate_data = {**self.data, **submitted_data}
                candidate_data.setdefault(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)
                self._errors = await _async_test_credentials(self.hass, candidate_data)
            if not self._errors:
                self.hass.config_entries.async_update_entry(
                    entry=self.config_entry,
                    title=candidate_data[CONF_HOST],
                    data=candidate_data,
                    options={},
                )
                self.data = candidate_data
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_get_schema(self.data)),
            errors=self._errors,
        )
