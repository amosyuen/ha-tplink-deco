"""Privacy-safe and transactional Deco config-flow failure regressions."""

import asyncio
from copy import deepcopy
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import ConfigEntryNotReady
import pytest

from custom_components.tplink_deco import config_flow
from custom_components.tplink_deco.const import CONF_CLIENT_PREFIX
from custom_components.tplink_deco.const import CONF_DEVICE_LIST_INTERVAL
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import COORDINATOR_MOBILE_KEY
from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY
from custom_components.tplink_deco.exceptions import TimeoutException

SECRET = "secret-router-password-012345"
CONFIG_DATA = {
    CONF_HOST: "http://192.0.2.1",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: SECRET,
    CONF_SCAN_INTERVAL: 30,
    CONF_DEVICE_LIST_INTERVAL: 0,
    CONF_CLIENT_PREFIX: "Private naming preference",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (TimeoutException(SECRET), "timeout_connect"),
        (asyncio.TimeoutError(SECRET), "timeout_connect"),
        (ConfigEntryAuthFailed(SECRET), "invalid_auth"),
        (ConfigEntryNotReady(SECRET), "invalid_host"),
        (aiohttp.ClientConnectionError(SECRET), "invalid_host"),
        (ValueError(SECRET), "unknown"),
    ],
)
async def test_credential_failures_are_classified_without_sensitive_logs(
    failure: Exception,
    expected_error: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Return fixed UI error codes without logging raw router exceptions."""
    hass = MagicMock()
    with (
        patch.object(
            config_flow,
            "async_create_and_refresh_coordinators",
            new=AsyncMock(side_effect=failure),
        ) as refresh,
        caplog.at_level(logging.DEBUG, logger=config_flow.__name__),
    ):
        errors = await config_flow._async_test_credentials(hass, CONFIG_DATA)

    assert errors == {"base": expected_error}
    refresh.assert_awaited_once_with(hass, CONFIG_DATA)
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_unexpected_coordinator_shutdown_failure_returns_safe_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Report failed temporary-coordinator cleanup without raw error text."""
    coordinator = SimpleNamespace(
        async_shutdown=AsyncMock(side_effect=RuntimeError(SECRET))
    )
    with (
        patch.object(
            config_flow,
            "async_create_and_refresh_coordinators",
            new=AsyncMock(return_value={COORDINATOR_DECOS_KEY: coordinator}),
        ),
        caplog.at_level(logging.DEBUG, logger=config_flow.__name__),
    ):
        errors = await config_flow._async_test_credentials(MagicMock(), CONFIG_DATA)

    assert errors == {"base": "unknown"}
    coordinator.async_shutdown.assert_awaited_once_with()
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_successful_credential_check_shuts_down_all_known_coordinators() -> None:
    """Close each temporary coordinator before reporting valid credentials."""
    coordinators = {
        key: SimpleNamespace(async_shutdown=AsyncMock())
        for key in (
            COORDINATOR_DECOS_KEY,
            COORDINATOR_CLIENTS_KEY,
            COORDINATOR_WIRELESS_KEY,
            COORDINATOR_MOBILE_KEY,
        )
    }
    with patch.object(
        config_flow,
        "async_create_and_refresh_coordinators",
        new=AsyncMock(return_value=coordinators),
    ):
        assert await config_flow._async_test_credentials(MagicMock(), CONFIG_DATA) == {}

    for coordinator in coordinators.values():
        coordinator.async_shutdown.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cancelled_credential_check_is_not_swallowed() -> None:
    """Let Home Assistant cancellation propagate instead of showing an error."""
    with patch.object(
        config_flow,
        "async_create_and_refresh_coordinators",
        new=AsyncMock(side_effect=asyncio.CancelledError()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await config_flow._async_test_credentials(MagicMock(), CONFIG_DATA)


@pytest.mark.asyncio
async def test_failed_options_verification_does_not_commit_tentative_settings() -> None:
    """Reject bad credentials without changing the handler or stored options."""
    saved_data = deepcopy(CONFIG_DATA)
    entry = SimpleNamespace(entry_id="mesh-one", data=saved_data)
    flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
    flow.handler = entry.entry_id
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.async_show_form = MagicMock(return_value={"type": "form"})
    submitted = {
        CONF_USERNAME: "different-user",
        CONF_PASSWORD: "bad-password",
        CONF_CLIENT_PREFIX: "New preference",
    }
    original = deepcopy(flow.data)

    with patch.object(
        config_flow,
        "_async_test_credentials",
        new=AsyncMock(return_value={"base": "invalid_auth"}),
    ) as credentials:
        response = await flow.async_step_init(submitted)

    assert response == {"type": "form"}
    assert flow._errors == {"base": "invalid_auth"}
    assert flow.data == original
    assert entry.data == saved_data
    credentials.assert_awaited_once()
    candidate_data = credentials.await_args.args[1]
    assert candidate_data[CONF_USERNAME] == "different-user"
    assert candidate_data[CONF_CLIENT_PREFIX] == "New preference"
    flow.hass.config_entries.async_update_entry.assert_not_called()
    flow.async_show_form.assert_called_once()


@pytest.mark.asyncio
async def test_successful_options_verification_commits_staged_settings() -> None:
    """Save the updated options only after credential verification succeeds."""
    entry = SimpleNamespace(entry_id="mesh-two", data=deepcopy(CONFIG_DATA))
    flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
    flow.handler = entry.entry_id
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    submitted = {
        CONF_USERNAME: "different-user",
        CONF_PASSWORD: "valid-password",
        CONF_CLIENT_PREFIX: "Updated preference",
    }

    with patch.object(
        config_flow,
        "_async_test_credentials",
        new=AsyncMock(return_value={}),
    ) as credentials:
        result = await flow.async_step_init(submitted)

    assert result == {"type": "create_entry"}
    credentials.assert_awaited_once()
    assert flow.data[CONF_USERNAME] == "different-user"
    assert flow.data[CONF_CLIENT_PREFIX] == "Updated preference"
    flow.hass.config_entries.async_update_entry.assert_called_once_with(
        entry=entry,
        title=CONFIG_DATA[CONF_HOST],
        data=flow.data,
        options={},
    )


@pytest.mark.asyncio
async def test_reauth_unexpected_firmware_error_returns_safe_form(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not expose a router error or persist credentials after failed reauth."""
    entry = SimpleNamespace(entry_id="mesh-reauth", data=deepcopy(CONFIG_DATA))
    flow = config_flow.TplinkDecoFlowHandler()
    flow.reauth_entry = entry
    flow.hass = MagicMock()
    flow.hass.config_entries.async_reload = AsyncMock()
    flow.async_show_form = MagicMock(return_value={"type": "form"})
    original = deepcopy(entry.data)

    with (
        patch.object(
            config_flow,
            "async_create_and_refresh_coordinators",
            new=AsyncMock(side_effect=RuntimeError(SECRET)),
        ),
        caplog.at_level(logging.DEBUG, logger=config_flow.__name__),
    ):
        result = await flow.async_step_reauth_confirm(
            {CONF_USERNAME: "replacement", CONF_PASSWORD: "replacement-password"}
        )

    assert result == {"type": "form"}
    assert flow._errors == {"base": "unknown"}
    assert flow.async_show_form.call_args.kwargs["errors"] == {"base": "unknown"}
    assert entry.data == original
    flow.hass.config_entries.async_update_entry.assert_not_called()
    flow.hass.config_entries.async_reload.assert_not_awaited()
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_failed_options_persistence_leaves_handler_data_unchanged() -> None:
    """Do not accept staged settings when Home Assistant rejects the write."""
    entry = SimpleNamespace(entry_id="mesh-write", data=deepcopy(CONFIG_DATA))
    flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
    flow.handler = entry.entry_id
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.hass.config_entries.async_update_entry.side_effect = RuntimeError(
        "simulated storage failure"
    )
    flow.async_create_entry = MagicMock()
    original = deepcopy(flow.data)

    with patch.object(
        config_flow,
        "_async_test_credentials",
        new=AsyncMock(return_value={}),
    ) as credentials:
        with pytest.raises(RuntimeError, match="simulated storage failure"):
            await flow.async_step_init(
                {
                    CONF_USERNAME: "updated",
                    CONF_PASSWORD: "new-password",
                    CONF_CLIENT_PREFIX: "Updated preference",
                }
            )

    credentials.assert_awaited_once()
    flow.hass.config_entries.async_update_entry.assert_called_once()
    flow.async_create_entry.assert_not_called()
    assert flow.data == original
    assert entry.data == original
