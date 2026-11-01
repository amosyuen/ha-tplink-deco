"""Tests for optional mobile data usage support."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.mobile import TplinkDecoMobileDataUpdateCoordinator
from custom_components.tplink_deco.mobile import supports_mobile_data
from custom_components.tplink_deco.sensor import TplinkMobileDataUsageSensor


def _api(response: dict) -> TplinkDecoApi:
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
    api._decrypt_data = MagicMock(return_value=response)
    api._check_authenticated_data_error_code = MagicMock()
    return api


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [217896125, "217896125"])
async def test_mobile_data_usage_parses_kib_value(value):
    api = _api({"result": {"mobile_cpe": {"data_usage": value}}})

    assert await api._async_get_mobile_data_usage() == 217896125
    api._async_post.assert_awaited_once_with(
        "Get Mobile Data Usage",
        "http://192.168.1.1/cgi-bin/luci/;stok=None/admin/network",
        params={"form": "internet"},
        data="payload",
    )
    api._check_authenticated_data_error_code.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"result": {}},
        {"result": {"mobile_cpe": {}}},
        {"result": {"mobile_cpe": {"data_usage": True}}},
        {"result": {"mobile_cpe": {"data_usage": -1}}},
        {"result": {"mobile_cpe": {"data_usage": "invalid"}}},
    ],
)
async def test_mobile_data_usage_ignores_unsupported_or_invalid_values(response):
    api = _api(response)

    assert await api._async_get_mobile_data_usage() is None


@pytest.mark.asyncio
async def test_mobile_data_coordinator_respects_polling_pause():
    coordinator = object.__new__(TplinkDecoMobileDataUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_get_mobile_data_usage = AsyncMock(return_value=200)
    coordinator._deco_coordinator = MagicMock(paused=True)
    coordinator.data = 100

    assert await coordinator._async_update_data() == 100
    coordinator.api.async_get_mobile_data_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_mobile_data_coordinator_fetches_supported_model():
    coordinator = object.__new__(TplinkDecoMobileDataUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_get_mobile_data_usage = AsyncMock(return_value=217896125)
    master_deco = TpLinkDeco("AA:BB:CC:DD:EE:01")
    master_deco.device_model = "Deco X50-5G"
    coordinator._deco_coordinator = MagicMock(
        paused=False,
        data=TpLinkDecoData(master_deco, {master_deco.mac: master_deco}),
    )

    assert await coordinator._async_update_data() == 217896125
    coordinator.api.async_get_mobile_data_usage.assert_awaited_once()


@pytest.mark.asyncio
async def test_mobile_data_coordinator_skips_non_mobile_model():
    coordinator = object.__new__(TplinkDecoMobileDataUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_get_mobile_data_usage = AsyncMock(return_value=217896125)
    master_deco = TpLinkDeco("AA:BB:CC:DD:EE:01")
    master_deco.device_model = "Deco X50"
    coordinator._deco_coordinator = MagicMock(
        paused=False,
        data=TpLinkDecoData(master_deco, {master_deco.mac: master_deco}),
    )

    assert await coordinator._async_update_data() is None
    coordinator.api.async_get_mobile_data_usage.assert_not_awaited()


@pytest.mark.parametrize(
    "model,supported",
    [
        ("Deco X50-5G", True),
        ("X20-4G", True),
        ("X50", False),
        (None, False),
    ],
)
def test_mobile_data_model_detection(model, supported):
    assert supports_mobile_data(model) is supported


def test_mobile_data_usage_sensor_uses_master_deco():
    master_deco = TpLinkDeco("AA:BB:CC:DD:EE:01")
    master_deco.name = "Living Room"
    coordinator_decos = MagicMock()
    coordinator_decos.data = TpLinkDecoData(master_deco, {master_deco.mac: master_deco})
    coordinator_mobile = MagicMock()
    coordinator_mobile.data = 217896125

    sensor = TplinkMobileDataUsageSensor(
        coordinator_decos,
        coordinator_mobile,
        master_deco.mac,
    )

    assert sensor.native_value == 217896125
    assert sensor.unique_id == f"{master_deco.mac}_mobile_data_usage"
