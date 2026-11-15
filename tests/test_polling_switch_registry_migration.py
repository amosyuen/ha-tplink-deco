"""Regression tests for config-entry-scoped Deco polling switch unique IDs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.switch import DecoPollingSwitch
from custom_components.tplink_deco.switch import LEGACY_POLLING_UNIQUE_ID
from custom_components.tplink_deco.switch import _migrate_polling_switch_unique_id
from custom_components.tplink_deco.switch import async_setup_entry
from custom_components.tplink_deco.switch import polling_unique_id


def _entry(entry_id: str) -> SimpleNamespace:
    """Return a minimal config entry identified by its Home Assistant ID."""
    return SimpleNamespace(entry_id=entry_id)


def _coordinator(entry_id: str) -> MagicMock:
    """Return a coordinator with a separate entry and polling state."""
    coordinator = MagicMock()
    coordinator.config_entry = _entry(entry_id)
    coordinator.paused = False
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _registry(
    *,
    legacy_entity_id: str | None = "switch.deco_polling",
    owner: str | None = "entry-one",
    scoped_entity_id: str | None = None,
) -> MagicMock:
    """Return a registry that distinguishes old and new unique IDs."""
    registry = MagicMock()
    entity_ids_by_unique_id: dict[str, str] = {}
    if legacy_entity_id is not None:
        entity_ids_by_unique_id[LEGACY_POLLING_UNIQUE_ID] = legacy_entity_id
    if scoped_entity_id is not None:
        entity_ids_by_unique_id[polling_unique_id("entry-one")] = scoped_entity_id

    def _find_entity_id(domain: str, platform: str, unique_id: str) -> str | None:
        """Look up the current ID, including changes made by migration."""
        assert (domain, platform) == ("switch", DOMAIN)
        return entity_ids_by_unique_id.get(unique_id)

    def _update_entity(entity_id: str, *, new_unique_id: str) -> None:
        """Move an existing registry identity without changing its entity ID."""
        previous_unique_id = next(
            unique_id
            for unique_id, registered_entity_id in entity_ids_by_unique_id.items()
            if registered_entity_id == entity_id
        )
        assert new_unique_id not in entity_ids_by_unique_id
        del entity_ids_by_unique_id[previous_unique_id]
        entity_ids_by_unique_id[new_unique_id] = entity_id

    registry.entity_ids_by_unique_id = entity_ids_by_unique_id
    registry.async_get_entity_id.side_effect = _find_entity_id
    registry.async_update_entity.side_effect = _update_entity
    registry.async_get.return_value = (
        SimpleNamespace(config_entry_id=owner) if owner is not None else None
    )
    return registry


def test_unique_ids_distinguish_config_entries_and_preserve_other_switch_details() -> (
    None
):
    """Two Deco entries must never create the same polling switch identity."""
    first = DecoPollingSwitch(_coordinator("entry-one"))
    second = DecoPollingSwitch(_coordinator("entry-two"))

    assert first.unique_id == "tplink_deco_polling_entry-one"
    assert second.unique_id == "tplink_deco_polling_entry-two"
    assert first.unique_id != second.unique_id
    assert first.name == second.name == "Polling"
    assert first.icon == second.icon == "mdi:lan-connect"
    assert first.is_on and second.is_on


def test_legacy_switch_migration_preserves_original_entity_id() -> None:
    """Change registry unique ID in place, without recreating the entity."""
    registry = _registry()
    hass = MagicMock()
    with patch(
        "custom_components.tplink_deco.switch.er.async_get",
        return_value=registry,
    ) as get_registry:
        _migrate_polling_switch_unique_id(hass, _entry("entry-one"))

    get_registry.assert_called_once_with(hass)
    registry.async_get.assert_called_once_with("switch.deco_polling")
    registry.async_update_entity.assert_called_once_with(
        "switch.deco_polling",
        new_unique_id=polling_unique_id("entry-one"),
    )


@pytest.mark.parametrize(
    ("legacy_id", "owner", "entry_id", "scoped_id"),
    [
        (None, "entry-one", "entry-one", None),
        ("switch.deco_polling", None, "entry-one", None),
        ("switch.deco_polling", "entry-one", "entry-two", None),
        ("switch.deco_polling", "entry-one", "entry-one", "switch.already_migrated"),
    ],
)
def test_migration_never_changes_unowned_or_conflicting_entries(
    legacy_id: str | None,
    owner: str | None,
    entry_id: str,
    scoped_id: str | None,
) -> None:
    """Avoid cross-mesh registry changes and duplicate unique IDs."""
    registry = _registry(
        legacy_entity_id=legacy_id,
        owner=owner,
        scoped_entity_id=scoped_id,
    )
    with patch(
        "custom_components.tplink_deco.switch.er.async_get",
        return_value=registry,
    ):
        _migrate_polling_switch_unique_id(MagicMock(), _entry(entry_id))

    registry.async_update_entity.assert_not_called()


def test_reloading_after_migration_is_idempotent() -> None:
    """Do not write to the registry when no legacy unique ID is present."""
    registry = _registry(
        legacy_entity_id=None,
        scoped_entity_id="switch.deco_polling",
    )
    with patch(
        "custom_components.tplink_deco.switch.er.async_get",
        return_value=registry,
    ):
        _migrate_polling_switch_unique_id(MagicMock(), _entry("entry-one"))

    registry.async_update_entity.assert_not_called()


@pytest.mark.asyncio
async def test_setup_migrates_before_registering_new_switch() -> None:
    """Use the scoped ID after migrating the previous registry entry."""
    registry = _registry()
    config_entry = _entry("entry-one")
    coordinator = _coordinator("entry-one")
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-one": {COORDINATOR_DECOS_KEY: coordinator}}}

    def _add_entities(entities: list[DecoPollingSwitch]) -> None:
        """Assert migration completed before entities are forwarded to HA."""
        registry.async_update_entity.assert_called_once()
        assert len(entities) == 1
        assert entities[0].unique_id == polling_unique_id("entry-one")

    with patch(
        "custom_components.tplink_deco.switch.er.async_get",
        return_value=registry,
    ):
        await async_setup_entry(hass, config_entry, _add_entities)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry_order",
    [
        ("entry-two", "entry-one"),
        ("entry-one", "entry-two"),
    ],
)
async def test_multiple_entries_only_migrate_the_owning_entry(
    entry_order: tuple[str, str],
) -> None:
    """Migrate only the owner regardless of which mesh is initialized first."""
    registry = _registry(owner="entry-one")
    hass = MagicMock()
    first = _coordinator("entry-one")
    second = _coordinator("entry-two")
    hass.data = {
        DOMAIN: {
            "entry-one": {COORDINATOR_DECOS_KEY: first},
            "entry-two": {COORDINATOR_DECOS_KEY: second},
        }
    }
    added: list[DecoPollingSwitch] = []

    def _add_entities(entities: list[DecoPollingSwitch]) -> None:
        """Simulate the platform registering its new switch after migration."""
        for entity in entities:
            entry_id = entity.coordinator.config_entry.entry_id
            if registry.async_get_entity_id("switch", DOMAIN, entity.unique_id) is None:
                registry.entity_ids_by_unique_id[entity.unique_id] = (
                    f"switch.deco_polling_{entry_id}"
                )
            added.append(entity)

    with patch(
        "custom_components.tplink_deco.switch.er.async_get",
        return_value=registry,
    ):
        for entry_id in entry_order:
            await async_setup_entry(hass, _entry(entry_id), _add_entities)
            if entry_id == "entry-one":
                # The old identity must immediately disappear when the
                # owning config entry migrates it.
                assert (
                    registry.async_get_entity_id(
                        "switch", DOMAIN, LEGACY_POLLING_UNIQUE_ID
                    )
                    is None
                )
                assert (
                    registry.async_get_entity_id(
                        "switch", DOMAIN, polling_unique_id("entry-one")
                    )
                    == "switch.deco_polling"
                )

    registry.async_update_entity.assert_called_once_with(
        "switch.deco_polling",
        new_unique_id=polling_unique_id("entry-one"),
    )
    assert (
        registry.async_get_entity_id("switch", DOMAIN, LEGACY_POLLING_UNIQUE_ID) is None
    )
    assert (
        registry.async_get_entity_id("switch", DOMAIN, polling_unique_id("entry-one"))
        == "switch.deco_polling"
    )
    assert (
        registry.async_get_entity_id("switch", DOMAIN, polling_unique_id("entry-two"))
        == "switch.deco_polling_entry-two"
    )
    assert [entity.unique_id for entity in added] == [
        polling_unique_id(entry_id) for entry_id in entry_order
    ]


@pytest.mark.asyncio
async def test_polling_switch_on_off_behavior_remains_unchanged() -> None:
    """Preserve pause/resume and explicit refresh behavior after migration."""
    coordinator = _coordinator("entry-one")
    entity = DecoPollingSwitch(coordinator)
    entity.async_write_ha_state = MagicMock()

    await entity.async_turn_off()
    assert coordinator.paused is True
    assert entity.is_on is False
    coordinator.async_request_refresh.assert_not_awaited()

    await entity.async_turn_on()
    assert coordinator.paused is False
    assert entity.is_on is True
    coordinator.async_request_refresh.assert_awaited_once()
    assert entity.async_write_ha_state.call_count == 2
