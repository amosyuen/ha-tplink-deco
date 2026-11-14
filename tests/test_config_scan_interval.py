"""Regression tests for serializable scan-interval setup and options flows."""

from types import SimpleNamespace
import json
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView
from homeassistant.helpers import selector
import pytest
import voluptuous as vol

from custom_components.tplink_deco import config_flow
from custom_components.tplink_deco.const import DOMAIN

SCANS = (10, 30, 60, 120)


def _input_data(interval: object = "30") -> dict[str, object]:
    """Return a complete flow submission without real credentials."""
    return {
        CONF_HOST: "http://192.0.2.1",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "test-only-password",
        CONF_SCAN_INTERVAL: interval,
    }


def _mock_flow(kind: str) -> tuple[Any, SimpleNamespace]:
    """Initialize the real flow with mocked Home Assistant dependencies."""
    entry = SimpleNamespace(entry_id="test-entry", data=_input_data(30))
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


async def _submit(
    flow: Any, kind: str, data: dict[str, Any] | None
) -> dict[str, Any]:
    """Submit data to the user or options step."""
    if kind == "user":
        return await flow.async_step_user(data)
    return await flow.async_step_init(data)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (10, "10"),
        ("10", "10"),
        (30, "30"),
        ("60", "60"),
        (120, "120"),
        ("120", "120"),
        (None, "30"),
        ("invalid", "30"),
        (0, "30"),
        (15, "30"),
        (True, "30"),
        (10.5, "30"),
    ],
)
def test_scan_interval_selector_default(stored: object, expected: str) -> None:
    """Use valid persisted settings and repair old invalid form defaults."""
    data = {CONF_SCAN_INTERVAL: stored}
    schema = vol.Schema(config_flow._get_schema(data))
    interval_key = next(
        key for key in schema.schema if key.schema == CONF_SCAN_INTERVAL
    )

    assert interval_key.default() == expected
    assert isinstance(schema.schema[interval_key], selector.SelectSelector)


@pytest.mark.parametrize("persisted", [10, "30", 60, "120"])
def test_form_serializes_to_home_assistant_json(persisted: int | str) -> None:
    """Serialize the scan interval form using Home Assistant's own HTTP path."""
    schema = vol.Schema(config_flow._get_schema({CONF_SCAN_INTERVAL: persisted}))
    view = _BaseFlowManagerView(MagicMock())

    result = view._prepare_result_json(
        {"type": FlowResultType.FORM, "data_schema": schema}
    )

    assert json.dumps(result)
    assert any(field["name"] == CONF_SCAN_INTERVAL for field in result["data_schema"])


@pytest.mark.parametrize("interval", SCANS)
def test_selector_accepts_string_choices(interval: int) -> None:
    """Accept frontend select strings without coercing them during display."""
    schema = vol.Schema(config_flow._get_schema({}))
    submitted = schema(_input_data(str(interval)))

    assert submitted[CONF_SCAN_INTERVAL] == str(interval)


@pytest.mark.parametrize("interval", SCANS)
@pytest.mark.parametrize("as_string", [False, True])
def test_normalize_valid_scan_interval(interval: int, as_string: bool) -> None:
    """Store valid intervals as integers, regardless of submitted representation."""
    data = {CONF_SCAN_INTERVAL: str(interval) if as_string else interval}

    assert config_flow._normalize_scan_interval(data)
    assert data[CONF_SCAN_INTERVAL] == interval
    assert isinstance(data[CONF_SCAN_INTERVAL], int)


@pytest.mark.parametrize(
    "invalid", ["bad", "15", 15, 0, -1, 121, None, True, 10.5]
)
def test_reject_invalid_scan_interval_without_mutating(invalid: object) -> None:
    """Reject unsupported values and leave caller-owned data unchanged."""
    data = {CONF_SCAN_INTERVAL: invalid}

    assert not config_flow._normalize_scan_interval(data)
    assert data[CONF_SCAN_INTERVAL] == invalid


def test_missing_scan_interval_is_kept_optional() -> None:
    """Retain the default behavior for an absent legacy config field."""
    data: dict[str, object] = {}

    assert config_flow._get_scan_interval(data) == "30"
    assert config_flow._normalize_scan_interval(data)
    assert data == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user", "options"])
@pytest.mark.parametrize("interval", SCANS)
async def test_flow_saves_integer_scan_interval(kind: str, interval: int) -> None:
    """Persist a supported interval without changing other settings."""
    flow, _entry = _mock_flow(kind)
    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ) as credentials:
        result = await _submit(flow, kind, _input_data(str(interval)))

    assert result["type"] == "create_entry"
    credentials.assert_awaited_once()
    if kind == "user":
        saved = flow.async_create_entry.call_args.kwargs["data"]
    else:
        saved = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_SCAN_INTERVAL] == interval
    assert isinstance(saved[CONF_SCAN_INTERVAL], int)
    assert saved[CONF_HOST] == "http://192.0.2.1"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["user", "options"])
@pytest.mark.parametrize("invalid", ["not-a-number", "15", 0, True, None])
async def test_flow_rejects_invalid_scan_interval_without_api_call(
    kind: str, invalid: object
) -> None:
    """Reject invalid values before network access or config entry mutation."""
    flow, entry = _mock_flow(kind)
    with patch.object(config_flow, "_async_test_credentials", AsyncMock()) as check:
        result = await _submit(flow, kind, _input_data(invalid))

    assert result["type"] == "form"
    assert result["errors"] == {CONF_SCAN_INTERVAL: "invalid_scan_interval"}
    check.assert_not_awaited()
    flow.async_create_entry.assert_not_called()
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert entry.data[CONF_SCAN_INTERVAL] == 30
