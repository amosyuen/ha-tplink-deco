"""Regressions for guarded IoT WiFi switching on a TP-Link Deco master."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.exceptions import UnexpectedApiException
from custom_components.tplink_deco.switch import DecoIotWifiSwitch
from custom_components.tplink_deco.switch import DecoPollingSwitch
from custom_components.tplink_deco.switch import async_setup_entry
from custom_components.tplink_deco.wireless import TplinkDecoWirelessUpdateCoordinator

MASTER_MAC = "02:00:00:00:01:99"
SECRET = "PRIVATE_SSID_PASSWORD_TOKEN"


def _api() -> TplinkDecoApi:
    """Build an authenticated but fully mocked Deco API."""
    api = TplinkDecoApi(
        MagicMock(), "https://192.0.2.1", "test-user", "test-password", True
    )
    api.async_login_if_needed = AsyncMock()
    api._stok = "synthetic-token"
    api._encode_payload = MagicMock(return_value="encrypted")
    api._async_post = AsyncMock(return_value={"data": "ciphertext"})
    api._decrypt_data = MagicMock(
        return_value={"error_code": 0, "result": {}}
    )
    return api


def _wireless() -> TplinkDecoWirelessUpdateCoordinator:
    """Construct a current, confirmed online master with mocked I/O."""
    master = TpLinkDeco(MASTER_MAC)
    master.name = "Synthetic Deco"
    master.online = True
    deco = MagicMock(paused=False)
    deco.data = TpLinkDecoData(master, {MASTER_MAC: master}, unique_master=True)
    deco.config_entry.entry_id = "mesh-one"

    wireless = object.__new__(TplinkDecoWirelessUpdateCoordinator)
    wireless.api = MagicMock()
    wireless.api.async_get_wireless = AsyncMock(
        return_value={"iot": {"host": {"enable": True, "ssid": SECRET}}}
    )
    wireless.api.async_set_iot_wireless = AsyncMock()
    wireless._deco_coordinator = deco
    wireless._observed_master_mac = MASTER_MAC
    wireless._master_generation = 0
    wireless._iot_state_identity = (MASTER_MAC, 0)
    wireless._iot_write_lock = asyncio.Lock()
    wireless.last_update_success = True
    wireless.data = {"iot": True}
    wireless.async_refresh = AsyncMock()
    wireless.async_add_listener = MagicMock(return_value=MagicMock())
    wireless.expose_ssids = False
    wireless.ssids = {}
    wireless._next_retry = 0.0
    wireless._consecutive_failures = 0
    wireless._ssid_master_mac = None
    wireless._ssid_master_generation = None
    return wireless


@pytest.mark.asyncio
async def test_api_sends_only_iot_enable_over_authenticated_wlan() -> None:
    """Ensure payload contains no password, name, guest or other fields."""
    api = _api()
    owner_check = MagicMock(return_value=True)

    await api.async_set_iot_wireless(False, owner_check)

    api._encode_payload.assert_called_once_with(
        {"operation": "write", "params": {"iot": {"host": {"enable": False}}}}
    )
    api._async_post.assert_awaited_once_with(
        "Set IoT WiFi",
        "https://192.0.2.1/cgi-bin/luci/;stok=synthetic-token/admin/wireless",
        params={"form": "wlan"},
        data="encrypted",
    )
    assert owner_check.call_count == 3


@pytest.mark.asyncio
async def test_api_rejects_nonboolean_or_missing_owner_without_io() -> None:
    """Do not issue router requests for invalid input or stale ownership."""
    api = _api()
    with pytest.raises(ValueError, match="boolean"):
        await api.async_set_iot_wireless(1, lambda: True)
    with pytest.raises(ValueError, match="ownership guard"):
        await api.async_set_iot_wireless(True, None)
    with pytest.raises(UnexpectedApiException, match="no longer current"):
        await api.async_set_iot_wireless(True, lambda: False)
    api.async_login_if_needed.assert_not_awaited()
    api._async_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_rechecks_owner_after_login() -> None:
    """Never POST after a master handover during the authentication await."""
    api = _api()
    owner = MagicMock(side_effect=[True, False])
    with pytest.raises(UnexpectedApiException, match="changed before"):
        await api.async_set_iot_wireless(True, owner)
    api._async_post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, payload",
    [
        ({}, {}),
        ({"data": "ciphertext"}, {"result": {}}),
        ({"data": "ciphertext"}, {"error_code": 3, "result": {}}),
        ({"data": "ciphertext"}, {"error_code": True, "result": {}}),
        ({"data": "ciphertext"}, {"error_code": 0, "result": []}),
    ],
)
async def test_api_requires_explicit_write_ack(
    response: dict[str, object], payload: dict[str, object]
) -> None:
    """Missing, rejected or malformed acknowledgement must not mean success."""
    api = _api()
    api._async_post.return_value = response
    api._decrypt_data.return_value = payload

    with pytest.raises(UnexpectedApiException, match="could not be confirmed"):
        await api.async_set_iot_wireless(True, lambda: True)
    api._async_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_never_retries_ambiguous_write_or_exposes_secret() -> None:
    """A transport timeout must not replay a write or preserve raw errors."""
    api = _api()
    api._async_post.side_effect = TimeoutError(SECRET)

    with pytest.raises(UnexpectedApiException) as error:
        await api.async_set_iot_wireless(True, lambda: True)
    api._async_post.assert_awaited_once()
    assert error.value.__context__ is None
    assert error.value.__cause__ is None
    assert SECRET not in str(error.value)


@pytest.mark.asyncio
async def test_api_preserves_task_cancellation() -> None:
    """Cancellation is not a generic WLAN write failure."""
    api = _api()
    api._async_post.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await api.async_set_iot_wireless(True, lambda: True)
    api._async_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_coordinator_checks_read_before_write_and_reconciles() -> None:
    """Require fresh supported firmware settings and observed readback."""
    wireless = _wireless()

    await wireless.async_set_iot_enabled(True, MASTER_MAC)

    wireless.api.async_get_wireless.assert_awaited_once()
    wireless.api.async_set_iot_wireless.assert_awaited_once()
    args = wireless.api.async_set_iot_wireless.call_args.args
    assert args[0] is True
    assert args[1]()
    wireless.async_refresh.assert_awaited_once()
    assert wireless.data == {"iot": True}


@pytest.mark.asyncio
async def test_coordinator_rejects_invalid_firmware_without_write() -> None:
    """Absent, unknown and malformed IoT enable flags are unsupported."""
    for response in [
        {},
        {"iot": {"host": {"enable": 99}}},
        {"iot": {"host": {"enable": None}}},
        {"iot": {"host": "malformed"}},
    ]:
        wireless = _wireless()
        wireless.api.async_get_wireless.return_value = response
        with pytest.raises(UpdateFailed, match="unsupported"):
            await wireless.async_set_iot_enabled(False, MASTER_MAC)
        wireless.api.async_set_iot_wireless.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_rejects_offline_stale_or_unowned_master() -> None:
    """A former/ambiguous/offline master is never a safe write target."""
    for mode in ("offline", "stale", "wrong-owner", "paused"):
        wireless = _wireless()
        if mode == "offline":
            wireless._deco_coordinator.data.confirmed_online_master = None
        elif mode == "stale":
            wireless._iot_state_identity = (MASTER_MAC, 99)
        elif mode == "paused":
            wireless._deco_coordinator.paused = True
        target = "other-master" if mode == "wrong-owner" else MASTER_MAC
        with pytest.raises(UpdateFailed, match="unavailable"):
            await wireless.async_set_iot_enabled(True, target)
        wireless.api.async_get_wireless.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_rejects_handover_during_preflight() -> None:
    """A generation change (including A -> B -> A) invalidates the write."""
    wireless = _wireless()

    async def changed_master() -> dict[str, object]:
        """Simulate master generation invalidation while the read awaits."""
        wireless._master_generation += 1
        return {"iot": {"host": {"enable": True}}}

    wireless.api.async_get_wireless.side_effect = changed_master
    with pytest.raises(UpdateFailed, match="Master Deco changed"):
        await wireless.async_set_iot_enabled(True, MASTER_MAC)
    wireless.api.async_set_iot_wireless.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_rejects_failed_readback_without_optimism() -> None:
    """A successful ACK with stale status does not authorize a success state."""
    wireless = _wireless()
    wireless.data = {"iot": False}

    with pytest.raises(UpdateFailed, match="could not be verified"):
        await wireless.async_set_iot_enabled(True, MASTER_MAC)
    wireless.api.async_set_iot_wireless.assert_awaited_once()
    assert wireless.data == {"iot": False}


@pytest.mark.asyncio
async def test_coordinator_rejects_master_change_after_write() -> None:
    """Do not report success when the active mesh changes during network I/O."""
    wireless = _wireless()

    async def write_then_change(*args: object) -> None:
        """Invalidate the generation after a simulated accepted write."""
        wireless._master_generation += 1

    wireless.api.async_set_iot_wireless.side_effect = write_then_change
    with pytest.raises(UpdateFailed, match="Master Deco changed"):
        await wireless.async_set_iot_enabled(True, MASTER_MAC)
    wireless.async_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_switch_discovery_is_owner_scoped_and_idempotent() -> None:
    """Keep polling switch and existing read-only sensors unchanged."""
    wireless = _wireless()
    deco = wireless._deco_coordinator
    entry = MagicMock(entry_id="mesh-one")
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "mesh-one": {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_WIRELESS_KEY: wireless,
            }
        }
    }
    batches: list[list[object]] = []
    with patch("custom_components.tplink_deco.switch._migrate_polling_switch_unique_id"):
        await async_setup_entry(hass, entry, batches.append)

    entities = [entity for batch in batches for entity in batch]
    assert len(entities) == 2
    assert isinstance(entities[0], DecoPollingSwitch)
    switch = entities[1]
    assert isinstance(switch, DecoIotWifiSwitch)
    assert switch.unique_id == f"{MASTER_MAC}_iot_wifi_switch"
    assert switch.is_on is True
    assert switch.available is True
    assert switch.device_info["identifiers"] == {(DOMAIN, MASTER_MAC)}

    callback = wireless.async_add_listener.call_args.args[0]
    callback()
    assert len(batches) == 2

    async def confirm_off() -> None:
        """Mock the router's post-write status readback."""
        wireless.data = {"iot": False}

    wireless.async_refresh.side_effect = confirm_off
    await switch.async_turn_off()
    wireless.api.async_set_iot_wireless.assert_awaited_once()
    wireless._deco_coordinator.data.confirmed_online_master = None
    assert switch.available is False


@pytest.mark.asyncio
async def test_iot_switch_not_discovered_without_current_valid_status() -> None:
    """Avoid exposing controls before a supported/current IoT status poll."""
    wireless = _wireless()
    wireless._iot_state_identity = None
    entry = MagicMock(entry_id="mesh-one")
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "mesh-one": {
                COORDINATOR_DECOS_KEY: wireless._deco_coordinator,
                COORDINATOR_WIRELESS_KEY: wireless,
            }
        }
    }
    batches: list[list[object]] = []
    with patch("custom_components.tplink_deco.switch._migrate_polling_switch_unique_id"):
        await async_setup_entry(hass, entry, batches.append)
    assert sum(len(batch) for batch in batches) == 1


@pytest.mark.asyncio
async def test_real_wireless_refresh_claims_only_its_master_generation() -> None:
    """New IoT controls require a successful poll, never stale cached flags."""
    wireless = _wireless()
    wireless._iot_state_identity = None
    assert await wireless._async_update_data() == {"iot": True}
    assert wireless._iot_state_identity == (MASTER_MAC, 0)

    wireless._deco_coordinator.data.master_deco = TpLinkDeco("02:00:00:00:01:98")
    wireless._observe_master()
    assert wireless._iot_state_identity is None
    assert not wireless.iot_state_is_current(MASTER_MAC)


@pytest.mark.asyncio
async def test_concurrent_iot_actions_are_serialized() -> None:
    """A second command must not enter its preflight while first holds lock."""
    wireless = _wireless()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def delayed_write(*args: object) -> None:
        """Hold the first write until the other action has been scheduled."""
        first_entered.set()
        await release_first.wait()

    wireless.api.async_set_iot_wireless.side_effect = delayed_write

    first = asyncio.create_task(wireless.async_set_iot_enabled(True, MASTER_MAC))
    await first_entered.wait()
    second = asyncio.create_task(wireless.async_set_iot_enabled(True, MASTER_MAC))
    await asyncio.sleep(0)
    assert wireless.api.async_get_wireless.await_count == 1
    release_first.set()
    await asyncio.gather(first, second)
    assert wireless.api.async_get_wireless.await_count == 2
