"""Regressions for the non-blocking initial Deco client-list refresh."""

from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco import async_setup_entry
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import PLATFORMS


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_fails", [False, True])
async def test_initial_client_refresh_is_entry_owned_and_nonblocking(
    refresh_fails: bool,
) -> None:
    """Finish entry setup before the client API request completes or fails."""
    events: list[str] = []
    background_coroutines: list[Coroutine[Any, Any, None]] = []
    hass = MagicMock()
    hass.data = {}

    async def _forward_platforms(*args: object) -> None:
        """Record that platforms finish loading before the client refresh."""
        events.append("platforms_forwarded")

    hass.config_entries.async_forward_entry_setups = AsyncMock(
        side_effect=_forward_platforms
    )
    config_entry = MagicMock()
    config_entry.entry_id = "mesh-one"

    def _register_background(
        target_hass: MagicMock,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> None:
        """Capture a config-entry background task without starting it."""
        assert target_hass is hass
        assert name == "tplink_deco initial client refresh"
        assert events == ["platforms_forwarded"]
        events.append("background_registered")
        background_coroutines.append(coroutine)

    config_entry.async_create_background_task.side_effect = _register_background

    async def _refresh_clients() -> None:
        """Simulate a client API request which executes only when scheduled."""
        events.append("client_refresh_started")
        if refresh_fails:
            raise RuntimeError("test client request failed")

    deco_coordinator = MagicMock()
    client_coordinator = MagicMock()
    client_coordinator.async_refresh = AsyncMock(side_effect=_refresh_clients)
    client_coordinator.async_request_refresh = AsyncMock()
    client_coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator_data = {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: client_coordinator,
    }

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new=AsyncMock(return_value=coordinator_data),
    ) as create_config_data:
        assert await async_setup_entry(hass, config_entry) is True

    create_config_data.assert_awaited_once_with(hass, config_entry)
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        config_entry, PLATFORMS
    )
    config_entry.async_create_background_task.assert_called_once()
    client_coordinator.async_refresh.assert_called_once_with()
    client_coordinator.async_refresh.assert_not_awaited()
    client_coordinator.async_request_refresh.assert_not_awaited()
    client_coordinator.async_config_entry_first_refresh.assert_not_awaited()
    assert events == ["platforms_forwarded", "background_registered"]
    assert len(background_coroutines) == 1
    assert hass.data[DOMAIN][config_entry.entry_id] is coordinator_data

    if refresh_fails:
        with pytest.raises(RuntimeError, match="test client request failed"):
            await background_coroutines[0]
    else:
        await background_coroutines[0]

    assert events[-1] == "client_refresh_started"
    client_coordinator.async_refresh.assert_awaited_once()
    hass.services.async_register.assert_called()


@pytest.mark.asyncio
async def test_failed_platform_forwarding_does_not_schedule_client_refresh() -> None:
    """Propagate platform setup failure before any client task is scheduled."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock(
        side_effect=RuntimeError("test forwarding failed")
    )
    config_entry = MagicMock()
    config_entry.entry_id = "mesh-one"
    deco_coordinator = MagicMock()
    client_coordinator = MagicMock()
    client_coordinator.async_refresh = AsyncMock()
    coordinator_data = {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: client_coordinator,
    }

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new=AsyncMock(return_value=coordinator_data),
    ):
        with pytest.raises(RuntimeError, match="test forwarding failed"):
            await async_setup_entry(hass, config_entry)

    client_coordinator.async_refresh.assert_not_called()
    config_entry.async_create_background_task.assert_not_called()
    hass.services.async_register.assert_not_called()
