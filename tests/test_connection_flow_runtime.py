"""Runtime regressions for the TP-Link Deco config-flow compatibility fix."""

from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def config_flow() -> ModuleType:
    """Load real Home Assistant integration code when its runtime is available."""
    pytest.importorskip("homeassistant", reason="Runtime tests require Home Assistant")
    from custom_components.tplink_deco import config_flow as deco_config_flow

    return deco_config_flow


def test_config_flow_preserves_base_class_and_entry_version(
    config_flow: ModuleType,
) -> None:
    """Keep the original config flow and migration version without old metadata."""
    from homeassistant import config_entries

    assert issubclass(config_flow.TplinkDecoFlowHandler, config_entries.ConfigFlow)
    assert config_flow.TplinkDecoFlowHandler.VERSION == 6
    assert "CONNECTION_CLASS" not in vars(config_flow.TplinkDecoFlowHandler)


def test_options_flow_factory_still_returns_handler(config_flow: ModuleType) -> None:
    """Retain the existing options flow after the compatibility change."""
    existing_data = {"host": "http://192.0.2.1", "scan_interval": 30}
    config_entry = SimpleNamespace(data=existing_data)

    options_flow = config_flow.TplinkDecoFlowHandler.async_get_options_flow(
        config_entry
    )

    assert isinstance(options_flow, config_flow.TplinkDecoOptionsFlowHandler)
    assert options_flow.data == existing_data
    assert options_flow.data is not existing_data


@pytest.mark.asyncio
async def test_config_flow_still_renders_initial_form(config_flow: ModuleType) -> None:
    """Render the setup form without relying on deprecated connection classes."""
    flow = config_flow.TplinkDecoFlowHandler()

    with patch.object(
        config_flow.TplinkDecoFlowHandler,
        "async_show_form",
        return_value={"type": "form", "step_id": "user"},
    ) as show_form:
        result = await flow.async_step_user()

    assert result == {"type": "form", "step_id": "user"}
    show_form.assert_called_once()
    assert show_form.call_args.kwargs["step_id"] == "user"
    assert not show_form.call_args.kwargs["errors"]
