"""Tests for the Deco polling switch."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from custom_components.tplink_deco.switch import DecoPollingSwitch
from custom_components.tplink_deco.switch import LEGACY_POLLING_UNIQUE_ID
from custom_components.tplink_deco.switch import _migrate_polling_switch_unique_id
from custom_components.tplink_deco.switch import polling_unique_id


def _config_entry(entry_id: str):
    return SimpleNamespace(entry_id=entry_id)


def test_polling_switch_unique_id_is_scoped_to_config_entry():
    first = DecoPollingSwitch(SimpleNamespace(config_entry=_config_entry("first")))
    second = DecoPollingSwitch(SimpleNamespace(config_entry=_config_entry("second")))

    assert first.unique_id == polling_unique_id("first")
    assert second.unique_id == polling_unique_id("second")
    assert first.unique_id != second.unique_id


def test_migrate_legacy_polling_switch_preserves_entity_id():
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "switch.polling"
    registry.async_get.return_value = SimpleNamespace(config_entry_id="first")

    with patch(
        "custom_components.tplink_deco.switch.er.async_get", return_value=registry
    ):
        _migrate_polling_switch_unique_id(MagicMock(), _config_entry("first"))

    registry.async_get_entity_id.assert_called_once_with(
        "switch", "tplink_deco", LEGACY_POLLING_UNIQUE_ID
    )
    registry.async_update_entity.assert_called_once_with(
        "switch.polling", new_unique_id=polling_unique_id("first")
    )


def test_migrate_legacy_polling_switch_ignores_other_config_entry():
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "switch.polling"
    registry.async_get.return_value = SimpleNamespace(config_entry_id="first")

    with patch(
        "custom_components.tplink_deco.switch.er.async_get", return_value=registry
    ):
        _migrate_polling_switch_unique_id(MagicMock(), _config_entry("second"))

    registry.async_update_entity.assert_not_called()


def test_migrate_polling_switch_without_legacy_entry_is_noop():
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None

    with patch(
        "custom_components.tplink_deco.switch.er.async_get", return_value=registry
    ):
        _migrate_polling_switch_unique_id(MagicMock(), _config_entry("first"))

    registry.async_get.assert_not_called()
    registry.async_update_entity.assert_not_called()
