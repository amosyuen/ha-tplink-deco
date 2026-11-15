"""Regressions for restoring unavailable client trackers across HA releases."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco import _remove_discovered_decos_from_clients
from custom_components.tplink_deco import async_create_and_refresh_coordinators
from custom_components.tplink_deco import async_create_config_data
from custom_components.tplink_deco.const import ATTR_DEVICE_TYPE
from custom_components.tplink_deco.const import DEVICE_TYPE_CLIENT
from custom_components.tplink_deco.const import DEVICE_TYPE_DECO
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData

DECO_MAC = "AA:BB:CC:DD:EE:01"
CLIENT_MAC = "AA:BB:CC:DD:EE:02"
OTHER_CLIENT_MAC = "AA:BB:CC:DD:EE:03"


def _entry(
    mac: str,
    *,
    domain: str = "device_tracker",
    disabled_by: str | None = None,
) -> SimpleNamespace:
    """Represent a registry entity without changing its MAC-based identity."""
    return SimpleNamespace(
        domain=domain,
        disabled_by=disabled_by,
        unique_id=mac,
        entity_id=f"{domain}.{mac.lower().replace(':', '_')}",
        original_name=f"Device {mac[-2:]}",
    )


def _stored_state(
    device_type: str | None = None, *, status: str = "unavailable"
) -> SimpleNamespace:
    """Create stored state with an optional device classification."""
    attributes = {} if device_type is None else {ATTR_DEVICE_TYPE: device_type}
    return SimpleNamespace(
        state=SimpleNamespace(state=status, attributes=attributes)
    )


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
            "custom_components.tplink_deco.entity_registry.async_entries_for_config_entry",
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
async def test_first_deco_refresh_reconciles_clients_before_client_setup() -> None:
    """Discard provisional Deco clients only after confirmed device discovery."""
    known_client = TpLinkDecoClient(CLIENT_MAC)
    provisional_deco = TpLinkDecoClient(DECO_MAC)
    clients = {DECO_MAC: provisional_deco, CLIENT_MAC: known_client}
    restored_deco = TpLinkDecoData()
    discovered_deco = TpLinkDeco(DECO_MAC)
    updated_decos = TpLinkDecoData(
        discovered_deco, {DECO_MAC: discovered_deco}
    )
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
    client_coordinator.async_config_entry_first_refresh.assert_awaited_once()
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
