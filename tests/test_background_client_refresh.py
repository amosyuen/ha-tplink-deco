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
from custom_components.tplink_deco.const import COORDINATOR_MOBILE_KEY
from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY
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


@pytest.mark.asyncio
async def test_all_initial_refreshes_are_deferred_until_after_platform_setup() -> None:
    """Port upstream optional-refresh parity without starting foreground tasks."""
    events: list[str] = []
    scheduled: list[tuple[str, Coroutine[Any, Any, None]]] = []
    hass = MagicMock()
    hass.data = {}

    async def _forward_platforms(*_args: object) -> None:
        """Record completion of platform forwarding."""
        events.append("platforms_forwarded")

    hass.config_entries.async_forward_entry_setups = AsyncMock(
        side_effect=_forward_platforms
    )
    config_entry = MagicMock()
    config_entry.entry_id = "all-coordinators"

    def _capture_task(
        target_hass: MagicMock,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> None:
        """Capture entry-owned tasks without awaiting or scheduling them."""
        assert target_hass is hass
        assert events and events[0] == "platforms_forwarded"
        scheduled.append((name, coroutine))
        events.append(name)

    config_entry.async_create_background_task.side_effect = _capture_task

    coordinators = {
        key: MagicMock()
        for key in (
            COORDINATOR_DECOS_KEY,
            COORDINATOR_CLIENTS_KEY,
            COORDINATOR_WIRELESS_KEY,
            COORDINATOR_MOBILE_KEY,
        )
    }
    for key in (
        COORDINATOR_CLIENTS_KEY,
        COORDINATOR_WIRELESS_KEY,
        COORDINATOR_MOBILE_KEY,
    ):
        coordinators[key].async_refresh = AsyncMock()
        coordinators[key].async_request_refresh = AsyncMock()

    try:
        with patch(
            "custom_components.tplink_deco.async_create_config_data",
            new=AsyncMock(return_value=coordinators),
        ):
            assert await async_setup_entry(hass, config_entry) is True

        expected_names = [
            "tplink_deco initial client refresh",
            "tplink_deco initial wireless refresh",
            "tplink_deco initial mobile data refresh",
        ]
        assert events == ["platforms_forwarded", *expected_names]
        assert [name for name, _coroutine in scheduled] == expected_names
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            config_entry, PLATFORMS
        )
        assert hass.data[DOMAIN][config_entry.entry_id] is coordinators
        assert config_entry.async_create_background_task.call_count == 3

        for key in (
            COORDINATOR_CLIENTS_KEY,
            COORDINATOR_WIRELESS_KEY,
            COORDINATOR_MOBILE_KEY,
        ):
            coordinator = coordinators[key]
            coordinator.async_refresh.assert_called_once_with()
            coordinator.async_refresh.assert_not_awaited()
            coordinator.async_request_refresh.assert_not_called()
    finally:
        for _name, coroutine in scheduled:
            coroutine.close()


@pytest.mark.asyncio
async def test_failed_platform_setup_does_not_start_any_optional_refresh() -> None:
    """Avoid scheduling client, WiFi or mobile tasks when forwarding fails."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock(
        side_effect=RuntimeError("synthetic platform setup failure")
    )
    config_entry = MagicMock()
    config_entry.entry_id = "all-coordinators"

    coordinators = {
        key: MagicMock()
        for key in (
            COORDINATOR_DECOS_KEY,
            COORDINATOR_CLIENTS_KEY,
            COORDINATOR_WIRELESS_KEY,
            COORDINATOR_MOBILE_KEY,
        )
    }
    for key in (
        COORDINATOR_CLIENTS_KEY,
        COORDINATOR_WIRELESS_KEY,
        COORDINATOR_MOBILE_KEY,
    ):
        coordinators[key].async_refresh = AsyncMock()

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new=AsyncMock(return_value=coordinators),
    ):
        with pytest.raises(RuntimeError, match="synthetic platform setup failure"):
            await async_setup_entry(hass, config_entry)

    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        config_entry, PLATFORMS
    )
    config_entry.async_create_background_task.assert_not_called()
    for key in (
        COORDINATOR_CLIENTS_KEY,
        COORDINATOR_WIRELESS_KEY,
        COORDINATOR_MOBILE_KEY,
    ):
        coordinators[key].async_refresh.assert_not_called()
        coordinators[key].async_request_refresh.assert_not_called()
