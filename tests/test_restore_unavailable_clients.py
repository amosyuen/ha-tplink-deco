"""Regressions for restoring unavailable client trackers across HA releases."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.components.device_tracker.const import CONF_CONSIDER_HOME
from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
import pytest

from custom_components.tplink_deco import _remove_discovered_decos_from_clients
from custom_components.tplink_deco import async_create_and_refresh_coordinators
from custom_components.tplink_deco import async_create_config_data
from custom_components.tplink_deco.const import ATTR_DEVICE_TYPE
from custom_components.tplink_deco.const import DEVICE_TYPE_CLIENT
from custom_components.tplink_deco.const import DEVICE_TYPE_DECO
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.coordinator import TplinkDecoUpdateCoordinator

DECO_MAC = "AA:BB:CC:DD:EE:01"
CLIENT_MAC = "AA:BB:CC:DD:EE:02"
OTHER_CLIENT_MAC = "AA:BB:CC:DD:EE:03"


def _entry(
    mac: str,
    *,
    domain: str = "device_tracker",
    disabled_by: str | None = None,
    device_id: str | None = None,
) -> SimpleNamespace:
    """Represent a registry entity without changing its MAC-based identity."""
    return SimpleNamespace(
        domain=domain,
        disabled_by=disabled_by,
        device_id=device_id,
        unique_id=mac,
        entity_id=f"{domain}.{mac.lower().replace(':', '_')}",
        original_name=f"Device {mac[-2:]}",
    )


def _stored_state(
    device_type: str | None = None, *, status: str = "unavailable"
) -> SimpleNamespace:
    """Create stored state with an optional device classification."""
    attributes = {} if device_type is None else {ATTR_DEVICE_TYPE: device_type}
    return SimpleNamespace(state=SimpleNamespace(state=status, attributes=attributes))


async def _restore(
    entries: list[SimpleNamespace],
    stored_states: dict[str, SimpleNamespace],
    *,
    modern_api: bool,
    entry_id: str = "mesh-one",
) -> tuple[TpLinkDecoData, dict[str, TpLinkDecoClient], MagicMock]:
    """Exercise the integration's actual registry/restore setup path."""
    config_entry = SimpleNamespace(entry_id=entry_id, data={})
    restore_lookup = MagicMock(side_effect=stored_states.get)
    if modern_api:
        restore_data = SimpleNamespace(async_get_stored_state=restore_lookup)
    else:
        restore_data = SimpleNamespace(last_states=stored_states)
    coordinator_factory = AsyncMock(return_value={})

    with (
        patch(
            "custom_components.tplink_deco.entity_registry."
            "async_entries_for_config_entry",
            return_value=entries,
        ) as registry_entries,
        patch("custom_components.tplink_deco.entity_registry.async_get"),
        patch(
            "custom_components.tplink_deco.restore_state.async_get",
            return_value=restore_data,
        ),
        patch(
            "custom_components.tplink_deco.async_create_and_refresh_coordinators",
            new=coordinator_factory,
        ),
    ):
        await async_create_config_data(MagicMock(), config_entry)

    registry_entries.assert_called_once()
    assert registry_entries.call_args.args[1] == entry_id
    coordinator_factory.assert_awaited_once()
    call_args = coordinator_factory.await_args.args
    if modern_api:
        eligible_entries = [
            item
            for item in entries
            if item.domain == "device_tracker" and item.disabled_by is None
        ]
        assert restore_lookup.call_count == len(eligible_entries)
    return call_args[5], call_args[6], restore_lookup


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
async def test_restore_passes_exact_coordinator_arguments_and_original_names(
    modern_api: bool,
) -> None:
    """Match the real positional startup contract for both HA restore APIs."""
    entry = _entry(CLIENT_MAC)
    config_entry = SimpleNamespace(
        entry_id="mesh-positional",
        data={CONF_SCAN_INTERVAL: 60, CONF_CONSIDER_HOME: 240},
    )
    stored_state = _stored_state()
    lookup = MagicMock(return_value=stored_state)
    restore_data = (
        SimpleNamespace(async_get_stored_state=lookup)
        if modern_api
        else SimpleNamespace(last_states={entry.entity_id: stored_state})
    )
    hass = MagicMock()
    coordinator_factory = AsyncMock(return_value={"decos": None, "clients": None})

    with (
        patch(
            "custom_components.tplink_deco.entity_registry."
            "async_entries_for_config_entry",
            return_value=[entry],
        ) as registry,
        patch("custom_components.tplink_deco.entity_registry.async_get"),
        patch(
            "custom_components.tplink_deco.restore_state.async_get",
            return_value=restore_data,
        ),
        patch(
            "custom_components.tplink_deco.async_create_and_refresh_coordinators",
            new=coordinator_factory,
        ),
    ):
        actual = await async_create_config_data(hass, config_entry)

    assert actual == {"decos": None, "clients": None}
    registry.assert_called_once()
    assert registry.call_args.args[1] == "mesh-positional"
    coordinator_factory.assert_awaited_once()
    arguments = coordinator_factory.await_args.args
    assert len(arguments) == 7
    assert coordinator_factory.await_args.kwargs == {}
    assert arguments[0] is hass
    assert arguments[1] is config_entry.data
    assert arguments[2] is config_entry
    assert arguments[3] == 240
    assert arguments[4] == timedelta(seconds=60)
    assert isinstance(arguments[5], TpLinkDecoData)
    assert arguments[5].decos == {}
    assert list(arguments[6]) == [CLIENT_MAC]
    assert arguments[6][CLIENT_MAC].name == entry.original_name
    assert arguments[6][CLIENT_MAC].online is False
    if modern_api:
        lookup.assert_called_once_with(entry.entity_id)



@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
@pytest.mark.parametrize(
    "malformed_state",
    [
        SimpleNamespace(state=None),
        SimpleNamespace(state=SimpleNamespace()),
        SimpleNamespace(state=SimpleNamespace(attributes=None)),
        SimpleNamespace(state=SimpleNamespace(attributes=[])),
    ],
)
async def test_malformed_restored_state_does_not_block_other_clients(
    modern_api: bool,
    malformed_state: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Skip corrupt restore records while retaining valid offline clients."""
    broken_entry = _entry(DECO_MAC)
    client_entry = _entry(CLIENT_MAC)
    states = {
        broken_entry.entity_id: malformed_state,
        client_entry.entity_id: _stored_state(),
    }

    decos, clients, _ = await _restore(
        [broken_entry, client_entry], states, modern_api=modern_api
    )

    assert decos.decos == {}
    assert list(clients) == [CLIENT_MAC]
    assert clients[CLIENT_MAC].name == client_entry.original_name
    assert clients[CLIENT_MAC].online is False
    assert "Skipping tracker with malformed restored-state attributes" in caplog.text
    assert broken_entry.entity_id not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
@pytest.mark.parametrize("invalid_device_type", ["unrecognized", 42, []])
async def test_unrecognized_device_type_checks_exact_registry_identity(
    modern_api: bool,
    invalid_device_type: object,
) -> None:
    """Classify unknown types by the registry's exact Deco MAC if available."""
    deco_entry = _entry(DECO_MAC, device_id="registered-deco")
    devices = MagicMock()
    devices.async_get.return_value = SimpleNamespace(identifiers={(DOMAIN, DECO_MAC)})
    stored_state = SimpleNamespace(
        state=SimpleNamespace(attributes={ATTR_DEVICE_TYPE: invalid_device_type})
    )

    with patch(
        "custom_components.tplink_deco.device_registry.async_get",
        return_value=devices,
    ):
        decos, clients, _ = await _restore(
            [deco_entry],
            {deco_entry.entity_id: stored_state},
            modern_api=modern_api,
        )

    assert set(decos.decos) == {DECO_MAC}
    assert clients == {}
    assert decos.decos[DECO_MAC].name == deco_entry.original_name


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
async def test_restore_multiple_offline_clients_keeps_registry_names(
    modern_api: bool,
) -> None:
    """Do not collapse client identity or discard names when several are offline."""
    first_entry = _entry(CLIENT_MAC)
    second_entry = _entry(OTHER_CLIENT_MAC)
    first_entry.original_name = "Kitchen phone"
    second_entry.original_name = "Hall tablet"
    restored = {
        first_entry.entity_id: _stored_state(status="unknown"),
        second_entry.entity_id: _stored_state(status="unavailable"),
    }

    decos, clients, lookup = await _restore(
        [first_entry, second_entry],
        restored,
        modern_api=modern_api,
    )

    assert decos.decos == {}
    assert set(clients) == {CLIENT_MAC, OTHER_CLIENT_MAC}
    assert clients[CLIENT_MAC].name == "Kitchen phone"
    assert clients[OTHER_CLIENT_MAC].name == "Hall tablet"
    assert all(client.online is False for client in clients.values())
    if modern_api:
        assert lookup.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
@pytest.mark.parametrize("status", ["unavailable", "unknown", "not_home"])
async def test_restores_existing_client_without_device_type(
    modern_api: bool, status: str
) -> None:
    """Do not permanently lose a tracker whose restored attributes vanished."""
    entry = _entry(CLIENT_MAC)
    deco_data, clients, _ = await _restore(
        [entry],
        {entry.entity_id: _stored_state(status=status)},
        modern_api=modern_api,
    )

    assert deco_data.decos == {}
    assert list(clients) == [CLIENT_MAC]
    assert clients[CLIENT_MAC].mac == CLIENT_MAC
    assert clients[CLIENT_MAC].name == entry.original_name
    assert clients[CLIENT_MAC].online is False


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
async def test_restores_known_deco_and_explicit_client_separately(
    modern_api: bool,
) -> None:
    """Retain previously classified Deco and client records without changes."""
    deco_entry = _entry(DECO_MAC)
    client_entry = _entry(CLIENT_MAC)
    states = {
        deco_entry.entity_id: _stored_state(DEVICE_TYPE_DECO),
        client_entry.entity_id: _stored_state(DEVICE_TYPE_CLIENT),
    }

    decos, clients, _ = await _restore(
        [deco_entry, client_entry], states, modern_api=modern_api
    )

    assert set(decos.decos) == {DECO_MAC}
    assert decos.decos[DECO_MAC].mac == DECO_MAC
    assert decos.decos[DECO_MAC].name == deco_entry.original_name
    assert set(clients) == {CLIENT_MAC}
    assert clients[CLIENT_MAC].name == client_entry.original_name


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
async def test_ignores_disabled_unrelated_and_unrestored_entries(
    modern_api: bool,
) -> None:
    """Never create trackers for disabled or unrelated registry entries."""
    disabled_entry = _entry(DECO_MAC, disabled_by="user")
    unrelated_entry = _entry(CLIENT_MAC, domain="sensor")
    absent_entry = _entry(OTHER_CLIENT_MAC)
    states = {
        disabled_entry.entity_id: _stored_state(),
        unrelated_entry.entity_id: _stored_state(),
    }

    decos, clients, lookup = await _restore(
        [disabled_entry, unrelated_entry, absent_entry],
        states,
        modern_api=modern_api,
    )

    assert decos.decos == {}
    assert clients == {}
    if modern_api:
        lookup.assert_called_once_with(absent_entry.entity_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
async def test_restore_isolated_per_config_entry(modern_api: bool) -> None:
    """Seed only entities belonging to the config entry being initialized."""
    first_entry = _entry(CLIENT_MAC)
    second_entry = _entry(OTHER_CLIENT_MAC)
    saved_states = {
        first_entry.entity_id: _stored_state(),
        second_entry.entity_id: _stored_state(),
    }

    _, first_clients, _ = await _restore(
        [first_entry], saved_states, modern_api=modern_api, entry_id="mesh-one"
    )
    _, second_clients, _ = await _restore(
        [second_entry], saved_states, modern_api=modern_api, entry_id="mesh-two"
    )

    assert set(first_clients) == {CLIENT_MAC}
    assert set(second_clients) == {OTHER_CLIENT_MAC}


def test_removes_only_confirmed_deco_macs_from_provisional_clients() -> None:
    """Reconcile IDs without removing other disconnected client trackers."""
    wrongly_classified = TpLinkDecoClient(DECO_MAC)
    genuine_client = TpLinkDecoClient(CLIENT_MAC)
    clients = {DECO_MAC: wrongly_classified, CLIENT_MAC: genuine_client}
    deco = TpLinkDeco(DECO_MAC)
    deco_data = TpLinkDecoData(deco, {DECO_MAC: deco})

    _remove_discovered_decos_from_clients(clients, deco_data)
    _remove_discovered_decos_from_clients(clients, deco_data)

    assert clients == {CLIENT_MAC: genuine_client}
    assert clients[CLIENT_MAC] is genuine_client


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
async def test_unavailable_deco_remains_a_deco_when_initially_offline(
    modern_api: bool,
) -> None:
    """Use the matching registry identifier before any router discovery."""
    entry = _entry(DECO_MAC, device_id="recorded-deco-device")
    device = SimpleNamespace(identifiers={(DOMAIN, DECO_MAC)})
    devices = MagicMock()
    devices.async_get.return_value = device

    with patch(
        "custom_components.tplink_deco.device_registry.async_get",
        return_value=devices,
    ) as registry:
        deco_data, clients, _ = await _restore(
            [entry],
            {entry.entity_id: _stored_state()},
            modern_api=modern_api,
        )

    registry.assert_called_once()
    devices.async_get.assert_called_once_with(entry.device_id)
    assert clients == {}
    assert deco_data.decos[DECO_MAC].name == entry.original_name

    # The router can omit a known offline Deco during the first refresh.
    # It must remain a Deco and retain its identity when it appears later.
    api = MagicMock()
    api.async_list_devices = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "mac": DECO_MAC,
                    "role": "master",
                    "nickname": "living_room",
                    "group_status": "connected",
                    "inet_status": "online",
                }
            ],
        ]
    )
    api.async_get_performance = AsyncMock(return_value={"result": {}})
    coordinator = TplinkDecoUpdateCoordinator(
        hass=MagicMock(),
        api=api,
        config_entry=MagicMock(),
        data=deco_data,
    )
    saved_deco = deco_data.decos[DECO_MAC]

    with patch("custom_components.tplink_deco.coordinator.async_dispatcher_send"):
        missing = await coordinator._async_update_data()
        assert missing.decos[DECO_MAC] is saved_deco
        assert saved_deco.online is False
        # Ordinary status polling is now interval-controlled: force a
        # manual refresh to simulate the restored Deco becoming visible.
        coordinator.async_refresh = AsyncMock(
            side_effect=coordinator._async_update_data
        )
        await coordinator.async_request_device_refresh()
        restored = coordinator.data

    assert restored.decos[DECO_MAC] is saved_deco
    assert restored.master_deco is saved_deco
    assert saved_deco.online is True
    assert clients == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_api", [False, True])
async def test_client_attached_to_deco_device_is_not_misclassified(
    modern_api: bool,
) -> None:
    """Compare the registry Deco identifier to the entity's own MAC."""
    client_entry = _entry(CLIENT_MAC, device_id="shared-deco-device")
    device = SimpleNamespace(identifiers={(DOMAIN, DECO_MAC)})
    devices = MagicMock()
    devices.async_get.return_value = device

    with patch(
        "custom_components.tplink_deco.device_registry.async_get",
        return_value=devices,
    ):
        decos, clients, _ = await _restore(
            [client_entry],
            {client_entry.entity_id: _stored_state()},
            modern_api=modern_api,
        )

    assert decos.decos == {}
    assert set(clients) == {CLIENT_MAC}
    assert clients[CLIENT_MAC].mac == CLIENT_MAC


@pytest.mark.asyncio
async def test_first_deco_refresh_reconciles_clients_before_client_setup() -> None:
    """Discard provisional Deco clients only after confirmed device discovery."""
    known_client = TpLinkDecoClient(CLIENT_MAC)
    provisional_deco = TpLinkDecoClient(DECO_MAC)
    clients = {DECO_MAC: provisional_deco, CLIENT_MAC: known_client}
    restored_deco = TpLinkDecoData()
    discovered_deco = TpLinkDeco(DECO_MAC)
    updated_decos = TpLinkDecoData(discovered_deco, {DECO_MAC: discovered_deco})
    events: list[str] = []
    deco_coordinator = MagicMock()
    deco_coordinator.data = restored_deco

    async def _refresh_decos() -> None:
        """Publish a newly confirmed Deco before client initialization."""
        events.append("deco_first_refresh")
        deco_coordinator.data = updated_decos

    deco_coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=_refresh_decos
    )
    client_coordinator = MagicMock()
    client_coordinator.async_config_entry_first_refresh = AsyncMock()

    def _create_client_coordinator(*args: object) -> MagicMock:
        """Capture the reconciled client dictionary before its first poll."""
        assert events == ["deco_first_refresh"]
        assert args[-1] is clients
        assert clients == {CLIENT_MAC: known_client}
        events.append("client_coordinator_created")
        return client_coordinator

    with (
        patch("custom_components.tplink_deco.async_get_clientsession"),
        patch("custom_components.tplink_deco.TplinkDecoApi"),
        patch(
            "custom_components.tplink_deco.TplinkDecoUpdateCoordinator",
            return_value=deco_coordinator,
        ),
        patch(
            "custom_components.tplink_deco.TplinkDecoClientUpdateCoordinator",
            side_effect=_create_client_coordinator,
        ),
    ):
        result = await async_create_and_refresh_coordinators(
            hass=MagicMock(),
            config_data={},
            config_entry=SimpleNamespace(entry_id="mesh-one"),
            deco_data=restored_deco,
            client_data=clients,
        )

    assert result["decos"] is deco_coordinator
    assert result["clients"] is client_coordinator
    assert events == ["deco_first_refresh", "client_coordinator_created"]
    # The client request is deferred until entry platforms are ready.
    client_coordinator.async_config_entry_first_refresh.assert_not_awaited()
    assert restored_deco.decos == {}
    assert deco_coordinator.data is updated_decos


@pytest.mark.asyncio
async def test_failed_device_refresh_does_not_prune_restored_clients() -> None:
    """Keep provisional clients untouched when the initial Deco query fails."""
    restored_client = TpLinkDecoClient(CLIENT_MAC)
    client_data = {CLIENT_MAC: restored_client}
    deco_coordinator = MagicMock()
    deco_coordinator.data = TpLinkDecoData()
    deco_coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=RuntimeError("device discovery failed")
    )

    with (
        patch("custom_components.tplink_deco.async_get_clientsession"),
        patch("custom_components.tplink_deco.TplinkDecoApi"),
        patch(
            "custom_components.tplink_deco.TplinkDecoUpdateCoordinator",
            return_value=deco_coordinator,
        ),
        patch(
            "custom_components.tplink_deco.TplinkDecoClientUpdateCoordinator"
        ) as client_constructor,
    ):
        with pytest.raises(RuntimeError, match="device discovery failed"):
            await async_create_and_refresh_coordinators(
                hass=MagicMock(),
                config_data={},
                config_entry=SimpleNamespace(entry_id="mesh-one"),
                deco_data=deco_coordinator.data,
                client_data=client_data,
            )

    assert client_data == {CLIENT_MAC: restored_client}
    client_constructor.assert_not_called()
