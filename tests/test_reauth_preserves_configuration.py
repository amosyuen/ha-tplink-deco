"""Regressions for preserving TP-Link Deco settings during reauthentication."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
import pytest

from custom_components.tplink_deco import config_flow
from custom_components.tplink_deco.const import CONF_CLIENT_POSTFIX
from custom_components.tplink_deco.const import CONF_CLIENT_PREFIX
from custom_components.tplink_deco.const import CONF_DECO_POSTFIX
from custom_components.tplink_deco.const import CONF_DECO_PREFIX
from custom_components.tplink_deco.const import CONF_DEVICE_LIST_INTERVAL
from custom_components.tplink_deco.const import CONF_EXPOSE_WIFI_SSIDS
from custom_components.tplink_deco.const import CONF_LINK_CLIENT_DEVICES
from custom_components.tplink_deco.const import CONF_TIMEOUT_ERROR_RETRIES
from custom_components.tplink_deco.const import CONF_TIMEOUT_SECONDS
from custom_components.tplink_deco.const import CONF_VERIFY_SSL

BASE_CONFIG: dict[str, Any] = {
    CONF_HOST: "http://192.0.2.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "old-test-password",
    CONF_SCAN_INTERVAL: 60,
    CONF_DEVICE_LIST_INTERVAL: 0,
}
CUSTOM_OPTIONS: dict[str, Any] = {
    CONF_CLIENT_PREFIX: "Client prefix",
    CONF_CLIENT_POSTFIX: "Client postfix",
    CONF_DECO_PREFIX: "Mesh prefix",
    CONF_DECO_POSTFIX: "Mesh postfix",
    CONF_EXPOSE_WIFI_SSIDS: True,
    CONF_LINK_CLIENT_DEVICES: False,
    CONF_TIMEOUT_ERROR_RETRIES: 2,
    CONF_TIMEOUT_SECONDS: 40,
    CONF_VERIFY_SSL: False,
}


def _reauth_flow(
    saved_data: dict[str, Any],
) -> tuple[config_flow.TplinkDecoFlowHandler, SimpleNamespace]:
    """Build a real reauth handler without contacting a physical router."""
    entry = SimpleNamespace(entry_id="mesh-entry", data=deepcopy(saved_data))
    flow = config_flow.TplinkDecoFlowHandler()
    flow.reauth_entry = entry
    flow.hass = MagicMock()
    flow.hass.config_entries.async_reload = AsyncMock()
    flow.async_abort = MagicMock(
        return_value={"type": "abort", "reason": "reauth_successful"}
    )
    flow.async_show_form = MagicMock(
        return_value={"type": "form", "step_id": "reauth_confirm"}
    )
    return flow, entry


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "saved_data",
    [BASE_CONFIG, BASE_CONFIG | CUSTOM_OPTIONS],
    ids=("legacy-entry-without-names", "custom-names-and-options"),
)
async def test_reauth_replaces_only_credentials_and_preserves_saved_options(
    saved_data: dict[str, Any],
) -> None:
    """Reauth must not add blank names or reset existing per-entry settings."""
    flow, entry = _reauth_flow(saved_data)
    old_data = deepcopy(entry.data)
    credentials = {
        CONF_USERNAME: "new-admin",
        CONF_PASSWORD: "new-test-password",
    }
    expected_data = old_data | credentials

    with patch.object(
        config_flow,
        "_async_test_credentials",
        AsyncMock(return_value={}),
    ) as check_credentials:
        result = await flow.async_step_reauth_confirm(credentials)

    assert result == {"type": "abort", "reason": "reauth_successful"}
    check_credentials.assert_awaited_once_with(flow.hass, expected_data)
    flow.hass.config_entries.async_update_entry.assert_called_once_with(
        entry, data=expected_data
    )
    flow.hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
    flow.async_abort.assert_called_once_with(reason="reauth_successful")
    flow.async_show_form.assert_not_called()
    assert entry.data == old_data
    assert credentials == {
        CONF_USERNAME: "new-admin",
        CONF_PASSWORD: "new-test-password",
    }
    for option in (
        CONF_CLIENT_PREFIX,
        CONF_CLIENT_POSTFIX,
        CONF_DECO_PREFIX,
        CONF_DECO_POSTFIX,
    ):
        assert (option in expected_data) is (option in old_data)


@pytest.mark.asyncio
async def test_invalid_reauth_does_not_change_saved_options_or_reload() -> None:
    """An authentication failure must leave stored configuration unchanged."""
    flow, entry = _reauth_flow(BASE_CONFIG | CUSTOM_OPTIONS)
    previous_data = deepcopy(entry.data)
    proposed_credentials = {
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "incorrect-password",
    }

    with patch.object(
        config_flow,
        "_async_test_credentials",
        AsyncMock(return_value={"base": "invalid_auth"}),
    ) as check_credentials:
        result = await flow.async_step_reauth_confirm(proposed_credentials)

    assert result == {"type": "form", "step_id": "reauth_confirm"}
    check_credentials.assert_awaited_once_with(
        flow.hass, previous_data | proposed_credentials
    )
    flow.async_show_form.assert_called_once()
    assert flow.async_show_form.call_args.kwargs["errors"] == {
        "base": "invalid_auth"
    }
    flow.hass.config_entries.async_update_entry.assert_not_called()
    flow.hass.config_entries.async_reload.assert_not_awaited()
    flow.async_abort.assert_not_called()
    assert entry.data == previous_data


@pytest.mark.asyncio
async def test_reauth_initial_form_is_credentials_only() -> None:
    """Opening the reauth dialog must not modify options or test credentials."""
    flow, entry = _reauth_flow(BASE_CONFIG | CUSTOM_OPTIONS)
    previous_data = deepcopy(entry.data)

    with patch.object(
        config_flow,
        "_async_test_credentials",
        AsyncMock(),
    ) as check_credentials:
        result = await flow.async_step_reauth_confirm()

    assert result == {"type": "form", "step_id": "reauth_confirm"}
    check_credentials.assert_not_awaited()
    flow.hass.config_entries.async_update_entry.assert_not_called()
    flow.hass.config_entries.async_reload.assert_not_awaited()
    assert entry.data == previous_data
