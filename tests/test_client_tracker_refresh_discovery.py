"""Regressions for client trackers discovered after coordinator data commits."""

from collections.abc import Callable
from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.const import CONF_CLIENT_POSTFIX
from custom_components.tplink_deco.const import CONF_CLIENT_PREFIX
from custom_components.tplink_deco.const import CONF_DECO_POSTFIX
from custom_components.tplink_deco.const import CONF_DECO_PREFIX
from custom_components.tplink_deco.const import CONF_LINK_CLIENT_DEVICES
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SIGNAL_CLIENT_ADDED
from custom_components.tplink_deco.coordinator import TpLinkDecoClient
from custom_components.tplink_deco.coordinator import TpLinkDecoData
from custom_components.tplink_deco.device_tracker import TplinkDecoClientDeviceTracker
from custom_components.tplink_deco.device_tracker import async_setup_entry

FIRST_MAC = "02:00:00:00:01:01"
SECOND_MAC = "02:00:00:00:01:02"
OTHER_ENTRY_MAC = "02:00:00:00:02:01"


def _new_client(mac: str) -> TpLinkDecoClient:
    """Build a discovered client with a stable registry identity."""
    client = TpLinkDecoClient(mac)
    client.name = "Test client"
    client.online = True
    return client


def _registered_clients(add_entities: MagicMock) -> list[TplinkDecoClientDeviceTracker]:
    """Return only client trackers added by the platform."""
    return [
        entity
        for call in add_entities.call_args_list
        for entity in call.args[0]
        if isinstance(entity, TplinkDecoClientDeviceTracker)
    ]


@pytest.mark.asyncio
async def test_client_refresh_discovers_after_commit_without_duplicate_trackers() -> None:
    """Recover from early dispatcher delivery and keep separate meshes isolated."""
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    post_refresh_callbacks: dict[str, Callable[[], None]] = {}
    discovery_callbacks: list[Callable[[], None]] = []
    client_coordinators: dict[str, MagicMock] = {}
    add_callbacks: dict[str, MagicMock] = {}

    def _register_listener(
        listener: Callable[[], None], *, entry_id: str
    ) -> MagicMock:
        """Capture a callback registered for one config entry."""
        post_refresh_callbacks[entry_id] = listener
        return MagicMock()

    def _subscribe_dispatcher(
        target_hass: MagicMock,
        signal: str,
        handler: Callable[[], None],
    ) -> MagicMock:
        """Capture only client-discovery notifications for the test."""
        assert target_hass is hass
        if signal == SIGNAL_CLIENT_ADDED:
            discovery_callbacks.append(handler)
        return MagicMock()

    with patch(
        "custom_components.tplink_deco.device_tracker.async_dispatcher_connect",
        side_effect=_subscribe_dispatcher,
    ):
        for entry_id, link_clients in (("mesh-one", True), ("mesh-two", False)):
            deco_coordinator = MagicMock()
            deco_coordinator.data = TpLinkDecoData()
            client_coordinator = MagicMock()
            client_coordinator.data = {}
            client_coordinator.async_add_listener.side_effect = partial(
                _register_listener, entry_id=entry_id
            )
            client_coordinators[entry_id] = client_coordinator
            hass.data[DOMAIN][entry_id] = {
                COORDINATOR_DECOS_KEY: deco_coordinator,
                COORDINATOR_CLIENTS_KEY: client_coordinator,
            }
            entry = SimpleNamespace(
                entry_id=entry_id,
                data={
                    CONF_CLIENT_PREFIX: "",
                    CONF_CLIENT_POSTFIX: "",
                    CONF_DECO_PREFIX: "",
                    CONF_DECO_POSTFIX: "Deco",
                    CONF_LINK_CLIENT_DEVICES: link_clients,
                },
            )
            add_callbacks[entry_id] = MagicMock()
            await async_setup_entry(hass, entry, add_callbacks[entry_id])

        assert len(discovery_callbacks) == 2
        assert set(post_refresh_callbacks) == {"mesh-one", "mesh-two"}

        # The coordinator currently signals before replacing its old data.
        for callback in discovery_callbacks:
            callback()
        assert all(not _registered_clients(add) for add in add_callbacks.values())

        # The post-update listener must discover clients even with no second signal.
        client_coordinators["mesh-one"].data = {FIRST_MAC: _new_client(FIRST_MAC)}
        post_refresh_callbacks["mesh-one"]()
        first_clients = _registered_clients(add_callbacks["mesh-one"])
        assert [client.unique_id for client in first_clients] == [FIRST_MAC]
        assert first_clients[0].mac_address == FIRST_MAC
        assert not _registered_clients(add_callbacks["mesh-two"])

        # Repeated notifications cannot register the same MAC twice.
        for callback in discovery_callbacks:
            callback()
        post_refresh_callbacks["mesh-one"]()
        assert len(_registered_clients(add_callbacks["mesh-one"])) == 1

        # Subsequent refreshes can discover additional clients independently.
        client_coordinators["mesh-one"].data[SECOND_MAC] = _new_client(SECOND_MAC)
        post_refresh_callbacks["mesh-one"]()
        client_coordinators["mesh-two"].data = {
            OTHER_ENTRY_MAC: _new_client(OTHER_ENTRY_MAC)
        }
        post_refresh_callbacks["mesh-two"]()

        assert [
            client.unique_id for client in _registered_clients(add_callbacks["mesh-one"])
        ] == [FIRST_MAC, SECOND_MAC]
        second_clients = _registered_clients(add_callbacks["mesh-two"])
        assert [client.unique_id for client in second_clients] == [OTHER_ENTRY_MAC]
        assert second_clients[0].mac_address is None

        for callback in discovery_callbacks:
            callback()
        for callback in post_refresh_callbacks.values():
            callback()
        assert len(_registered_clients(add_callbacks["mesh-one"])) == 2
        assert len(_registered_clients(add_callbacks["mesh-two"])) == 1

        # The usual teardown must unsubscribe both client discovery sources.
        for coordinator in client_coordinators.values():
            coordinator.async_add_listener.assert_called_once()
            assert coordinator.on_close.call_count == 2
