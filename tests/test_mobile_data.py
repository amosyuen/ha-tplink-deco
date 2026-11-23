"""Regression tests for optional, privacy-safe mobile usage on 4G/5G Decos."""

import asyncio
import json
import logging
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.tplink_deco import async_setup_entry
from custom_components.tplink_deco import async_unload_entry
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import COORDINATOR_MOBILE_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import PLATFORMS
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.exceptions import ForbiddenException
from custom_components.tplink_deco.exceptions import LoginInvalidException
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.exceptions import UnexpectedApiException
from custom_components.tplink_deco.mobile import TplinkDecoMobileDataUpdateCoordinator
from custom_components.tplink_deco.mobile import supports_mobile_data
from custom_components.tplink_deco.sensor import (
    async_setup_entry as async_setup_sensors,
)
from custom_components.tplink_deco.sensor import TplinkMobileDataUsageSensor

MASTER_A = "02:00:00:00:63:01"
MASTER_B = "02:00:00:00:63:02"
PRIVATE_VALUE = "TEST_MOBILE_AUTH_TOKEN_NEVER_LOG"
DATA_USAGE = 217896125


def _api(response: object) -> TplinkDecoApi:
    """Prepare the actual API parser with encrypted transport boundaries mocked."""
    api = TplinkDecoApi(MagicMock(), "http://192.0.2.1", "test", "test", True)
    api.async_login_if_needed = AsyncMock()
    api._stok = "synthetic-token"
    api._encode_payload = MagicMock(return_value="encoded")
    api._async_post = AsyncMock(return_value={"data": "encrypted"})
    api._decrypt_data = MagicMock(return_value=response)
    return api


def _master(mac: str = MASTER_A, model: str = "Deco X50-5G") -> TpLinkDeco:
    """Create a synthetic master with an explicit, known firmware model."""
    master = TpLinkDeco(mac)
    master.device_model = model
    master.name = "Test Deco"
    return master


def _coordinator(
    *values: object, model: str = "Deco X50-5G"
) -> TplinkDecoMobileDataUpdateCoordinator:
    """Initialize every field used by the real coordinator without router I/O."""
    coordinator = object.__new__(TplinkDecoMobileDataUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_get_mobile_data_usage = AsyncMock(side_effect=values)
    coordinator._deco_coordinator = MagicMock()
    coordinator._deco_coordinator.paused = False
    master = _master(model=model)
    coordinator._deco_coordinator.data = TpLinkDecoData(master, {master.mac: master})
    coordinator.data = None
    coordinator.last_update_success = True
    coordinator._observed_master_mac = MASTER_A
    coordinator._master_generation = 0
    coordinator._data_owner_mac = None
    coordinator._data_owner_generation = None
    return coordinator


def _change_master(
    coordinator: TplinkDecoMobileDataUpdateCoordinator, master_mac: str
) -> None:
    """Deliver the actual master-update callback for a synthetic mesh change."""
    master = _master(master_mac)
    coordinator._deco_coordinator.data = TpLinkDecoData(master, {master.mac: master})
    coordinator._handle_deco_update()


@pytest.mark.parametrize(
    ("model", "supported"),
    [
        ("Deco X50-5G", True),
        ("X20-4G", True),
        ("X50", False),
        ("", False),
        (None, False),
        (25, False),
    ],
)
def test_mobile_model_detection(model: object, supported: bool) -> None:
    """Do not probe an optional endpoint on ordinary or invalid models."""
    assert supports_mobile_data(model) is supported


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, 217896125, "217896125"])
async def test_mobile_api_parses_valid_kib_usage(value: object) -> None:
    """Read only the validated mobile counter from an encrypted read response."""
    api = _api({"result": {"mobile_cpe": {"data_usage": value}}})
    assert await api._async_get_mobile_data_usage() == int(value)
    api._async_post.assert_awaited_once_with(
        "Get mobile data usage",
        "http://192.0.2.1/cgi-bin/luci/;stok=synthetic-token/admin/network",
        params={"form": "internet"},
        data="encoded",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"result": {}},
        {"result": {"mobile_cpe": {}}},
        {"result": {"mobile_cpe": []}},
        {"result": {"mobile_cpe": {"data_usage": True}}},
        {"result": {"mobile_cpe": {"data_usage": -1}}},
        {"result": {"mobile_cpe": {"data_usage": "invalid"}}},
        {"result": {"mobile_cpe": {"data_usage": 1.2}}},
        {"result": {"mobile_cpe": {"data_usage": "1.2"}}},
        {"result": {"mobile_cpe": {"data_usage": " 4 "}}},
        {"result": {"mobile_cpe": {"data_usage": "9" * 200}}},
    ],
)
async def test_mobile_api_omits_unsupported_or_invalid_counts(payload: dict) -> None:
    """Do not expose malformed or non-integral router data as measurements."""
    api = _api(payload)
    assert await api._async_get_mobile_data_usage() is None


@pytest.mark.parametrize("bad_payload", [None, [], {}, {"data": None}, 4])
@pytest.mark.asyncio
async def test_mobile_api_rejects_invalid_envelopes(bad_payload: object) -> None:
    """Reject incomplete encrypted envelopes before decrypting or logging data."""
    api = _api({"result": {}})
    api._async_post.return_value = bad_payload
    with pytest.raises(UnexpectedApiException, match="Mobile data"):
        await api._async_get_mobile_data_usage()
    api._decrypt_data.assert_not_called()


@pytest.mark.parametrize("payload", [None, [], {}, {"result": []}, {"error_code": 7}])
@pytest.mark.asyncio
async def test_mobile_api_rejects_malformed_decrypted_payloads(
    payload: object,
) -> None:
    """Use a fixed error without exposing router payloads."""
    api = _api(payload)
    with pytest.raises(UnexpectedApiException, match="Mobile data"):
        await api._async_get_mobile_data_usage()


def test_mobile_coordinator_listener_is_entry_scoped() -> None:
    """Verify actual listener registration and config-entry unload ownership."""
    config_entry = MagicMock()
    deco = MagicMock()
    deco.data = TpLinkDecoData(_master(), {})
    with patch.object(DataUpdateCoordinator, "__init__", return_value=None):
        coordinator = TplinkDecoMobileDataUpdateCoordinator(
            MagicMock(), MagicMock(), config_entry, deco
        )
    registered = deco.async_add_listener.call_args.args[0]
    assert registered == coordinator._handle_deco_update
    config_entry.async_on_unload.assert_called_once_with(
        deco.async_add_listener.return_value
    )
    assert coordinator._observed_master_mac == MASTER_A
    assert coordinator.data is None
    _change_master(coordinator, MASTER_B)
    assert coordinator._master_generation == 1


@pytest.mark.asyncio
async def test_mobile_coordinator_skips_nonmobile_missing_and_paused_models() -> None:
    """Never query an unsupported, missing or paused Deco master."""
    coordinator = _coordinator(DATA_USAGE, model="X50")
    assert await coordinator._async_update_data() is None
    coordinator.api.async_get_mobile_data_usage.assert_not_awaited()

    coordinator._deco_coordinator.data = TpLinkDecoData(None, {})
    assert await coordinator._async_update_data() is None
    coordinator.api.async_get_mobile_data_usage.assert_not_awaited()

    coordinator = _coordinator(DATA_USAGE)
    coordinator.data = 57
    coordinator._deco_coordinator.paused = True
    assert await coordinator._async_update_data() == 57
    coordinator.api.async_get_mobile_data_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_mobile_usage_coordinator_accepts_zero_and_clears_unsupported_data() -> (
    None
):
    """An explicit zero is a valid counter; missing data clears it."""
    coordinator = _coordinator(0, None)
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.data == 0
    assert coordinator.has_current_usage(MASTER_A)
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.data is None
    assert not coordinator.has_current_usage(MASTER_A)


@pytest.mark.asyncio
async def test_mobile_data_failure_is_optional_and_privacy_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Propagate authentication, sanitize ordinary errors and keep old data."""
    coordinator = _coordinator(DATA_USAGE, ValueError(PRIVATE_VALUE))
    coordinator.data = await coordinator._async_update_data()
    caplog.set_level(logging.DEBUG)
    with pytest.raises(UpdateFailed, match="Unable to read optional mobile data") as e:
        await coordinator._async_update_data()
    assert e.value.__cause__ is None
    assert e.value.__context__ is None
    assert coordinator.data == DATA_USAGE
    assert PRIVATE_VALUE not in caplog.text

    coordinator.api.async_get_mobile_data_usage = AsyncMock(
        side_effect=LoginInvalidException(PRIVATE_VALUE)
    )
    with pytest.raises(
        ConfigEntryAuthFailed, match="Mobile data authentication failed"
    ) as auth_error:
        await coordinator._async_update_data()
    assert auth_error.value.__cause__ is None
    assert auth_error.value.__context__ is None
    assert PRIVATE_VALUE not in str(auth_error.value)
    assert PRIVATE_VALUE not in caplog.text
    assert coordinator.data == DATA_USAGE


@pytest.mark.asyncio
async def test_mobile_request_does_not_swallow_cancellation() -> None:
    """Preserve Home Assistant's expected cancellation behavior."""
    coordinator = _coordinator()
    coordinator.api.async_get_mobile_data_usage = AsyncMock(
        side_effect=asyncio.CancelledError()
    )
    with pytest.raises(asyncio.CancelledError):
        await coordinator._async_update_data()


@pytest.mark.parametrize("return_to_a", [False, True])
@pytest.mark.asyncio
async def test_mobile_inflight_master_switch_invalidates_old_usage(
    return_to_a: bool,
) -> None:
    """A -> B or A -> B -> A while awaiting cannot publish an old value."""
    coordinator = _coordinator()
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_usage() -> int:
        """Return a synthetic usage reading after the master has changed."""
        started.set()
        await release.wait()
        return DATA_USAGE

    coordinator.api.async_get_mobile_data_usage = AsyncMock(side_effect=delayed_usage)
    request = asyncio.create_task(coordinator._async_update_data())
    await started.wait()
    _change_master(coordinator, MASTER_B)
    if return_to_a:
        _change_master(coordinator, MASTER_A)
    release.set()
    coordinator.data = await request
    assert coordinator.data is None
    assert not coordinator.has_current_usage(MASTER_A)
    assert not coordinator.has_current_usage(MASTER_B)
    assert coordinator._master_generation == (2 if return_to_a else 1)
    coordinator.api.async_get_mobile_data_usage = AsyncMock(return_value=DATA_USAGE)
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.has_current_usage(MASTER_A if return_to_a else MASTER_B)


@pytest.mark.asyncio
async def test_mobile_sensor_uses_existing_master_registry_and_stable_id() -> None:
    """Keep a per-master sensor unavailable when its master changes."""
    coordinator = _coordinator(DATA_USAGE)
    coordinator.data = await coordinator._async_update_data()
    sensor = TplinkMobileDataUsageSensor(
        coordinator._deco_coordinator, coordinator, MASTER_A
    )
    assert sensor.unique_id == f"{MASTER_A}_mobile_data_usage"
    # Exercise Home Assistant's actual entity naming path on the Dutch locale.
    sensor.platform_data = SimpleNamespace(
        platform_name="tplink_deco",
        domain="sensor",
        platform_translations={
            "component.tplink_deco.entity.sensor.mobile_data_usage.name": (
                "Mobiel dataverbruik"
            )
        },
        component_translations={},
    )
    assert sensor.name == "Mobiel dataverbruik"
    assert sensor.native_value == DATA_USAGE
    assert sensor.available
    assert sensor.device_info["identifiers"] == {(DOMAIN, MASTER_A)}

    _change_master(coordinator, MASTER_B)
    assert sensor.native_value is None
    assert not sensor.available


@pytest.mark.asyncio
async def test_mobile_sensor_registration_is_delayed_and_idempotent() -> None:
    """Only supported, successful firmware readings create mobile sensors."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "mobile-test"
    master = _master()
    deco = MagicMock()
    deco.data = TpLinkDecoData(master, {master.mac: master})
    client = MagicMock()
    client.has_successful_refresh = False
    mobile = MagicMock()
    mobile.data = None
    mobile.has_current_usage.return_value = False
    batches: list[list[object]] = []
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_CLIENTS_KEY: client,
                COORDINATOR_MOBILE_KEY: mobile,
            }
        }
    }
    with (
        patch(
            "custom_components.tplink_deco.sensor.async_dispatcher_connect",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.tplink_deco.sensor.entity_registry.async_get",
            return_value=MagicMock(async_get_entity_id=MagicMock(return_value=None)),
        ),
    ):
        await async_setup_sensors(hass, entry, batches.append)
    listener = mobile.async_add_listener.call_args.args[0]
    assert not any(
        isinstance(entity, TplinkMobileDataUsageSensor)
        for batch in batches
        for entity in batch
    )
    mobile.data = 0
    mobile.has_current_usage.return_value = True
    listener()
    listener()
    registered = [
        entity
        for batch in batches
        for entity in batch
        if isinstance(entity, TplinkMobileDataUsageSensor)
    ]
    assert len(registered) == 1
    assert registered[0].unique_id == f"{MASTER_A}_mobile_data_usage"
    entry.async_on_unload.assert_any_call(mobile.async_add_listener.return_value)


@pytest.mark.asyncio
async def test_mobile_diagnostics_never_export_usage_or_credentials() -> None:
    """Expose only harmless status metadata to diagnostics downloads."""
    from custom_components.tplink_deco.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    hass = MagicMock()
    entry = SimpleNamespace(entry_id="mobile-only")
    deco = _master()
    deco_coord = MagicMock()
    deco_coord.data = TpLinkDecoData(deco, {deco.mac: deco})
    deco_coord.device_list_interval_seconds = 0
    deco_coord.health = MagicMock(
        last_error="0",
        last_successful_update=None,
        response_time_ms=None,
        timeout_count=0,
        consecutive_failures=0,
    )
    deco_coord.update_interval = None
    clients = MagicMock()
    clients.data = {}
    clients.health = deco_coord.health
    clients.update_interval = None
    clients.has_successful_refresh = False
    clients.client_query_mode = "per_node"
    clients.remaining_backoff_seconds = 0
    clients.last_update_success = True
    deco_coord.paused = False
    deco_coord.last_update_success = True
    mobile = MagicMock()
    mobile.data = DATA_USAGE
    mobile.last_update_success = True
    mobile.update_interval = None
    mobile.has_current_usage.return_value = True
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: deco_coord,
                COORDINATOR_CLIENTS_KEY: clients,
                COORDINATOR_MOBILE_KEY: mobile,
            }
        }
    }
    snapshot = await async_get_config_entry_diagnostics(hass, entry)
    assert snapshot["mobile_data_coordinator"]["supported"] is True
    assert snapshot["mobile_data_coordinator"]["update_interval_seconds"] is None
    assert str(DATA_USAGE) not in json.dumps(snapshot)
    assert PRIVATE_VALUE not in json.dumps(snapshot)


@pytest.mark.asyncio
async def test_mobile_initial_refresh_is_nonblocking_and_entry_owned() -> None:
    """Schedule client and mobile reads only after platform forwarding."""
    events: list[str] = []
    scheduled: list[object] = []
    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.entry_id = "mobile-background"

    async def forward(*args: object) -> None:
        """Record that all platforms are loaded first."""
        events.append("forwarded")

    def capture_background(
        target_hass: MagicMock, coroutine: object, *, name: str
    ) -> None:
        """Capture but do not execute an entry-owned coroutine."""
        assert target_hass is hass
        assert events and events[0] == "forwarded"
        scheduled.append((name, coroutine))

    hass.config_entries.async_forward_entry_setups = AsyncMock(side_effect=forward)
    entry.async_create_background_task.side_effect = capture_background
    client = MagicMock()
    client.async_refresh = AsyncMock()
    mobile = MagicMock()
    mobile.async_refresh = AsyncMock()
    data = {
        COORDINATOR_DECOS_KEY: MagicMock(),
        COORDINATOR_CLIENTS_KEY: client,
        COORDINATOR_MOBILE_KEY: mobile,
    }
    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new=AsyncMock(return_value=data),
    ):
        assert await async_setup_entry(hass, entry) is True

    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )
    assert [name for name, _ in scheduled] == [
        "tplink_deco initial client refresh",
        "tplink_deco initial mobile data refresh",
    ]
    client.async_refresh.assert_not_awaited()
    mobile.async_refresh.assert_not_awaited()
    for _, coroutine in scheduled:
        await coroutine
    mobile.async_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_mobile_coordinator_shutdown_does_not_call_custom_close() -> None:
    """Unload platforms before shutting down the optional mobile coordinator."""
    entry = SimpleNamespace(entry_id="mobile-unload")
    deco = MagicMock()
    deco.async_shutdown = AsyncMock()
    deco.async_close = AsyncMock()
    deco.api.async_logout = AsyncMock()
    clients = MagicMock()
    clients.async_shutdown = AsyncMock()
    clients.async_close = AsyncMock()
    mobile = SimpleNamespace(async_shutdown=AsyncMock())
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry.entry_id: {
                COORDINATOR_DECOS_KEY: deco,
                COORDINATOR_CLIENTS_KEY: clients,
                COORDINATOR_MOBILE_KEY: mobile,
            }
        }
    }
    hass.config_entries.async_forward_entry_unload = AsyncMock(return_value=True)

    assert await async_unload_entry(hass, entry) is True
    assert hass.config_entries.async_forward_entry_unload.await_count == len(PLATFORMS)
    mobile.async_shutdown.assert_awaited_once()
    deco.async_close.assert_awaited_once()
    clients.async_close.assert_awaited_once()
    deco.api.async_logout.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.parametrize("status", [401, 403, 502])
@pytest.mark.asyncio
async def test_real_mobile_http_failure_redacts_authenticated_request(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    """HTTP failures cannot leak a LuCI token from aiohttp request_info."""
    api = _api({})
    api._async_post = TplinkDecoApi._async_post.__get__(api, TplinkDecoApi)
    response = MagicMock()
    response.history = []
    request_info = MagicMock()
    request_info.real_url = "http://192.0.2.1/cgi-bin/luci/;stok=" + PRIVATE_VALUE
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=PRIVATE_VALUE,
    )
    api._session.post = AsyncMock(return_value=response)
    caplog.set_level(logging.DEBUG)

    expected_error = (
        ForbiddenException if status in (401, 403) else UnexpectedApiException
    )
    with pytest.raises(expected_error) as error:
        await api._async_post(
            "Get mobile data usage",
            "http://192.0.2.1/cgi-bin/luci/;stok=synthetic-token/admin/network",
            {"form": "internet"},
            "encoded",
        )
    assert error.value.__suppress_context__
    assert PRIVATE_VALUE not in str(error.value)
    assert PRIVATE_VALUE not in "".join(traceback.format_exception(error.value))
    assert PRIVATE_VALUE not in caplog.text
    assert (api._stok is None) is (status in (401, 403))


@pytest.mark.asyncio
async def test_real_mobile_http_api_error_never_logs_private_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Firmware API errors must not log any raw mobile WAN response."""
    api = _api({})
    api._async_post = TplinkDecoApi._async_post.__get__(api, TplinkDecoApi)
    response = MagicMock()
    response.history = []
    response.raise_for_status = MagicMock()
    response.headers.getall.return_value = []
    response.json = AsyncMock(
        return_value={"error_code": PRIVATE_VALUE, "password": PRIVATE_VALUE}
    )
    api._session.post = AsyncMock(return_value=response)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(
        UnexpectedApiException, match="Mobile data request was rejected"
    ) as error:
        await api._async_post(
            "Get mobile data usage",
            "http://192.0.2.1/cgi-bin/luci/;stok=synthetic-token/admin/network",
            {"form": "internet"},
            "encoded",
        )
    assert PRIVATE_VALUE not in str(error.value)
    assert PRIVATE_VALUE not in caplog.text


def test_real_mobile_decrypt_failure_never_logs_raw_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Execute the bound decrypt helper instead of trusting a mocked parser."""
    api = _api({})
    api._decrypt_data = TplinkDecoApi._decrypt_data.__get__(api, TplinkDecoApi)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(
        UnexpectedApiException, match="Mobile data response could not be decoded"
    ) as error:
        api._decrypt_data("Get mobile data usage", PRIVATE_VALUE + "!")
    assert PRIVATE_VALUE not in str(error.value)
    assert PRIVATE_VALUE not in caplog.text


@pytest.mark.asyncio
async def test_real_mobile_connection_error_never_logs_private_host(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not format mobile request or connection errors containing private URLs."""
    api = _api({})
    api._async_post = TplinkDecoApi._async_post.__get__(api, TplinkDecoApi)
    connection_key = SimpleNamespace(host=PRIVATE_VALUE, port=80, ssl=False)
    api._session.post = AsyncMock(
        side_effect=aiohttp.ClientConnectorError(connection_key, OSError(PRIVATE_VALUE))
    )
    caplog.set_level(logging.DEBUG)
    with pytest.raises(
        UnexpectedApiException, match="Mobile data connection failed"
    ) as error:
        await api._async_post(
            "Get mobile data usage",
            "http://192.0.2.1/cgi-bin/luci/;stok=synthetic-token/admin/network",
            {"form": "internet"},
            "encoded",
        )
    assert error.value.__suppress_context__
    assert PRIVATE_VALUE not in "".join(traceback.format_exception(error.value))
    assert PRIVATE_VALUE not in caplog.text


@pytest.mark.asyncio
async def test_mobile_invalid_json_error_is_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject malformed HTTP JSON without exposing its original error text."""
    api = _api({})
    api._async_post = TplinkDecoApi._async_post.__get__(api, TplinkDecoApi)
    response = MagicMock()
    response.history = []
    response.headers.getall.return_value = []
    response.json = AsyncMock(side_effect=ValueError(PRIVATE_VALUE))
    api._session.post = AsyncMock(return_value=response)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(
        UnexpectedApiException, match="Mobile data response is malformed"
    ) as error:
        await api._async_post(
            "Get mobile data usage",
            "http://192.0.2.1/cgi-bin/luci/;stok=synthetic-token/admin/network",
            {"form": "internet"},
            "encoded",
        )
    assert error.value.__suppress_context__
    assert PRIVATE_VALUE not in "".join(traceback.format_exception(error.value))
    assert PRIVATE_VALUE not in caplog.text


@pytest.mark.asyncio
async def test_mobile_http_401_authentication_retry_is_bounded() -> None:
    """Reuse exactly one authenticated retry, never an unbounded loop."""
    api = _api({})
    api._async_get_mobile_data_usage = AsyncMock(
        side_effect=[ForbiddenException("Mobile data forbidden (HTTP 401)"), DATA_USAGE]
    )
    assert await api.async_get_mobile_data_usage() == DATA_USAGE
    assert api._async_get_mobile_data_usage.await_count == 2

    api._async_get_mobile_data_usage = AsyncMock(
        side_effect=ForbiddenException("Mobile data forbidden (HTTP 401)")
    )
    with pytest.raises(ForbiddenException):
        await api.async_get_mobile_data_usage()
    assert api._async_get_mobile_data_usage.await_count == 2


@pytest.mark.asyncio
async def test_mobile_timeout_does_not_expose_upstream_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retain timeout classification while hiding sensitive aiohttp details."""
    api = _api({})
    api._async_post = TplinkDecoApi._async_post.__get__(api, TplinkDecoApi)
    api._session.post = AsyncMock(side_effect=asyncio.TimeoutError(PRIVATE_VALUE))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(TimeoutException) as error:
        await api._async_post(
            "Get mobile data usage",
            "http://192.0.2.1/cgi-bin/luci/;stok=synthetic-token/admin/network",
            {"form": "internet"},
            "encoded",
        )
    assert error.value.__suppress_context__
    assert PRIVATE_VALUE not in "".join(traceback.format_exception(error.value))
    assert PRIVATE_VALUE not in caplog.text
