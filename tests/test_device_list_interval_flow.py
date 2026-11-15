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
    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as credentials:
        if kind == "setup":
            result = await flow.async_step_user(_values(value))
        else:
            result = await flow.async_step_init(_values(value))
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
