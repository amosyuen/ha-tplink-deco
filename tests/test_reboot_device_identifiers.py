"""Regression tests for TP-Link Deco reboot device-registry identifiers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.const import ATTR_DEVICE_ID
import pytest

from custom_components.tplink_deco import _deco_mac_from_identifiers
from custom_components.tplink_deco import async_setup_entry
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SERVICE_REBOOT_DECO

MAC_1 = "AA:BB:CC:DD:EE:01"
MAC_2 = "AA:BB:CC:DD:EE:02"


@pytest.mark.parametrize(
    ("identifiers", "expected_mac"),
    [
        ({(DOMAIN, MAC_1)}, MAC_1),
        ({("other_integration", "another_id"), (DOMAIN, MAC_1)}, MAC_1),
        ({("other_integration", "another_id")}, None),
        ({(DOMAIN, "")}, None),
        (set(), None),
    ],
)
def test_deco_mac_from_identifiers(
    identifiers: set[tuple[str, str]], expected_mac: str | None
) -> None:
    """Select the Deco MAC regardless of unrelated registry identifiers."""
    assert _deco_mac_from_identifiers(identifiers) == expected_mac


async def _get_reboot_service() -> tuple[object, AsyncMock]:
    """Set up the integration with mocked coordinators and capture the handler."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    config_entry = MagicMock()
    config_entry.entry_id = "entry_1"
    reboot_api = AsyncMock()
    deco_coordinator = MagicMock()
    deco_coordinator.api.async_reboot_decos = reboot_api

    with patch(
        "custom_components.tplink_deco.async_create_config_data",
        new_callable=AsyncMock,
        return_value={COORDINATOR_DECOS_KEY: deco_coordinator},
    ):
        assert await async_setup_entry(hass, config_entry) is True

    handler = next(
        call.args[2]
        for call in hass.services.async_register.call_args_list
        if call.args[:2] == (DOMAIN, SERVICE_REBOOT_DECO)
    )
    return handler, reboot_api


@pytest.mark.asyncio
async def test_reboot_service_accepts_multiple_identifiers() -> None:
    """Reboot selected Decos even if their registry entries have extra IDs."""
    handler, reboot_api = await _get_reboot_service()
    registry = MagicMock()
    registry.async_get.side_effect = [
        SimpleNamespace(identifiers={(DOMAIN, MAC_1), ("other", "device")}),
        SimpleNamespace(identifiers={(DOMAIN, MAC_2)}),
    ]

    with patch(
        "custom_components.tplink_deco.device_registry.async_get",
        return_value=registry,
    ):
        await handler(SimpleNamespace(data={ATTR_DEVICE_ID: ["device_1", "device_2"]}))

    reboot_api.assert_awaited_once_with([MAC_1, MAC_2])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identifiers",
    [set(), {("other_integration", "another_id")}, {(DOMAIN, "")}],
)
async def test_reboot_service_rejects_missing_deco_identifier(
    identifiers: set[tuple[str, str]],
) -> None:
    """Report an actionable error and avoid rebooting unrelated devices."""
    handler, reboot_api = await _get_reboot_service()
    registry = MagicMock()
    registry.async_get.return_value = SimpleNamespace(identifiers=identifiers)

    with patch(
        "custom_components.tplink_deco.device_registry.async_get",
        return_value=registry,
    ):
        with pytest.raises(Exception, match="does not have tplink_deco MAC identifier"):
            await handler(SimpleNamespace(data={ATTR_DEVICE_ID: ["device_1"]}))

    reboot_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_reboot_service_rejects_missing_registry_device() -> None:
    """Reject unknown registry devices without invoking the Deco API."""
    handler, reboot_api = await _get_reboot_service()
    registry = MagicMock()
    registry.async_get.return_value = None

    with patch(
        "custom_components.tplink_deco.device_registry.async_get",
        return_value=registry,
    ):
        with pytest.raises(Exception, match="not a TP-Link Deco device"):
            await handler(SimpleNamespace(data={ATTR_DEVICE_ID: ["missing"]}))

    reboot_api.assert_not_awaited()
