"""Tests for wireless network status support."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import LoginInvalidException
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.wireless import TplinkDecoWirelessUpdateCoordinator
from custom_components.tplink_deco.wireless import WIRELESS_NETWORKS
from custom_components.tplink_deco.wireless import parse_wireless_ssids
from custom_components.tplink_deco.wireless import parse_wireless_states


def _coordinator(*responses) -> TplinkDecoWirelessUpdateCoordinator:
    coordinator = object.__new__(TplinkDecoWirelessUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_get_wireless = AsyncMock(side_effect=responses)
    coordinator._deco_coordinator = MagicMock(paused=False)
    coordinator.data = {}
    coordinator.ssids = {}
    coordinator._next_retry = 0.0
    coordinator._consecutive_failures = 0
    return coordinator


def test_parse_wireless_states_supports_multiple_firmware_values():
    config = {
        "band2_4": {
            "host": {"enable": "on", "ssid": "private"},
            "guest": {"enable": 0, "password": "private"},
        },
        "band5_1": {
            "host": {"enable": True},
            "guest": {"enable": "enabled"},
        },
        "iot": {"host": {"enable": "off", "psk": "private"}},
    }

    assert parse_wireless_states(config) == {
        "main": True,
        "guest": True,
        "iot": False,
    }


def test_parse_wireless_states_omits_networks_not_exposed_by_firmware():
    config = {"band2_4": {"host": {"enable": "1"}}}

    assert parse_wireless_states(config) == {"main": True}


def test_parse_wireless_states_returns_no_sensitive_values():
    config = {
        "band2_4": {
            "guest": {
                "enable": True,
                "ssid": ["private-network"],
                "password": {"value": "private-password"},
            }
        }
    }

    states = parse_wireless_states(config)

    assert states == {"guest": True}
    assert "private" not in repr(states)


def test_parse_wireless_ssids_decodes_names():
    config = {
        "band2_4": {
            "host": {"enable": True, "ssid": "SG9tZQ==", "password": "secret"},
            "guest": {"enable": True, "ssid": "Ospiti"},
        },
        "band5_1": {"host": {"enable": True, "ssid": "SG9tZQ=="}},
        "iot": {"host": {"enable": False, "psk": "secret"}},
    }

    ssids = parse_wireless_ssids(config)

    assert ssids == {"main": "Home", "guest": "Ospiti"}
    assert "secret" not in repr(ssids)


def test_parse_wireless_ssids_ignores_non_string_values():
    config = {"band2_4": {"guest": {"enable": True, "ssid": ["private-network"]}}}

    assert parse_wireless_ssids(config) == {}


def test_main_wifi_sensor_is_disabled_by_default():
    main_network = next(
        network for network in WIRELESS_NETWORKS if network.key == "main"
    )

    assert main_network.entity_registry_enabled_default is False


@pytest.mark.asyncio
async def test_wireless_coordinator_retries_next_poll_after_single_failure():
    coordinator = _coordinator(
        OSError("temporary failure"),
        {"band2_4": {"guest": {"enable": "on", "ssid": "Ospiti"}}},
    )

    with patch(
        "custom_components.tplink_deco.wireless.monotonic",
        side_effect=[100.0, 110.0],
    ):
        with pytest.raises(UpdateFailed, match="Unable to read wireless status"):
            await coordinator._async_update_data()

        assert coordinator._next_retry == 0.0
        assert await coordinator._async_update_data() == {"guest": True}
        assert coordinator.ssids == {"guest": "Ospiti"}
        assert coordinator._consecutive_failures == 0


@pytest.mark.asyncio
async def test_wireless_coordinator_defers_after_repeated_failures():
    coordinator = _coordinator(
        OSError("temporary failure"),
        OSError("temporary failure"),
        {"band2_4": {"guest": {"enable": "on"}}},
    )

    with patch(
        "custom_components.tplink_deco.wireless.monotonic",
        side_effect=[100.0, 110.0, 200.0, 411.0],
    ):
        with pytest.raises(UpdateFailed, match="Unable to read wireless status"):
            await coordinator._async_update_data()

        with pytest.raises(UpdateFailed, match="Unable to read wireless status"):
            await coordinator._async_update_data()

        with pytest.raises(UpdateFailed, match="retry is deferred"):
            await coordinator._async_update_data()

        assert await coordinator._async_update_data() == {"guest": True}
        assert coordinator._next_retry == 0.0


def test_wireless_coordinator_reset_retry_clears_deferral():
    coordinator = _coordinator()
    coordinator._next_retry = 500.0
    coordinator._consecutive_failures = 3

    coordinator.reset_retry()

    assert coordinator._next_retry == 0.0
    assert coordinator._consecutive_failures == 0


@pytest.mark.asyncio
async def test_wireless_coordinator_reports_exception_type_for_empty_errors():
    coordinator = _coordinator(TimeoutError())

    with pytest.raises(
        UpdateFailed, match="Unable to read wireless status: TimeoutError$"
    ):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_wireless_coordinator_propagates_auth_failure():
    coordinator = _coordinator(LoginInvalidException(1))

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    assert coordinator._next_retry == 0.0


@pytest.mark.asyncio
async def test_wireless_coordinator_respects_polling_pause():
    coordinator = _coordinator({"band2_4": {"host": {"enable": "on"}}})
    coordinator._deco_coordinator.paused = True
    coordinator.data = {"main": False}

    assert await coordinator._async_update_data() == {"main": False}
    coordinator.api.async_get_wireless.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_get_wireless_uses_read_operation():
    api = TplinkDecoApi(
        session=MagicMock(),
        host="http://192.168.1.1",
        username="admin",
        password="password",
        verify_ssl=False,
    )
    api.async_login_if_needed = AsyncMock()
    api._encode_payload = MagicMock(return_value="payload")
    api._async_post = AsyncMock(return_value={"data": "encrypted"})
    api._decrypt_data = MagicMock(
        return_value={"error_code": 0, "result": {"band2_4": {}}}
    )

    result = await api.async_get_wireless("wlan")

    assert result == {"band2_4": {}}
    api._encode_payload.assert_called_once_with({"operation": "read"})
    api._async_post.assert_awaited_once_with(
        "Get Wireless wlan",
        "http://192.168.1.1/cgi-bin/luci/;stok=None/admin/wireless",
        params={"form": "wlan"},
        data="payload",
    )


@pytest.mark.asyncio
async def test_async_get_wireless_uses_configured_timeout_retries():
    api = TplinkDecoApi(
        session=MagicMock(),
        host="http://192.168.1.1",
        username="admin",
        password="password",
        verify_ssl=False,
        timeout_error_retries=1,
    )
    api._async_get_wireless = AsyncMock(
        side_effect=[TimeoutException("Get Wireless wlan"), {"band2_4": {}}]
    )

    assert await api.async_get_wireless("wlan") == {"band2_4": {}}
    assert api._async_get_wireless.await_count == 2
