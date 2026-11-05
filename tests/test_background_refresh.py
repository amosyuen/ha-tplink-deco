"""Tests for initial coordinator background refreshes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco import async_setup_entry
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import COORDINATOR_MOBILE_KEY
from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY


@pytest.mark.asyncio
async def test_initial_optional_refreshes_remain_background_tasks():
    """Ensure initial refreshes do not create foreground debouncer tasks."""
    deco_coordinator = MagicMock()
    clients_coordinator = MagicMock()
    wireless_coordinator = MagicMock()
    mobile_coordinator = MagicMock()
    clients_coordinator.async_refresh = AsyncMock()
    wireless_coordinator.async_refresh = AsyncMock()
    mobile_coordinator.async_refresh = AsyncMock()
    clients_coordinator.async_request_refresh = AsyncMock()
    wireless_coordinator.async_request_refresh = AsyncMock()
    mobile_coordinator.async_request_refresh = AsyncMock()
    coordinator_data = {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: clients_coordinator,
        COORDINATOR_WIRELESS_KEY: wireless_coordinator,
        COORDINATOR_MOBILE_KEY: mobile_coordinator,
    }

    scheduled_names = []

    def capture_background_task(_hass, target, name):
        scheduled_names.append(name)
        target.close()

    config_entry = MagicMock()
    config_entry.entry_id = "entry"
    config_entry.async_create_background_task.side_effect = capture_background_task
    hass = SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
        services=SimpleNamespace(async_register=MagicMock()),
    )

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new=AsyncMock(return_value=coordinator_data),
    ):
        assert await async_setup_entry(hass, config_entry) is True

    clients_coordinator.async_refresh.assert_called_once_with()
    wireless_coordinator.async_refresh.assert_called_once_with()
    mobile_coordinator.async_refresh.assert_called_once_with()
    clients_coordinator.async_request_refresh.assert_not_called()
    wireless_coordinator.async_request_refresh.assert_not_called()
    mobile_coordinator.async_request_refresh.assert_not_called()
    assert scheduled_names == [
        "tplink_deco initial client refresh",
        "tplink_deco initial wireless refresh",
        "tplink_deco initial mobile data refresh",
    ]
