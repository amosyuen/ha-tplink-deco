"""Adds config flow for TP-Link Deco."""
import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.device_tracker.const import CONF_CONSIDER_HOME
from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import callback
from homeassistant.core import HomeAssistant

from .__init__ import async_create_and_refresh_coordinators
from .const import CONFIG_VERIFY_SSL
from .const import DEFAULT_CONSIDER_HOME
from .const import DEFAULT_SCAN_INTERVAL
from .const import DOMAIN
from .exceptions import AuthException

_LOGGER: logging.Logger = logging.getLogger(__package__)


def _get_schema(data: dict[str:Any]):
    if data is None:
        data = {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "192.168.0.1")): str,
            vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "admin")): str,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required(
                CONF_CONSIDER_HOME,
                default=data.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required(
                CONFIG_VERIFY_SSL,
                default=data.get(CONFIG_VERIFY_SSL, True),
            ): bool,
        }
    )


async def _async_test_credentials(hass: HomeAssistant, data: dict[str:Any]):
    """Return true if credentials is valid."""
    try:
        await async_create_and_refresh_coordinators(hass, data, consider_home_seconds=1)
        return {}
    except asyncio.TimeoutError:
        return {"base": "timeout_connect"}
    except AuthException as err:
        _LOGGER.warn("Error authenticating credentials: %s", err)
        return {"base": "invalid_auth"}
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warn("Error testing credentials: %s", err)
        return {"base": "unknown"}


class TplinkDecoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for tplink_deco."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if user_input is not None:
            self._errors = await _async_test_credentials(self.hass, user_input)
            if len(self._errors) == 0:
                return self.async_create_entry(
                    title=user_input[CONF_HOST], data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_get_schema(user_input),
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
        self.config_entry = config_entry
        self.data = dict(config_entry.data)
        self._errors = {}

    async def async_step_init(self, user_input: dict[str:Any] = None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if user_input is not None:
            self.data.update(user_input)

            self._errors = await _async_test_credentials(self.hass, self.data)
            if len(self._errors) == 0:
                return self.async_create_entry(
                    title=self.data.get(CONF_HOST), data=self.data
                )

        return self.async_show_form(
            step_id="init",
            data_schema=_get_schema(self.data),
            errors=self._errors,
        )
