"""Regressions for awaited Home Assistant Deco platform setup."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco import async_setup_entry
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import PLATFORMS


def _setup_mocks(entry_id: str) -> tuple[MagicMock, MagicMock]:
    """Create mocks for a config entry and its Home Assistant host."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    return hass, config_entry


@pytest.mark.asyncio
async def test_entry_setup_awaits_platforms_before_registering_services() -> None:
    """Do not finish setup while forwarded platforms are still initializing."""
    hass, config_entry = _setup_mocks("delayed_platforms")
    forward_started = asyncio.Event()
    forward_released = asyncio.Event()

    async def _forward_platforms(entry: MagicMock, platforms: list[str]) -> None:
        """Hold forwarding until the test checks the setup boundary."""
        assert entry is config_entry
        assert platforms == PLATFORMS
        assert hass.data[DOMAIN][entry.entry_id][COORDINATOR_DECOS_KEY]
        forward_started.set()
        await forward_released.wait()

    forward = AsyncMock(side_effect=_forward_platforms)
    hass.config_entries.async_forward_entry_setups = forward

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new_callable=AsyncMock,
        return_value={COORDINATOR_DECOS_KEY: MagicMock()},
    ):
        setup_task = asyncio.create_task(async_setup_entry(hass, config_entry))
        try:
            await asyncio.wait_for(forward_started.wait(), timeout=5)
            assert not setup_task.done()
            hass.services.async_register.assert_not_called()
        finally:
            forward_released.set()

        assert await asyncio.wait_for(setup_task, timeout=5) is True

    forward.assert_awaited_once_with(config_entry, PLATFORMS)
    hass.async_create_task.assert_not_called()
    assert hass.services.async_register.call_count == 3
    config_entry.async_on_unload.assert_called_once()


@pytest.mark.asyncio
async def test_entry_setup_propagates_platform_forwarding_failure() -> None:
    """Abort setup without registering services if a platform setup fails."""
    hass, config_entry = _setup_mocks("failed_platforms")
    forward = AsyncMock(side_effect=RuntimeError("platform setup failed"))
    hass.config_entries.async_forward_entry_setups = forward

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new_callable=AsyncMock,
        return_value={COORDINATOR_DECOS_KEY: MagicMock()},
    ):
        with pytest.raises(RuntimeError, match="platform setup failed"):
            await async_setup_entry(hass, config_entry)

    forward.assert_awaited_once_with(config_entry, PLATFORMS)
    hass.async_create_task.assert_not_called()
    hass.services.async_register.assert_not_called()
    config_entry.async_on_unload.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_id", ["mesh_1", "mesh_2"])
async def test_entry_setup_forwards_platforms_once_per_config_entry(
    entry_id: str,
) -> None:
    """Keep distinct config entries using their existing platform contracts."""
    hass, config_entry = _setup_mocks(entry_id)

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new_callable=AsyncMock,
        return_value={COORDINATOR_DECOS_KEY: MagicMock()},
    ):
        assert await async_setup_entry(hass, config_entry) is True

    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        config_entry, PLATFORMS
    )
    hass.async_create_task.assert_not_called()
    assert entry_id in hass.data[DOMAIN]
