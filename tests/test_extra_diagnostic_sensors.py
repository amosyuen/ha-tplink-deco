"""Restore extra-branch diagnostic contracts without copying legacy behavior."""

from collections.abc import Callable
from datetime import timedelta
import json
import logging
from pathlib import Path
from types import MappingProxyType
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
import pytest

from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import CoordinatorHealth
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator
from custom_components.tplink_deco.diagnostics import async_get_config_entry_diagnostics
from custom_components.tplink_deco.node_diagnostics import parse_node_diagnostics
from custom_components.tplink_deco.sensor import DIAGNOSTIC_SENSOR_DESCRIPTIONS
from custom_components.tplink_deco.sensor import TplinkDecoDiagnosticSensor
from custom_components.tplink_deco.sensor import async_setup_entry

MASTER = "02:00:00:00:64:01"
SATELLITE = "02:00:00:00:64:02"
STATION = "02-00-00-00-64-03"
PRIVATE_ERROR = "PRIVATE-SSID PASSWORD=private-password TOKEN=private-token"
RESTORED_KEYS = {
    "group_status",
    "inet",
    "nickname",
    "role",
    "master",
    "slave",
    "standalone",
    "signal_level",
    "signal_level24",
    "signal_level5",
    "interface",
    "previous",
    "client_mesh",
    "bssid_sta_2g",
    "bssid_sta_5g",
    "set_gateway_support",
    "topology",
}


def _node(mac: str = MASTER, role: str = "master") -> dict[str, object]:
    """Return anonymous firmware data for every restored diagnostic."""
    return {
        "mac": mac,
        "role": role,
        "group_status": "connected",
        "inet_status": "offline",
        "nickname": "firmware_name",
        "custom_nickname": "User display name",
        "signal_level": {"band2_4": 0, "band5": "48"},
        "interface": "eth0",
        "previous": SATELLITE,
        "client_mesh": False,
        "bssid_sta_2g": MASTER,
        "bssid_sta_5g": STATION,
        "set_gateway_support": 0,
        "topology": {"auto": False, "device_id": SATELLITE},
        "inet_error_msg": PRIVATE_ERROR,
    }


def _coordinator(entry_id: str = "mesh-one") -> TplinkDecoUpdateCoordinator:
    """Create the actual inventory coordinator without making router requests."""
    api = MagicMock()
    api.async_list_devices = AsyncMock()
    api.async_get_performance = AsyncMock(return_value={"result": {}})
    return TplinkDecoUpdateCoordinator(
        hass=MagicMock(), api=api, config_entry=MagicMock(entry_id=entry_id)
    )


def _inventory(
    coordinator: TplinkDecoUpdateCoordinator, nodes: list[dict[str, object]]
) -> None:
    """Commit real inventory data without an external dispatcher."""
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        coordinator._process_device_list(nodes)


async def _platform(
    coordinator: TplinkDecoUpdateCoordinator, entry_id: str = "mesh-one"
) -> tuple[MagicMock, MagicMock, Callable[[], None]]:
    """Exercise actual sensor setup and capture its normal update listener."""
    clients = MagicMock(
        data={},
        has_successful_refresh=False,
        health=CoordinatorHealth(),
        update_interval=None,
        last_update_success=True,
        client_query_mode="per_node",
        remaining_backoff_seconds=0,
    )
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            entry_id: {
                COORDINATOR_DECOS_KEY: coordinator,
                COORDINATOR_CLIENTS_KEY: clients,
            }
        }
    }
    coordinator.async_add_listener = MagicMock(return_value=MagicMock())
    added = MagicMock()
    with patch("custom_components.tplink_deco.sensor.async_dispatcher_connect"):
        await async_setup_entry(hass, SimpleNamespace(entry_id=entry_id), added)
    return hass, added, coordinator.async_add_listener.call_args_list[0].args[0]


def _sensors(added: MagicMock) -> dict[str, TplinkDecoDiagnosticSensor]:
    """Collect restored diagnostics by their original registry unique IDs."""
    entities = [
        entity
        for call in added.call_args_list
        for entity in call.args[0]
        if isinstance(entity, TplinkDecoDiagnosticSensor)
        and entity.entity_description.key in RESTORED_KEYS
    ]
    assert len(entities) == len({entity.unique_id for entity in entities})
    return {entity.unique_id: entity for entity in entities}


@pytest.mark.asyncio
async def test_original_sensor_keys_values_and_read_only_device_association() -> None:
    """Keep every restored ID, false/zero state, disabled default and Deco link."""
    coordinator = _coordinator()
    _inventory(coordinator, [_node()])
    _, added, _ = await _platform(coordinator)
    sensors = _sensors(added)
    assert set(sensors) == {f"{MASTER}_{key}" for key in RESTORED_KEYS}
    expected = {
        "group_status": "connected",
        "inet": "offline",
        "nickname": "firmware_name",
        "role": "master",
        "master": True,
        "slave": False,
        "standalone": True,
        "signal_level": 0,
        "signal_level24": 0,
        "signal_level5": 48,
        "interface": "eth0",
        "previous": SATELLITE,
        "client_mesh": False,
        "bssid_sta_2g": MASTER,
        "bssid_sta_5g": STATION,
        "set_gateway_support": False,
        "topology": SATELLITE,
    }
    for key, value in expected.items():
        entity = sensors[f"{MASTER}_{key}"]
        assert entity.native_value == value
        assert type(entity.native_value) is type(value)
        assert entity.translation_key == key
        assert entity.available
        assert entity.unique_id == f"{MASTER}_{key}"
        assert entity.entity_description.entity_category == "diagnostic"
        assert entity.entity_description.entity_registry_enabled_default is False
        assert entity.device_info["identifiers"] == {(DOMAIN, MASTER)}
    assert coordinator.data.master_deco.name == "User display name"
    assert not any(
        item.key == "inet_error_msg" for item in DIAGNOSTIC_SENSOR_DESCRIPTIONS
    )
    coordinator.api.async_list_devices.assert_not_called()
    coordinator.api.async_get_performance.assert_not_called()


@pytest.mark.parametrize("internet", [False, True, 0, 1, "up", "offline"])
def test_internet_status_uses_the_real_firmware_field(internet: object) -> None:
    """Retain genuine scalar states instead of reading extra's unset inet field."""
    values = parse_node_diagnostics({"inet_status": internet, "inet": "wrong-field"})
    assert values["inet"] == internet
    assert type(values["inet"]) is type(internet)


@pytest.mark.parametrize(
    ("payload", "absent_key"),
    [
        ({"group_status": []}, "group_status"),
        ({"nickname": {"private": PRIVATE_ERROR}}, "nickname"),
        ({"nickname": " "}, "nickname"),
        ({"nickname": "x" * 256}, "nickname"),
        ({"nickname": "bad\nname"}, "nickname"),
        ({"role": None}, "master"),
        ({"role": "unknown"}, "slave"),
        ({"interface": ["eth0"]}, "interface"),
        ({"inet_status": []}, "inet"),
        ({"inet_status": 2}, "inet"),
        ({"inet_status": 1.0}, "inet"),
        ({"client_mesh": "false"}, "client_mesh"),
        ({"set_gateway_support": "0"}, "set_gateway_support"),
        ({"set_gateway_support": 1.0}, "set_gateway_support"),
        ({"previous": PRIVATE_ERROR}, "previous"),
        ({"previous": "02:00-00:00:64:01"}, "previous"),
        ({"bssid_sta_2g": {}}, "bssid_sta_2g"),
        ({"bssid_sta_5g": "invalid"}, "bssid_sta_5g"),
        ({"bssid_sta_5g": "00:00:00:00:00:00"}, "bssid_sta_5g"),
        ({"previous": "FF-FF-FF-FF-FF-FF"}, "previous"),
        ({"signal_level": {"band2_4": True}}, "signal_level24"),
        ({"signal_level": {"band2_4": 2.5}}, "signal_level24"),
        ({"signal_level": {"band5": -1}}, "signal_level5"),
        ({"signal_level": {"band5": "NaN"}}, "signal_level5"),
        ({"signal_level": {"band5": 2**100}}, "signal_level5"),
        ({"topology": None}, "topology"),
        ({"topology": []}, "topology"),
        ({"topology": {"auto": "false", "device_id": MASTER}}, "topology"),
        ({"topology": {}}, "topology"),
        ({"topology": {"auto": False, "device_id": PRIVATE_ERROR}}, "topology"),
        ({"topology": {"device_id": MASTER}}, "topology"),
        ({"topology": {"auto": True, "device_id": []}}, "topology"),
    ],
)
def test_malformed_optional_fields_never_create_invented_states(
    payload: dict[str, object], absent_key: str
) -> None:
    """Ignore invalid optional scalars without exposing containers or false OFF."""
    assert absent_key not in parse_node_diagnostics(payload)


def test_missing_fields_flags_and_signal_fallback() -> None:
    """Keep unknown fields absent and accept explicit false and zero values."""
    assert parse_node_diagnostics({}) == {}
    assert parse_node_diagnostics({"inet_error_msg": PRIVATE_ERROR}) == {}
    assert parse_node_diagnostics({"previous": "020000006401"}) == {
        "previous": "020000006401"
    }
    assert parse_node_diagnostics({"topology": {"auto": False}}) == {
        "topology": "fixed"
    }
    assert parse_node_diagnostics({"topology": {"auto": True, "device_id": ""}}) == {
        "topology": "auto"
    }
    values = parse_node_diagnostics(
        {
            "client_mesh": 0,
            "set_gateway_support": 1,
            "signal_level": {"band2_4": None, "band5": "0"},
            "topology": {"auto": True},
        }
    )
    assert values == {
        "client_mesh": False,
        "set_gateway_support": True,
        "signal_level": 0,
        "signal_level5": 0,
        "topology": "auto",
    }


@pytest.mark.asyncio
async def test_late_fields_offline_nodes_missing_values_and_reload_keep_identity() -> (
    None
):
    """Register later values once and retain identities through loss and recovery."""
    coordinator = _coordinator()
    _inventory(coordinator, [{"mac": MASTER}])
    _, added, notify = await _platform(coordinator)
    assert _sensors(added) == {}

    _inventory(coordinator, [_node(), _node(SATELLITE, "slave")])
    notify()
    notify()
    sensors = _sensors(added)
    master = coordinator.data.decos[MASTER]
    satellite = coordinator.data.decos[SATELLITE]
    assert len(sensors) == 34
    assert sensors[f"{SATELLITE}_master"].native_value is False
    assert sensors[f"{SATELLITE}_slave"].native_value is True
    assert sensors[f"{MASTER}_standalone"].native_value is False

    _inventory(
        coordinator,
        [
            {"mac": MASTER, "role": "master", "set_gateway_support": False},
            {**_node(SATELLITE, "slave"), "group_status": "disconnected"},
        ],
    )
    notify()
    assert sensors[f"{MASTER}_set_gateway_support"].available
    assert sensors[f"{MASTER}_set_gateway_support"].native_value is False
    assert sensors[f"{SATELLITE}_group_status"].available
    assert sensors[f"{SATELLITE}_group_status"].native_value == "disconnected"
    assert not sensors[f"{SATELLITE}_master"].available

    _inventory(coordinator, [_node()])
    notify()
    assert coordinator.data.decos[SATELLITE] is satellite
    assert sensors[f"{MASTER}_standalone"].native_value is False
    assert not sensors[f"{SATELLITE}_master"].available
    assert sensors[f"{SATELLITE}_master"].device_info["identifiers"] == {
        (DOMAIN, SATELLITE)
    }

    _inventory(coordinator, [{"mac": MASTER, "group_status": "connected"}])
    notify()
    assert coordinator.data.decos[MASTER] is master
    assert not sensors[f"{MASTER}_master"].available
    assert sensors[f"{MASTER}_master"].native_value is None
    assert len(_sensors(added)) == 34

    _inventory(coordinator, [_node(), _node(SATELLITE, "slave")])
    notify()
    assert sensors[f"{MASTER}_master"].available
    assert len(_sensors(added)) == 34
    _, reloaded, _ = await _platform(coordinator)
    assert set(_sensors(reloaded)) == set(sensors)
    assert all(
        entity.entity_description.entity_registry_enabled_default is False
        for entity in _sensors(reloaded).values()
    )


@pytest.mark.asyncio
async def test_missing_or_ambiguous_master_does_not_invent_standalone_topology() -> (
    None
):
    """Require exactly one confirmed current master rather than a stale role."""
    coordinator = _coordinator()
    for nodes in (
        [_node(SATELLITE, "slave")],
        [_node(), _node(SATELLITE)],
        [],
    ):
        _inventory(coordinator, nodes)
        assert all(
            "standalone" not in deco.diagnostic_values
            for deco in coordinator.data.decos.values()
        )


@pytest.mark.asyncio
async def test_actual_refresh_privacy_failure_recovery_and_config_entry_isolation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep sensitive fields out of logs/downloads and retain models on failures."""
    caplog.set_level(logging.DEBUG)
    coordinator = _coordinator()
    coordinator.api.async_list_devices.return_value = [_node()]
    coordinator.hass.is_stopping = False
    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        await coordinator.async_request_device_refresh()
    master = coordinator.data.master_deco
    hass, added, notify = await _platform(coordinator)
    entity = _sensors(added)[f"{MASTER}_master"]

    coordinator.api.async_list_devices.side_effect = TimeoutError("synthetic failure")
    with pytest.raises(HomeAssistantError, match="Unable to refresh Deco status"):
        await coordinator.async_request_device_refresh()
    assert coordinator.last_update_success is False
    assert not entity.available
    assert coordinator.data.master_deco is master
    assert entity.native_value is True
    coordinator.api.async_list_devices.side_effect = None
    await coordinator.async_request_device_refresh()
    assert coordinator.last_update_success is True
    notify()
    assert entity.available

    second = _coordinator("mesh-two")
    _inventory(second, [_node(SATELLITE, "slave")])
    _, second_added, _ = await _platform(second, "mesh-two")
    assert f"{MASTER}_master" not in _sensors(second_added)
    assert _sensors(second_added)[f"{SATELLITE}_master"].native_value is False

    exported = json.dumps(
        await async_get_config_entry_diagnostics(
            hass, SimpleNamespace(entry_id="mesh-one")
        )
    )
    for secret in (
        PRIVATE_ERROR,
        MASTER,
        SATELLITE,
        STATION,
        "firmware_name",
        "User display name",
    ):
        assert secret not in caplog.text
        assert secret not in exported
    assert "diagnostic_values" not in exported
    assert coordinator.api.async_list_devices.await_count == 3
    assert coordinator.api.async_get_performance.await_count == 2


@pytest.mark.parametrize("locale", ["en", "nl", "fr", "nb", "pt", "pt-BR", "sk", "sv"])
def test_restored_sensor_names_are_translated_in_every_shipped_locale(
    locale: str,
) -> None:
    """Keep translation keys complete without changing previously shipped labels."""
    integration = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    labels = json.loads(
        (integration / "translations" / f"{locale}.json").read_text(encoding="utf-8")
    )
    for key in RESTORED_KEYS:
        assert labels["entity"]["sensor"][key]["name"].strip()


@pytest.mark.asyncio
async def test_legacy_enabled_sensor_reclaims_custom_entity_and_device(
    tmp_path: Path,
) -> None:
    """Exercise Home Assistant's registry and state machine after a sparse startup."""
    hass = HomeAssistant(str(tmp_path))
    entry = ConfigEntry(
        data={},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id="mesh-one",
        minor_version=1,
        options={},
        source="user",
        subentries_data=None,
        title="Mesh",
        unique_id=None,
        version=7,
    )
    hass.config_entries = MagicMock(spec=ConfigEntries)
    hass.config_entries.async_get_entry.return_value = entry
    # HA 2026.11 sets the device registry up before loading it.
    if hasattr(dr, "async_setup"):
        dr.async_setup(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    registry = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, MASTER)},
        name="Test Deco",
    )
    prior = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{MASTER}_master",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="my_custom_master",
        disabled_by=None,
    )
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain=Platform.SENSOR,
        platform_name=DOMAIN,
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    try:
        coordinator = _coordinator()
        _inventory(coordinator, [{"mac": MASTER}])
        _, added, notify = await _platform(coordinator)
        assert not _sensors(added)
        assert registry.async_get(prior.entity_id).device_id == device.id
        _inventory(coordinator, [{"mac": MASTER, "role": "master"}])
        notify()
        sensors = _sensors(added)
        await platform.async_add_entities(
            [sensors[f"{MASTER}_master"], sensors[f"{MASTER}_slave"]]
        )
        current = registry.async_get(prior.entity_id)
        assert current.id == prior.id and current.device_id == device.id
        assert current.config_entry_id == entry.entry_id
        assert current.disabled_by is None
        assert hass.states.get(prior.entity_id).state == "True"
        new_id = registry.async_get_entity_id("sensor", DOMAIN, f"{MASTER}_slave")
        assert (
            registry.async_get(new_id).disabled_by
            == er.RegistryEntryDisabler.INTEGRATION
        )
        assert hass.states.get(new_id) is None
    finally:
        await platform.async_reset()
        await hass.async_stop()
