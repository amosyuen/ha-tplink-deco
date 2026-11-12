"""Regression tests for serializable forms and Deco status intervals."""

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
from custom_components.tplink_deco.const import CONF_SYSLOG_ENABLED
from custom_components.tplink_deco.const import CONF_SYSLOG_HOST
from custom_components.tplink_deco.const import DOMAIN


def _data(interval=30):
    return {
        CONF_HOST: "http://192.0.2.1",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "test-password",
        CONF_SCAN_INTERVAL: "30",
        CONF_DEVICE_LIST_INTERVAL: interval,
    }


def _flow(kind):
    entry = SimpleNamespace(entry_id="test-entry", data=_data())
    if kind == "user":
        flow = config_flow.TplinkDecoFlowHandler()
        flow.handler = DOMAIN
    else:
        flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
        flow.handler = entry.entry_id
    flow.flow_id = "test-flow"
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    return flow, entry


async def _step(flow, kind, data=None):
    if kind == "user":
        return await flow.async_step_user(data)
    return await flow.async_step_init(data)


def _serialize(schema):
    # Exercise HA's actual HTTP conversion, including its version-specific serializer.
    view = _BaseFlowManagerView(MagicMock())
    result = view._prepare_result_json(
        {"type": FlowResultType.FORM, "data_schema": schema}
    )
    json.dumps(result)
    return result["data_schema"]


@pytest.mark.parametrize("interval", [0, 5, 10, 11, 30, 3600])
def test_full_schema_is_serializable(interval):
    schema = vol.Schema(config_flow._get_schema(_data(interval)))

    fields = _serialize(schema)

    field = next(item for item in fields if item["name"] == CONF_DEVICE_LIST_INTERVAL)
    assert field["default"] == interval


def test_old_disjoint_interval_schema_reproduces_serialization_error():
    legacy_serializer = pytest.importorskip(
        "voluptuous_serialize",
        reason="Only older HA versions use the legacy serializer",
    )
    schema = vol.Schema(
        {
            vol.Required(CONF_DEVICE_LIST_INTERVAL): vol.All(
                vol.Coerce(int), vol.Any(0, vol.Range(min=10))
            )
        }
    )

    with pytest.raises(ValueError, match="Unable to convert schema"):
        legacy_serializer.convert(schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user", "options"])
async def test_initial_flow_form_is_serializable(kind):
    flow, _entry = _flow(kind)

    result = await _step(flow, kind)

    assert result["type"] == "form"
    assert not result["errors"]
    _serialize(result["data_schema"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user", "options"])
@pytest.mark.parametrize("interval", range(1, 10))
async def test_short_interval_returns_field_error_without_router_access(kind, interval):
    flow, entry = _flow(kind)
    submitted = vol.Schema(config_flow._get_schema({}))(_data(interval))

    with patch.object(config_flow, "_async_test_credentials", AsyncMock()) as check:
        result = await _step(flow, kind, submitted)

    assert result["type"] == "form"
    assert result["errors"] == {
        CONF_DEVICE_LIST_INTERVAL: "invalid_device_list_interval"
    }
    check.assert_not_awaited()
    flow.async_create_entry.assert_not_called()
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert entry.data[CONF_DEVICE_LIST_INTERVAL] == 30
    fields = _serialize(result["data_schema"])
    field = next(item for item in fields if item["name"] == CONF_DEVICE_LIST_INTERVAL)
    assert field["default"] == interval


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user", "options"])
@pytest.mark.parametrize("interval", [0, 10, 11, 30, 60, 120, 3600, "0", "10", "33"])
async def test_valid_intervals_are_saved_without_clamping(kind, interval):
    flow, _entry = _flow(kind)
    submitted = vol.Schema(config_flow._get_schema({}))(_data(interval))

    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ):
        result = await _step(flow, kind, submitted)

    assert result["type"] == "create_entry"
    if kind == "user":
        saved = flow.async_create_entry.call_args.kwargs["data"]
    else:
        saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_DEVICE_LIST_INTERVAL] == int(interval)
    assert isinstance(saved[CONF_DEVICE_LIST_INTERVAL], int)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user", "options"])
async def test_correcting_invalid_interval_finishes_flow(kind):
    flow, _entry = _flow(kind)

    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as check:
        invalid = await _step(flow, kind, _data(5))
        check.assert_not_awaited()
        valid = await _step(flow, kind, _data(10))

    assert invalid["type"] == "form"
    assert valid["type"] == "create_entry"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user", "options"])
async def test_interval_validation_does_not_hide_syslog_validation(kind):
    flow, _entry = _flow(kind)
    submitted = _data(5) | {CONF_SYSLOG_ENABLED: True, CONF_SYSLOG_HOST: ""}

    with patch.object(config_flow, "_async_test_credentials", AsyncMock()) as check:
        result = await _step(flow, kind, submitted)

    assert result["errors"] == {
        CONF_DEVICE_LIST_INTERVAL: "invalid_device_list_interval",
        CONF_SYSLOG_HOST: "syslog_host_required",
    }
    check.assert_not_awaited()


def test_schema_rejects_negative_interval():
    schema = vol.Schema(config_flow._get_schema({}))

    with pytest.raises(vol.Invalid):
        schema(_data(-1))
