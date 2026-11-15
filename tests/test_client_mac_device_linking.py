"""Regression tests for opt-out MAC-based Deco client device linking."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.components.device_tracker.const import ATTR_MAC
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView
import pytest
import voluptuous as vol

from custom_components.tplink_deco import async_migrate_entry
from custom_components.tplink_deco import async_remove_config_entry_device
from custom_components.tplink_deco import config_flow
from custom_components.tplink_deco.const import CONF_LINK_CLIENT_DEVICES
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.device_tracker import TplinkDecoClientDeviceTracker
from custom_components.tplink_deco.device_tracker import TplinkDecoDeviceTracker
from custom_components.tplink_deco.device_tracker import async_setup_entry

CLIENT_MAC = "02:00:00:00:00:31"
MASTER_MAC = "02:00:00:00:00:32"


def _client_tracker(
    *,
    link_client_devices: bool = True,
    mac_address: str = CLIENT_MAC,
) -> TplinkDecoClientDeviceTracker:
    """Build a tracker without needing a running router or event loop."""
    client = TpLinkDecoClient(mac_address)
    client.name = "Test Device"
    deco_coordinator = MagicMock()
    deco_coordinator.data = TpLinkDecoData()
    return TplinkDecoClientDeviceTracker(
        coordinator_decos=deco_coordinator,
        coordinator_clients=MagicMock(),
        client=client,
        client_prefix="",
        client_postfix="",
        link_client_devices=link_client_devices,
    )


@pytest.mark.parametrize("link_client_devices", [True, False])
def test_client_tracker_identity_is_stable_across_opt_out(
    link_client_devices: bool,
) -> None:
    """Preserve registry entity IDs even when automatic MAC linking stops."""
    tracker = _client_tracker(link_client_devices=link_client_devices)

    assert tracker.unique_id == CLIENT_MAC
    assert tracker.hostname == "Test Device"
    assert tracker.mac_address == (CLIENT_MAC if link_client_devices else None)
    assert tracker.extra_state_attributes.get(ATTR_MAC) == (
        None if link_client_devices else CLIENT_MAC
    )


def test_existing_client_tracker_constructor_preserves_linking_default() -> None:
    """Keep old call sites and installations linked unless opted out."""
    tracker = _client_tracker()
    assert tracker.mac_address == CLIENT_MAC
    assert tracker.unique_id == CLIENT_MAC


def test_deco_device_tracker_mac_is_unchanged() -> None:
    """Do not suppress MAC matching for physical Deco nodes."""
    master = TpLinkDeco(MASTER_MAC)
    master.update({"role": "master", "nickname": "Mesh"})
    coordinator = MagicMock()
    coordinator.data = TpLinkDecoData(master, {MASTER_MAC: master})
    tracker = TplinkDecoDeviceTracker(coordinator, master, "", "Deco")

    assert tracker.mac_address == MASTER_MAC
    assert tracker.unique_id == MASTER_MAC


def _device(
    *,
    entry_ids: set[str] | None = None,
    identifiers: set[tuple[str, str]] | None = None,
    connections: set[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    """Create a registry device representing a previously linked client."""
    return SimpleNamespace(
        config_entries={"mesh-one"} if entry_ids is None else entry_ids,
        identifiers=set() if identifiers is None else identifiers,
        connections={("mac", CLIENT_MAC)} if connections is None else connections,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("option", "entry_ids", "identifiers", "connections", "allowed"),
    [
        (False, {"mesh-one"}, set(), {("mac", CLIENT_MAC)}, True),
        (True, {"mesh-one"}, set(), {("mac", CLIENT_MAC)}, False),
        (None, {"mesh-one"}, set(), {("mac", CLIENT_MAC)}, False),
        (False, {"mesh-other"}, set(), {("mac", CLIENT_MAC)}, False),
        (False, {"mesh-one", "other"}, set(), {("mac", CLIENT_MAC)}, False),
        (False, {"mesh-one"}, {(DOMAIN, MASTER_MAC)}, {("mac", CLIENT_MAC)}, False),
        (False, {"mesh-one"}, {("other", "id")}, {("mac", CLIENT_MAC)}, False),
        (False, {"mesh-one"}, set(), set(), False),
        (False, {"mesh-one"}, set(), {("upnp", "id")}, False),
    ],
)
async def test_only_legacy_client_devices_may_be_removed(
    option: bool | None,
    entry_ids: set[str],
    identifiers: set[tuple[str, str]],
    connections: set[tuple[str, str]],
    allowed: bool,
) -> None:
    """Protect physical Deco nodes, shared devices and unrelated entries."""
    data = {} if option is None else {CONF_LINK_CLIENT_DEVICES: option}
    entry = SimpleNamespace(entry_id="mesh-one", data=data)

    result = await async_remove_config_entry_device(
        MagicMock(),
        entry,
        _device(
            entry_ids=entry_ids, identifiers=identifiers, connections=connections
        ),
    )

    assert result is allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("existing_value", [None, False, True])
async def test_migration_adds_opt_out_with_safe_default(
    version: int, existing_value: bool | None
) -> None:
    """Upgrade older config entries without changing their existing setting."""
    data: dict[str, Any] = {"host": "192.0.2.1", "client_prefix": "Home"}
    if existing_value is not None:
        data[CONF_LINK_CLIENT_DEVICES] = existing_value
    entry = SimpleNamespace(version=version, data=data)
    hass = MagicMock()

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 7
    saved = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert saved[CONF_LINK_CLIENT_DEVICES] is (
        True if existing_value is None else existing_value
    )
    assert saved["client_prefix"] == "Home"
    assert saved["host"] == (
        "http://192.0.2.1" if version == 5 else "192.0.2.1"
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_link_option_is_serializable_and_boolean(enabled: bool) -> None:
    """Expose a real Home Assistant boolean option in both flow schemas."""
    schema = vol.Schema(config_flow._get_schema({CONF_LINK_CLIENT_DEVICES: enabled}))
    key = next(
        item for item in schema.schema if item.schema == CONF_LINK_CLIENT_DEVICES
    )
    assert key.default() is enabled
    assert schema.schema[key] is bool

    view = _BaseFlowManagerView(MagicMock())

    result = view._prepare_result_json(
        {"type": FlowResultType.FORM, "data_schema": schema}
    )
    assert json.dumps(result)
    assert any(
        field["name"] == CONF_LINK_CLIENT_DEVICES for field in result["data_schema"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("kind", ["setup", "options"])
async def test_config_flow_persists_mac_link_setting(
    enabled: bool, kind: str
) -> None:
    """Save both options without changing scan interval or router identity."""
    settings = {
        "host": "http://192.0.2.1",
        "username": "admin",
        "password": "test-only",
        "scan_interval": "30",
        CONF_LINK_CLIENT_DEVICES: enabled,
    }
    entry = SimpleNamespace(entry_id="mesh-one", data=dict(settings))
    if kind == "setup":
        flow = config_flow.TplinkDecoFlowHandler()
        flow.handler = DOMAIN
    else:
        flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
        flow.handler = "mesh-one"
    flow.flow_id = "test-mac-link"
    flow.hass = MagicMock()
    flow.hass.config_entries.async_get_known_entry.return_value = entry
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ):
        if kind == "setup":
            await flow.async_step_user(settings)
            saved = flow.async_create_entry.call_args.kwargs["data"]
        else:
            await flow.async_step_init(settings)
            saved = flow.hass.config_entries.async_update_entry.call_args.kwargs[
                "data"
            ]

    assert saved[CONF_LINK_CLIENT_DEVICES] is enabled
    assert saved["scan_interval"] == 30
    assert saved["host"] == "http://192.0.2.1"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_client_platform_applies_setting_to_all_discovered_clients(
    enabled: bool,
) -> None:
    """Apply the option to new trackers without affecting device entries."""
    client = TpLinkDecoClient(CLIENT_MAC)
    client.name = "Client"
    deco_coordinator = MagicMock()
    deco_coordinator.data = TpLinkDecoData()
    client_coordinator = MagicMock()
    client_coordinator.data = {CLIENT_MAC: client}
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "mesh-one": {
                COORDINATOR_DECOS_KEY: deco_coordinator,
                COORDINATOR_CLIENTS_KEY: client_coordinator,
            }
        }
    }
    entry = SimpleNamespace(
        entry_id="mesh-one",
        data={
            "client_prefix": "",
            "client_postfix": "",
            "deco_prefix": "",
            "deco_postfix": "Deco",
            CONF_LINK_CLIENT_DEVICES: enabled,
        },
    )
    added: list[Any] = []
    with patch(
        "custom_components.tplink_deco.device_tracker.async_dispatcher_connect",
        return_value=MagicMock(),
    ):
        await async_setup_entry(hass, entry, added.extend)

    trackers = [
        item for item in added if isinstance(item, TplinkDecoClientDeviceTracker)
    ]
    assert len(trackers) == 1
    assert trackers[0].unique_id == CLIENT_MAC
    assert trackers[0].mac_address == (CLIENT_MAC if enabled else None)
