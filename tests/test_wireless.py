"""Regression tests for optional, privacy-safe TP-Link Deco WiFi status."""

import asyncio
import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.binary_sensor import TplinkDecoWirelessBinarySensor
from custom_components.tplink_deco.binary_sensor import async_setup_entry
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.exceptions import UnexpectedApiException
from custom_components.tplink_deco.wireless import TplinkDecoWirelessUpdateCoordinator
from custom_components.tplink_deco.wireless import WIRELESS_NETWORKS
from custom_components.tplink_deco.wireless import parse_wireless_states

MASTER_MAC = "02:00:00:00:62:01"
SECRET = "PRIVATE_SSID_PASSWORD_AND_SESSION"


def _coordinator(*responses: object) -> TplinkDecoWirelessUpdateCoordinator:
    """Create an isolated coordinator with no router or Home Assistant I/O."""
    coordinator = object.__new__(TplinkDecoWirelessUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_get_wireless = AsyncMock(side_effect=responses)
    coordinator._deco_coordinator = MagicMock(paused=False)
    coordinator.data = {}
    coordinator._next_retry = 0.0
    coordinator._consecutive_failures = 0
    return coordinator


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("on", True),
        ("ENABLED", True),
        ("off", False),
        ("0", False),
        ("weird", None),
        (None, None),
        (2, None),
        ([], None),
    ],
)
def test_parse_wireless_flags_omits_unrecognized_values(
    flag: object, expected: bool | None
) -> None:
    """Unknown/malformed firmware flags must not be displayed as off."""
    result = parse_wireless_states({"band2_4": {"guest": {"enable": flag}}})
    assert result == ({"guest": expected} if expected is not None else {})


def test_wireless_parser_handles_bands_and_discards_private_data() -> None:
    """Only known network status leaves the parser, never sensitive fields."""
    response = {
        "band2_4": {
            "host": {"enable": "on", "ssid": SECRET, "password": SECRET},
            "guest": {"enable": "off", "psk": SECRET},
        },
        "band5_1": {"guest": {"enable": True}},
        "iot": {"host": {"enable": False, "ssid": SECRET}},
        "unknown": {"ssid": SECRET},
    }
    parsed = parse_wireless_states(response)
    assert parsed == {"main": True, "guest": True, "iot": False}
    assert SECRET not in repr(parsed)
    assert parse_wireless_states({"band2_4": {"host": {"ssid": SECRET}}}) == {}
    assert parse_wireless_states([response]) == {}


def test_main_wifi_is_disabled_by_default() -> None:
    """Main WiFi is normally always on and should be opt-in."""
    main = next(network for network in WIRELESS_NETWORKS if network.key == "main")
    assert main.entity_registry_enabled_default is False


@pytest.mark.asyncio
async def test_wireless_errors_are_sanitized_and_backoff_is_bounded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retry once then defer, without exposing raw firmware exceptions."""
    coordinator = _coordinator(
        OSError(SECRET),
        TimeoutError(SECRET),
        {"band2_4": {"guest": {"enable": "1"}}},
    )
    caplog.set_level(logging.DEBUG)
    with patch(
        "custom_components.tplink_deco.wireless.monotonic",
        side_effect=[100.0, 110.0, 120.0, 411.0],
    ):
        with pytest.raises(UpdateFailed, match="Unable to read optional wireless"):
            await coordinator._async_update_data()
        assert coordinator._next_retry == 0.0
        with pytest.raises(UpdateFailed, match="Unable to read optional wireless"):
            await coordinator._async_update_data()
        assert coordinator._next_retry == 410.0
        with pytest.raises(UpdateFailed, match="retry is deferred"):
            await coordinator._async_update_data()
        assert await coordinator._async_update_data() == {"guest": True}
    assert coordinator._next_retry == 0.0
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_wireless_pause_uses_cache_and_cancel_propagates() -> None:
    """Do not poll while paused or consume task cancellation."""
    coordinator = _coordinator()
    coordinator.data = {"main": False}
    coordinator._deco_coordinator.paused = True
    assert await coordinator._async_update_data() == {"main": False}
    coordinator.api.async_get_wireless.assert_not_awaited()
    coordinator._deco_coordinator.paused = False
    coordinator.api.async_get_wireless.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_api_uses_read_only_wireless_form_and_redacts_errors() -> None:
    """Read the fixed wlan endpoint without surfacing password-bearing data."""
    api = TplinkDecoApi(
        session=MagicMock(),
        host="http://192.0.2.1",
        username="test",
        password="test",
        verify_ssl=True,
    )
    api.async_login_if_needed = AsyncMock()
    api._stok = "test-stok"
    api._encode_payload = MagicMock(return_value="encrypted")
    api._async_post = AsyncMock(return_value={"data": "ciphertext"})
    api._decrypt_data = MagicMock(
        return_value={"result": {"band2_4": {"host": {"enable": True}}}}
    )
    assert await api.async_get_wireless() == {"band2_4": {"host": {"enable": True}}}
    api._encode_payload.assert_called_once_with({"operation": "read"})
    api._async_post.assert_awaited_once_with(
        "Get wireless status",
        "http://192.0.2.1/cgi-bin/luci/;stok=test-stok/admin/wireless",
        params={"form": "wlan"},
        data="encrypted",
    )
    api._decrypt_data.return_value = {
        "error_code": 123,
        "result": {"password": SECRET},
    }
    with pytest.raises(UnexpectedApiException, match="request was rejected") as error:
        await api.async_get_wireless()
    assert SECRET not in str(error.value)


@pytest.mark.asyncio
async def test_api_rejects_malformed_wireless_payload() -> None:
    """Malformed firmware results must not become healthy empty reads."""
    api = TplinkDecoApi(MagicMock(), "http://192.0.2.1", "test", "test", True)
    api.async_login_if_needed = AsyncMock()
    api._encode_payload = MagicMock(return_value="encrypted")
    api._async_post = AsyncMock(return_value={"data": "ciphertext"})
    api._decrypt_data = MagicMock(return_value={"result": [SECRET]})
    with pytest.raises(ValueError, match="Wireless status response is malformed"):
        await api.async_get_wireless()


@pytest.mark.asyncio
async def test_wireless_networks_are_discovered_once_and_linked_to_master() -> None:
    """Preserve preexisting binary sensors while discovering WiFi networks."""
    master = TpLinkDeco(MASTER_MAC)
    master.name = "Test Deco"
    deco = MagicMock()
    deco.data = TpLinkDecoData(master, {MASTER_MAC: master})
    wireless = MagicMock()
    wireless.data = {"guest": True}
    wireless.last_update_success = True
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "mesh-one": {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_WIRELESS_KEY: wireless,
            }
        }
    }
    entry = MagicMock()
    entry.entry_id = "mesh-one"
    batches: list[list[object]] = []
    with patch(
        "custom_components.tplink_deco.binary_sensor.async_dispatcher_connect",
        return_value=MagicMock(),
    ):
        await async_setup_entry(hass, entry, batches.append)
    initial = [entity for batch in batches for entity in batch]
    entities = [
        entity
        for entity in initial
        if isinstance(entity, TplinkDecoWirelessBinarySensor)
    ]
    assert len(entities) == 1
    guest = entities[0]
    assert guest.unique_id == f"{MASTER_MAC}_wifi_guest"
    assert guest.is_on is True
    assert guest.available is True
    assert guest.device_info["identifiers"] == {(DOMAIN, MASTER_MAC)}
    listener = wireless.async_add_listener.call_args.args[0]
    listener()
    assert sum(len(batch) for batch in batches) == len(initial)
    wireless.data["iot"] = False
    listener()
    updated = [entity for batch in batches for entity in batch]
    iot = next(
        entity
        for entity in updated
        if isinstance(entity, TplinkDecoWirelessBinarySensor)
        and entity.entity_description.key == "iot"
    )
    assert iot.is_on is False
    wireless.data = {}
    assert guest.available is False
    assert iot.available is False


@pytest.mark.asyncio
async def test_two_wireless_coordinators_keep_independent_state() -> None:
    """Multiple configuration entries never share WLAN retry state."""
    first = _coordinator({"band2_4": {"guest": {"enable": True}}})
    second = _coordinator({"iot": {"host": {"enable": False}}})
    assert await first._async_update_data() == {"guest": True}
    assert await second._async_update_data() == {"iot": False}
    first._next_retry = 500.0
    assert second._next_retry == 0.0
