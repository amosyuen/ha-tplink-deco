"""Runtime regressions for the TP-Link Deco config-flow compatibility fix."""

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant import config_entries
import pytest

from custom_components.tplink_deco.config_flow import TplinkDecoFlowHandler
from custom_components.tplink_deco.config_flow import TplinkDecoOptionsFlowHandler


def test_config_flow_preserves_base_class_and_entry_version() -> None:
    """Keep the original config flow and migration version without old metadata."""
    assert issubclass(TplinkDecoFlowHandler, config_entries.ConfigFlow)
    assert TplinkDecoFlowHandler.VERSION == 6
    assert "CONNECTION_CLASS" not in vars(TplinkDecoFlowHandler)


def test_options_flow_factory_still_returns_handler() -> None:
    """Retain the existing options flow after the compatibility change."""
    existing_data = {"host": "http://192.0.2.1", "scan_interval": 30}
    config_entry = SimpleNamespace(data=existing_data)

    options_flow = TplinkDecoFlowHandler.async_get_options_flow(config_entry)

    assert isinstance(options_flow, TplinkDecoOptionsFlowHandler)
    assert options_flow.data == existing_data
    assert options_flow.data is not existing_data


@pytest.mark.asyncio
async def test_config_flow_still_renders_initial_form() -> None:
    """Render the setup form without relying on deprecated connection classes."""
    flow = TplinkDecoFlowHandler()

    with patch.object(
        TplinkDecoFlowHandler,
        "async_show_form",
        return_value={"type": "form", "step_id": "user"},
    ) as show_form:
        result = await flow.async_step_user()

    assert result == {"type": "form", "step_id": "user"}
    show_form.assert_called_once()
    assert show_form.call_args.kwargs["step_id"] == "user"
    assert not show_form.call_args.kwargs["errors"]
