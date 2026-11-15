"""Test independently scheduled and manually requested Deco inventory polls."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.tplink_deco import _get_device_list_interval
from custom_components.tplink_deco.button import DecoRefreshStatusButton
from custom_components.tplink_deco.button import async_setup_entry
from custom_components.tplink_deco.const import CONF_DEVICE_LIST_INTERVAL
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.exceptions import TransientConnectionException

MASTER = "02:00:00:00:10:01"
SATELLITE = "02:00:00:00:10:02"


def _node(mac: str, master: bool = False) -> dict[str, str]:
    """Return anonymous valid node data."""
    return {
        "mac": mac,
        "role": "master" if master else "slave",
        "group_status": "connected",
        "inet_status": "online",
    }


def _coordinator(interval: int) -> TplinkDecoUpdateCoordinator:
    """Create a real coordinator with no live network access."""
    api = MagicMock()
    api.async_list_devices = AsyncMock(return_value=[_node(MASTER, True)])
    api.async_get_performance = AsyncMock(
        return_value={"result": {"cpu_usage": "0.2", "mem_usage": "0.4"}}
    )
    return TplinkDecoUpdateCoordinator(
        hass=MagicMock(),
        api=api,
        config_entry=MagicMock(entry_id="mesh-one"),
        update_interval=timedelta(seconds=30),
        device_list_interval_seconds=interval,
    )


@pytest.mark.asyncio
async def test_startup_only_retains_master_and_keeps_performance() -> None:
    """Perform first device_list only once; continue performance polling."""
    coordinator = _coordinator(0)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        first = await coordinator._async_update_data()
        second = await coordinator._async_update_data()
    assert first is second
    assert second.master_deco is first.decos[MASTER]
    assert second.master_deco.cpu_usage_raw == 20.0
    assert second.master_deco.mem_usage_raw == 40.0
    assert coordinator.api.async_list_devices.await_count == 1
    assert coordinator.api.async_get_performance.await_count == 2


@pytest.mark.asyncio
async def test_interval_per_entry_and_cached_node_identity() -> None:
    """Two meshes use independent status cadence but both refresh performance."""
    fast, slow = _coordinator(10), _coordinator(300)
    with patch("custom_components.tplink_deco.coordinator.monotonic", return_value=100):
        with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
            await fast._async_update_data()
            await slow._async_update_data()
    with patch("custom_components.tplink_deco.coordinator.monotonic", return_value=111):
        await fast._async_update_data()
        await slow._async_update_data()
    assert fast.api.async_list_devices.await_count == 2
    assert slow.api.async_list_devices.await_count == 1
    assert fast.api.async_get_performance.await_count == 2
    assert slow.api.async_get_performance.await_count == 2


@pytest.mark.asyncio
async def test_forced_refresh_bypasses_disabled_interval_and_pause() -> None:
    """A manual refresh discovers new nodes and retains master identity."""
    coordinator = _coordinator(0)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()
    old_master = coordinator.data.master_deco
    coordinator.paused = True
    coordinator.api.async_list_devices.return_value = [
        _node(MASTER, True),
        _node(SATELLITE),
    ]
    coordinator.async_refresh = AsyncMock(side_effect=coordinator._async_update_data)
    # A directly mocked refresh does not update the real HA success flag.
    coordinator.last_update_success = True
    with patch(
        "custom_components.tplink_deco.coordinator.async_dispatcher_send"
    ) as signal:
        await coordinator.async_request_device_refresh()
    assert coordinator.api.async_list_devices.await_count == 2
    assert coordinator.data.master_deco is old_master
    assert SATELLITE in coordinator.data.decos
    signal.assert_called_once()
    assert coordinator._force_device_list_refresh is False
    await coordinator._async_update_data()
    assert coordinator.api.async_list_devices.await_count == 2


@pytest.mark.asyncio
async def test_failed_manual_refresh_preserves_cache_and_pause() -> None:
    """Sanitize timeouts without unpausing or modifying cached mesh data."""
    coordinator = _coordinator(0)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()
    old_data = coordinator.data
    coordinator.paused = True
    coordinator.api.async_list_devices.side_effect = TimeoutError("private token")
    coordinator.async_refresh = AsyncMock(side_effect=coordinator._async_update_data)
    with pytest.raises(HomeAssistantError, match="Unable to refresh") as caught:
        await coordinator.async_request_device_refresh()

    assert "private token" not in str(caught.value)
    assert coordinator.data is old_data
    assert coordinator.paused is True
    assert coordinator._force_device_list_refresh is False
    assert coordinator.health.last_error == "TimeoutError"
    assert "private token" not in repr(coordinator.health)

    # A failed press must not make paused polling perform another API call.
    await coordinator._async_update_data()
    assert coordinator.api.async_list_devices.await_count == 2

    coordinator.api.async_list_devices.side_effect = None
    coordinator.last_update_success = True
    await coordinator.async_request_device_refresh()
    assert coordinator.api.async_list_devices.await_count == 3
    assert coordinator.data.master_deco is old_data.master_deco


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        (None, 30),
        (0, 0),
        ("0", 0),
        ("300", 300),
        (300, 300),
        (5, 30),
        (-1, 30),
        (True, 30),
        ("invalid", 30),
    ],
)
def test_legacy_config_defaults(saved: object, expected: int) -> None:
    """Retain old scan cadence unless a valid new option was saved."""
    values = {} if saved is None else {CONF_DEVICE_LIST_INTERVAL: saved}
    assert _get_device_list_interval(values, timedelta(seconds=30)) == expected


@pytest.mark.asyncio
async def test_manual_button_is_entry_scoped_and_linked_to_master() -> None:
    """Expose a single button with a stable entry ID and master association."""
    coordinator = _coordinator(0)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()
    coordinator.async_request_device_refresh = AsyncMock()
    hass = MagicMock()
    hass.data = {DOMAIN: {"mesh-one": {COORDINATOR_DECOS_KEY: coordinator}}}
    add = MagicMock()
    await async_setup_entry(hass, SimpleNamespace(entry_id="mesh-one"), add)
    button = add.call_args.args[0][0]
    assert isinstance(button, DecoRefreshStatusButton)
    assert button.unique_id == "mesh-one_refresh_deco_status"
    assert button.device_info["identifiers"] == {(DOMAIN, MASTER)}
    await button.async_press()
    coordinator.async_request_device_refresh.assert_awaited_once_with()


def test_button_without_master_has_no_device_link() -> None:
    """Avoid inventing a master identity before the first successful poll."""
    assert DecoRefreshStatusButton(_coordinator(0)).device_info is None


@pytest.mark.asyncio
async def test_manual_refresh_reports_a_failed_home_assistant_poll() -> None:
    """Report a failed coordinator refresh instead of false button success."""
    coordinator = _coordinator(0)
    coordinator.last_update_success = False
    coordinator.async_refresh = AsyncMock(return_value=None)

    with pytest.raises(HomeAssistantError, match="Unable to refresh Deco status"):
        await coordinator.async_request_device_refresh()

    coordinator.async_refresh.assert_awaited_once_with()
    assert coordinator._force_device_list_refresh is False



@pytest.mark.asyncio
async def test_manual_refresh_sanitizes_authentication_failure() -> None:
    """Preserve Home Assistant's auth signal without leaking upstream details."""
    coordinator = _coordinator(0)
    coordinator.async_refresh = AsyncMock(
        side_effect=ConfigEntryAuthFailed("private-session-token")
    )

    with pytest.raises(
        ConfigEntryAuthFailed, match="Deco authentication failed"
    ) as caught:
        await coordinator.async_request_device_refresh()

    assert "private-session-token" not in str(caught.value)
    assert coordinator._force_device_list_refresh is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_response",
    [
        None,
        {"devices": []},
        [_node(MASTER, True), {"role": "slave"}],
        [_node(MASTER, True), _node(MASTER, True)],
        [{"mac": MASTER, "signal_level": None}],
        ["private_router_response"],
    ],
)
async def test_invalid_device_list_preserves_cached_state(
    invalid_response: object,
) -> None:
    """Reject malformed or duplicate IDs before modifying known Deco objects."""
    coordinator = _coordinator(10)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()

    old_data = coordinator.data
    old_master = old_data.master_deco
    old_master.name = "Previously saved Deco"
    old_name = old_master.name
    old_timestamp = coordinator._last_device_list_update
    coordinator.api.async_list_devices.return_value = invalid_response
    coordinator._force_device_list_refresh = True
    prior_calls = coordinator.api.async_get_performance.await_count
    with pytest.raises(ValueError, match="Deco inventory"):
        await coordinator._async_update_data()

    assert coordinator.data is old_data
    assert old_master.name == old_name
    assert coordinator._last_device_list_update == old_timestamp
    assert coordinator._force_device_list_refresh is True
    assert coordinator.api.async_get_performance.await_count == prior_calls
    assert coordinator.health.last_error == "ValueError"
    assert coordinator.health.consecutive_failures == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "optional_error",
    [
        TimeoutException("private-session-token"),
        TimeoutError("private-session-token"),
        TransientConnectionException("private-session-token"),
    ],
)
async def test_optional_performance_timeout_keeps_valid_device_discovery(
    optional_error: Exception,
) -> None:
    """Keep the mesh and prior performance when only the optional API fails."""
    coordinator = _coordinator(10)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()

    old_master = coordinator.data.master_deco
    coordinator.api.async_list_devices.return_value = [
        _node(MASTER, True),
        _node(SATELLITE),
    ]
    coordinator.api.async_get_performance.side_effect = optional_error
    coordinator._force_device_list_refresh = True

    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()

    assert coordinator.data.master_deco is old_master
    assert SATELLITE in coordinator.data.decos
    assert old_master.cpu_usage_raw == 20.0
    assert old_master.mem_usage_raw == 40.0
    assert coordinator.health.consecutive_failures == 0
    assert coordinator._force_device_list_refresh is False


@pytest.mark.asyncio
async def test_performance_authentication_failure_is_not_suppressed() -> None:
    """A real auth error must remain a failed refresh, not a cached success."""
    coordinator = _coordinator(10)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()

    coordinator.api.async_get_performance.side_effect = ConfigEntryAuthFailed(
        "private-session-token"
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    assert coordinator.health.last_error == "ConfigEntryAuthFailed"
    assert coordinator.health.consecutive_failures == 1


@pytest.mark.asyncio
async def test_unexpected_performance_payload_preserves_known_values() -> None:
    """A malformed optional result must not clear the previous CPU sample."""
    coordinator = _coordinator(0)
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator._async_update_data()

    old_master = coordinator.data.master_deco
    coordinator.api.async_get_performance.return_value = {"result": ["invalid"]}
    await coordinator._async_update_data()

    assert coordinator.data.master_deco is old_master
    assert old_master.cpu_usage_raw == 20.0
    assert old_master.mem_usage_raw == 40.0
    assert coordinator.health.consecutive_failures == 0
