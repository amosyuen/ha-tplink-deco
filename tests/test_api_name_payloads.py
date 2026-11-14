"""API-level regression tests for firmware Deco and client name payloads."""

import base64
import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from custom_components.tplink_deco.api import TplinkDecoApi

DECO_MAC = "AA:BB:CC:DD:EE:FF"
CLIENT_MAC = "11:22:33:44:55:66"


def _encode_name(name: str) -> str:
    """Encode the name as firmware-compatible UTF-8 Base64."""
    return base64.b64encode(name.encode("utf-8")).decode("ascii")


def _mock_api(decoded_payload: dict[str, object]) -> TplinkDecoApi:
    """Construct an API client with fully mocked transport and authentication."""
    api = TplinkDecoApi(
        session=MagicMock(),
        host="http://192.0.2.1",
        username="admin",
        password="unused-test-password",
        verify_ssl=True,
    )
    api.async_login_if_needed = AsyncMock()
    api._async_post = AsyncMock(return_value={"data": "mocked-encrypted-body"})
    api._encode_payload = MagicMock(return_value="mocked-request-body")
    api._decrypt_data = MagicMock(return_value=decoded_payload)
    api._stok = "test-session"
    return api


@pytest.mark.asyncio
async def test_list_devices_handles_mixed_firmware_nicknames() -> None:
    """Decode, preserve, or omit nicknames without losing other device attributes."""
    original_devices = [
        {"mac": DECO_MAC, "custom_nickname": _encode_name("Café"), "role": "master"},
        {"mac": "00:00:00:00:00:01", "custom_nickname": "Kitchen"},
        {
            "mac": "00:00:00:00:00:02",
            "custom_nickname": "<Error Decoding Bedroom>",
        },
        {"mac": "00:00:00:00:00:03", "nickname": "study_room"},
        {"mac": "00:00:00:00:00:04", "custom_nickname": ""},
    ]
    api = _mock_api({"result": {"device_list": original_devices}})

    devices = await api._async_list_devices()

    assert [item.get("custom_nickname") for item in devices] == [
        "Café",
        "Kitchen",
        "Bedroom",
        None,
        "",
    ]
    assert devices[0]["mac"] == DECO_MAC
    assert devices[0]["role"] == "master"
    assert devices[3]["nickname"] == "study_room"
    api.async_login_if_needed.assert_awaited_once_with()
    api._async_post.assert_awaited_once()
    api._decrypt_data.assert_called_once_with(
        "List Devices", "mocked-encrypted-body"
    )


@pytest.mark.asyncio
async def test_list_clients_handles_mixed_firmware_names() -> None:
    """Decode and preserve names without altering client MAC addresses or status."""
    original_clients = [
        {"mac": CLIENT_MAC, "name": _encode_name("Laptop 💻"), "online": True},
        {"mac": "00:00:00:00:00:01", "name": "Office PC", "online": True},
        {
            "mac": "00:00:00:00:00:02",
            "name": "<Error Decoding Guest phone>",
            "online": False,
        },
        {"mac": "00:00:00:00:00:03", "name": ""},
    ]
    api = _mock_api({"result": {"client_list": original_clients}})

    clients = await api._async_list_clients("default")

    assert [item["name"] for item in clients] == [
        "Laptop 💻",
        "Office PC",
        "Guest phone",
        "",
    ]
    assert clients[0]["mac"] == CLIENT_MAC
    assert clients[0]["online"] is True
    assert clients[2]["online"] is False
    api.async_login_if_needed.assert_awaited_once_with()
    api._async_post.assert_awaited_once()
    api._decrypt_data.assert_called_once_with(
        "List Clients default", "mocked-encrypted-body"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "result_key", "name_key"),
    [
        ("_async_list_devices", "device_list", "custom_nickname"),
        ("_async_list_clients", "client_list", "name"),
    ],
)
async def test_successful_name_reads_do_not_log_private_names(
    method: str,
    result_key: str,
    name_key: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Never emit raw client or Deco names in diagnostic logs."""
    sensitive_name = "Private Household Name"
    decoded_payload = {
        "result": {result_key: [{"mac": DECO_MAC, name_key: sensitive_name}]}
    }
    api = _mock_api(decoded_payload)

    with caplog.at_level(logging.DEBUG):
        if method == "_async_list_devices":
            await api._async_list_devices()
        else:
            await api._async_list_clients("default")

    assert sensitive_name not in caplog.text
