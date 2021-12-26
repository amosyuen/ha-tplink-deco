"""Adds config flow for TP-Link Deco."""
import asyncio
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.components.device_tracker.const import (
    CONF_CONSIDER_HOME,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONSIDER_HOME,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .__init__ import create_api
from .const import DOMAIN
from .exceptions import AuthException

_LOGGER: logging.Logger = logging.getLogger(__package__)


def _get_schema(data):
    if data is None:
        data = {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "192.168.0.1")): str,
            vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "admin")): str,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=data.get(CONF_SCAN_INTERVAL, 30),
            ): vol.All(vol.Coerce(int), vol.Clamp(min=1)),
            vol.Optional(
                CONF_CONSIDER_HOME,
                default=data.get(
                    CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds()
                ),
            ): vol.All(vol.Coerce(int), vol.Clamp(min=0)),
        }
    )


async def _async_test_credentials(hass, data):
    """Return true if credentials is valid."""
    try:
        api = create_api(hass, data)
        await api.async_list_clients()
        return {}
    except asyncio.TimeoutError as err:
        return {"base": "timeout_connect"}
    except AuthException as err:
        _LOGGER.warn("Error authenticating credentials: %s", err)
        return {"base": "invalid_auth"}
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warn("Error testing credentials: %s", err)
        return {"base": "unknown"}


class TpLinkDecoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for tp_link_deco."""

    VERSION = 1
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

        return await self._show_config_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TpLinkDecoOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="user",
            data_schema=_get_schema(user_input),
            errors=self._errors,
        )


class TpLinkDecoOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for tp_link_deco."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.data = dict(config_entry.data)
        self._errors = {}

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if user_input is not None:
            self.data.update(user_input)

            self._errors = await _async_test_credentials(self.hass, self.data)
            if len(self._errors) == 0:
                return self.async_create_entry(
                    title=self.config_entry.data.get(CONF_HOST), data=self.data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_get_schema(self.data),
            errors=self._errors,
        )
