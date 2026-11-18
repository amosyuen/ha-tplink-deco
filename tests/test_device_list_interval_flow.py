"""Validate serializable Deco device-list intervals in setup and options."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView
import pytest
import voluptuous as vol

from custom_components.tplink_deco import config_flow
from custom_components.tplink_deco.const import CONF_DEVICE_LIST_INTERVAL
from custom_components.tplink_deco.const import CONF_EXPOSE_WIFI_SSIDS
from custom_components.tplink_deco.const import DOMAIN


def _values(device_interval: object = "0") -> dict[str, object]:
    """Provide isolated form data without real Deco login credentials."""
    return {
        CONF_HOST: "http://192.0.2.1",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "test-only",
        CONF_SCAN_INTERVAL: "30",
        CONF_DEVICE_LIST_INTERVAL: device_interval,
    }


def _flow(kind: str) -> tuple[object, MagicMock]:
    """Create a mocked flow using the real integration form methods."""
    entry = SimpleNamespace(entry_id="mesh-one", data=_values())
    if kind == "setup":
        flow = config_flow.TplinkDecoFlowHandler()
        flow.handler = DOMAIN
    else:
        flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
        flow.handler = entry.entry_id
    flow.flow_id = "test-device-interval"
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    return flow, flow.hass


@pytest.mark.parametrize("value", [0, 5, 10, 60, 300, "300"])
def test_schema_is_serializable_and_uses_valid_defaults(value: object) -> None:
    """Use a continuous schema; validate the disjoint rule outside it."""
    schema = vol.Schema(config_flow._get_schema(_values(value)))
    view = _BaseFlowManagerView(MagicMock())
    result = view._prepare_result_json(
        {
            "type": FlowResultType.FORM,
            "data_schema": schema,
        }
    )
    assert json.dumps(result)
    fields = result["data_schema"]
    interval = next(
        item for item in fields if item["name"] == CONF_DEVICE_LIST_INTERVAL
    )
    expected = int(value) if int(value) == 0 or int(value) >= 10 else 30
    assert interval["default"] == expected


@pytest.mark.parametrize("kind", ["setup", "options"])
@pytest.mark.parametrize("value", [0, "0", 10, "10", 300, "300"])
@pytest.mark.asyncio
async def test_flow_persists_independent_numeric_interval(
    kind: str, value: object
) -> None:
    """Store integer values in either flow without changing main cadence."""
    flow, hass = _flow(kind)
    data = _values(value)
    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as credentials:
        if kind == "setup":
            await flow.async_step_user(data)
            saved = flow.async_create_entry.call_args.kwargs["data"]
        else:
            await flow.async_step_init(data)
            saved = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    credentials.assert_awaited_once()
    assert saved[CONF_SCAN_INTERVAL] == 30
    assert saved[CONF_DEVICE_LIST_INTERVAL] == int(value)
    assert saved[CONF_HOST] == "http://192.0.2.1"


@pytest.mark.parametrize("kind", ["setup", "options"])
@pytest.mark.parametrize("value", [-1, 1, 9, "9", "bad", None, True, 1.5])
@pytest.mark.asyncio
async def test_invalid_interval_rejects_before_authentication(
    kind: str, value: object
) -> None:
    """Do not attempt router login or change persisted values on bad input."""
    flow, hass = _flow(kind)
    submitted_data = _values(value)
    original_data = dict(submitted_data)
    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as credentials:
        if kind == "setup":
            result = await flow.async_step_user(submitted_data)
        else:
            result = await flow.async_step_init(submitted_data)
    assert submitted_data == original_data
    assert result["errors"] == {
        CONF_DEVICE_LIST_INTERVAL: "invalid_device_list_interval"
    }
    credentials.assert_not_awaited()
    flow.async_create_entry.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


def test_legacy_form_inherits_existing_scan_interval() -> None:
    """Avoid changing device polling on existing entries lacking the new key."""
    schema = vol.Schema(config_flow._get_schema({CONF_SCAN_INTERVAL: 60}))
    key = next(
        marker for marker in schema.schema if marker.schema == CONF_DEVICE_LIST_INTERVAL
    )
    assert key.default() == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["setup", "options"])
@pytest.mark.parametrize(
    ("field_name", "invalid_value", "corrected_value", "error_code"),
    [
        (CONF_DEVICE_LIST_INTERVAL, 5, "10", "invalid_device_list_interval"),
        (CONF_DEVICE_LIST_INTERVAL, 9, "300", "invalid_device_list_interval"),
        (CONF_SCAN_INTERVAL, "15", "60", "invalid_scan_interval"),
    ],
)
async def test_invalid_interval_can_be_corrected_in_same_flow(
    kind: str,
    field_name: str,
    invalid_value: int | str,
    corrected_value: str,
    error_code: str,
) -> None:
    """Complete the same setup/options flow after a rejected polling interval."""
    flow, hass = _flow(kind)
    entry = hass.config_entries.async_get_known_entry.return_value
    original_data = dict(entry.data)
    invalid_data = _values()
    invalid_data[field_name] = invalid_value
    valid_data = _values()
    valid_data[field_name] = corrected_value
    original_invalid_data = dict(invalid_data)
    original_valid_data = dict(valid_data)
    step = flow.async_step_user if kind == "setup" else flow.async_step_init

    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as credentials:
        invalid_result = await step(invalid_data)

        assert invalid_data == original_invalid_data
        assert invalid_result["type"] == FlowResultType.FORM
        assert invalid_result["errors"] == {field_name: error_code}
        form_json = _BaseFlowManagerView(MagicMock())._prepare_result_json(
            {
                "type": FlowResultType.FORM,
                "data_schema": invalid_result["data_schema"],
            }
        )
        assert json.dumps(form_json)
        assert any(field["name"] == field_name for field in form_json["data_schema"])
        credentials.assert_not_awaited()
        flow.async_create_entry.assert_not_called()
        hass.config_entries.async_update_entry.assert_not_called()
        assert entry.data == original_data

        valid_result = await step(valid_data)

    assert valid_data == original_valid_data
    assert valid_result["type"] == "create_entry"
    credentials.assert_awaited_once()
    flow.async_create_entry.assert_called_once()
    if kind == "setup":
        hass.config_entries.async_update_entry.assert_not_called()
        saved = flow.async_create_entry.call_args.kwargs["data"]
    else:
        hass.config_entries.async_update_entry.assert_called_once()
        saved = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        flow.async_create_entry.assert_called_once_with(data={})

    assert credentials.await_args.args[1] == saved
    assert saved[CONF_HOST] == original_data[CONF_HOST]
    assert saved[CONF_USERNAME] == original_data[CONF_USERNAME]
    assert saved[CONF_SCAN_INTERVAL] == (
        int(corrected_value) if field_name == CONF_SCAN_INTERVAL else 30
    )
    assert saved[CONF_DEVICE_LIST_INTERVAL] == (
        int(corrected_value) if field_name == CONF_DEVICE_LIST_INTERVAL else 0
    )
    assert entry.data == original_data


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["setup", "options"])
async def test_invalid_ssid_consent_does_not_normalize_submitted_intervals(
    kind: str,
) -> None:
    """Reject invalid consent without modifying the submitted field values."""
    flow, hass = _flow(kind)
    submitted_data = _values("10")
    submitted_data[CONF_SCAN_INTERVAL] = "60"
    submitted_data[CONF_EXPOSE_WIFI_SSIDS] = "yes"
    original_data = dict(submitted_data)
    step = flow.async_step_user if kind == "setup" else flow.async_step_init

    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as credentials:
        result = await step(submitted_data)

    assert result["errors"] == {CONF_EXPOSE_WIFI_SSIDS: "invalid_expose_wifi_ssids"}
    assert submitted_data == original_data
    credentials.assert_not_awaited()
    flow.async_create_entry.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["setup", "options"])
async def test_auth_failure_and_retry_preserve_submitted_mapping(kind: str) -> None:
    """Retry a rejected login without modifying caller-owned interval values."""
    flow, hass = _flow(kind)
    entry = hass.config_entries.async_get_known_entry.return_value
    previous_data = dict(entry.data)
    submitted_data = _values("10")
    submitted_data[CONF_SCAN_INTERVAL] = "60"
    original_data = dict(submitted_data)
    step = flow.async_step_user if kind == "setup" else flow.async_step_init

    with patch.object(
        config_flow,
        "_async_test_credentials",
        AsyncMock(side_effect=[{"base": "invalid_auth"}, {}]),
    ) as credentials:
        failed_result = await step(submitted_data)
        assert failed_result["errors"] == {"base": "invalid_auth"}
        assert submitted_data == original_data
        assert entry.data == previous_data
        flow.async_create_entry.assert_not_called()
        hass.config_entries.async_update_entry.assert_not_called()

        successful_result = await step(submitted_data)

    assert successful_result["type"] == "create_entry"
    assert submitted_data == original_data
    assert credentials.await_count == 2
    for credential_call in credentials.await_args_list:
        checked_data = credential_call.args[1]
        assert checked_data[CONF_SCAN_INTERVAL] == 60
        assert checked_data[CONF_DEVICE_LIST_INTERVAL] == 10

    if kind == "setup":
        saved = flow.async_create_entry.call_args.kwargs["data"]
        hass.config_entries.async_update_entry.assert_not_called()
    else:
        saved = hass.config_entries.async_update_entry.call_args.kwargs["data"]
        hass.config_entries.async_update_entry.assert_called_once()
    assert saved[CONF_SCAN_INTERVAL] == 60
    assert saved[CONF_DEVICE_LIST_INTERVAL] == 10
    assert entry.data == previous_data


@pytest.mark.asyncio
async def test_options_storage_failure_preserves_submitted_mapping() -> None:
    """Leave submitted values and handler state intact on persistence failure."""
    flow, hass = _flow("options")
    entry = hass.config_entries.async_get_known_entry.return_value
    previous_data = dict(entry.data)
    submitted_data = _values("10")
    submitted_data[CONF_SCAN_INTERVAL] = "60"
    original_data = dict(submitted_data)
    hass.config_entries.async_update_entry.side_effect = RuntimeError(
        "simulated storage failure"
    )

    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as credentials:
        with pytest.raises(RuntimeError, match="simulated storage failure"):
            await flow.async_step_init(submitted_data)

    credentials.assert_awaited_once()
    hass.config_entries.async_update_entry.assert_called_once()
    flow.async_create_entry.assert_not_called()
    assert submitted_data == original_data
    assert flow.data == previous_data
    assert entry.data == previous_data
