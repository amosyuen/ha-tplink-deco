from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator


def _coordinator(interval: int) -> TplinkDecoUpdateCoordinator:
    coordinator = object.__new__(TplinkDecoUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_list_devices = AsyncMock(return_value=[])
    coordinator.api.async_get_performance = AsyncMock(return_value={})
    coordinator.data = TpLinkDecoData()
    coordinator.hass = MagicMock()
    coordinator.device_list_interval_seconds = interval
    coordinator._last_device_list_update = None
    coordinator._force_device_list_refresh = False
    return coordinator


@pytest.mark.asyncio
async def test_first_update_always_refreshes_device_list():
    coordinator = _coordinator(0)

    await coordinator._async_update_data_internal()

    coordinator.api.async_list_devices.assert_awaited_once()
    coordinator.api.async_get_performance.assert_awaited_once()
    assert coordinator._last_device_list_update is not None


@pytest.mark.asyncio
async def test_disabled_device_list_still_updates_performance():
    coordinator = _coordinator(0)
    coordinator._last_device_list_update = 100

    await coordinator._async_update_data_internal()

    coordinator.api.async_list_devices.assert_not_awaited()
    coordinator.api.async_get_performance.assert_awaited_once()


@pytest.mark.asyncio
async def test_forced_device_list_refresh_ignores_disabled_interval():
    coordinator = _coordinator(0)
    coordinator._last_device_list_update = 100
    coordinator._force_device_list_refresh = True

    await coordinator._async_update_data_internal()

    coordinator.api.async_list_devices.assert_awaited_once()
    assert coordinator._force_device_list_refresh is False


def test_device_list_refresh_uses_independent_interval():
    coordinator = _coordinator(300)
    coordinator._last_device_list_update = 100

    with patch("custom_components.tplink_deco.coordinator.monotonic", return_value=399):
        assert coordinator._device_list_refresh_due() is False

    with patch("custom_components.tplink_deco.coordinator.monotonic", return_value=400):
        assert coordinator._device_list_refresh_due() is True
