"""Tests for private, multi-entry manual log-download service behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
import pytest
import voluptuous as vol

from custom_components.tplink_deco import async_setup
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SERVICE_DOWNLOAD_SYSTEM_LOG
from custom_components.tplink_deco.services import _log_filename
from custom_components.tplink_deco.system_log import SystemLogLevel


class FakeServices:
    """Store registered service handlers without a Home Assistant instance."""

    def __init__(self) -> None:
        """Initialize a minimal service handler registry."""
        self.handlers: dict[tuple[str, str], tuple[Any, Any]] = {}

    def async_register(
        self, domain: str, service: str, handler: Any, *, schema: Any,
        supports_response: Any
    ) -> None:
        """Register a service with schema validation."""
        self.handlers[(domain, service)] = (handler, schema)

    async def async_call(self, domain: str, service: str, data: dict) -> dict:
        """Dispatch a validated service call."""
        handler, schema = self.handlers[(domain, service)]
        return await handler(SimpleNamespace(data=schema(data)))


class FakeConfigEntries:
    """Return Home Assistant-like config-entry objects by ID and domain."""

    def __init__(self, entries: list[SimpleNamespace]) -> None:
        """Index the fake config entries."""
        self.entries = {entry.entry_id: entry for entry in entries}

    def async_entries(self, domain: str) -> list[SimpleNamespace]:
        """Find entries belonging to one integration domain."""
        return [entry for entry in self.entries.values() if entry.domain == domain]

    def async_get_entry(self, entry_id: str) -> SimpleNamespace | None:
        """Return an entry by ID or None."""
        return self.entries.get(entry_id)


def _entry(
    entry_id: str,
    domain: str = DOMAIN,
    state: ConfigEntryState = ConfigEntryState.LOADED,
) -> SimpleNamespace:
    """Make a loaded or unloaded config entry."""
    return SimpleNamespace(entry_id=entry_id, domain=domain, state=state)


def _hass(tmp_path: Path) -> SimpleNamespace:
    """Create a fake Home Assistant with isolated entries and private storage."""
    api_first = MagicMock()
    api_first.async_get_system_log = AsyncMock(return_value="first\n")
    api_second = MagicMock()
    api_second.async_get_system_log = AsyncMock(return_value="second\nlast\n")

    async def _execute(target: Any, *args: Any) -> Any:
        """Run a deterministic file-writing job during testing."""
        return target(*args)

    return SimpleNamespace(
        data={
            DOMAIN: {
                "first": {COORDINATOR_DECOS_KEY: SimpleNamespace(api=api_first)},
                "second": {COORDINATOR_DECOS_KEY: SimpleNamespace(api=api_second)},
            }
        },
        config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts))),
        config_entries=FakeConfigEntries(
            [_entry("first"), _entry("second"), _entry("unrelated", "hue")]
        ),
        services=FakeServices(),
        async_add_executor_job=_execute,
    )


async def _download(hass: SimpleNamespace, **data: Any) -> dict:
    """Call the registered manual-download action."""
    return await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_SYSTEM_LOG, data)


@pytest.mark.asyncio
async def test_action_is_registered_once_and_selects_correct_entry(
    tmp_path: Path,
) -> None:
    """An explicit entry ID prevents cross-router system-log downloads."""
    hass = _hass(tmp_path)
    assert await async_setup(hass, {}) is True
    assert len(hass.services.handlers) == 1

    response = await _download(
        hass, config_entry_id="second", filename="sample.log", log_level="WARNING"
    )
    path = tmp_path / "tplink_deco_logs" / "sample.log"
    assert response == {"path": str(path), "line_count": 2}
    assert path.read_text(encoding="utf-8") == "second\nlast\n"
    assert path.stat().st_mode & 0o077 == 0
    hass.data[DOMAIN]["first"][COORDINATOR_DECOS_KEY].api.async_get_system_log.assert_not_awaited()
    hass.data[DOMAIN]["second"][COORDINATOR_DECOS_KEY].api.async_get_system_log.assert_awaited_once_with(
        SystemLogLevel.WARNING
    )


@pytest.mark.asyncio
async def test_single_loaded_entry_is_selected_without_identifier(
    tmp_path: Path,
) -> None:
    """Automatically choose the only loaded entry."""
    hass = _hass(tmp_path)
    hass.config_entries.entries["second"].state = ConfigEntryState.NOT_LOADED
    await async_setup(hass, {})

    await _download(hass, filename="one.log")
    hass.data[DOMAIN]["first"][COORDINATOR_DECOS_KEY].api.async_get_system_log.assert_awaited_once_with(
        SystemLogLevel.ALL
    )


@pytest.mark.asyncio
async def test_ambiguous_entry_requires_config_entry_id(tmp_path: Path) -> None:
    """Reject an action that could download from the wrong Deco."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError, match="config_entry_id"):
        await _download(hass)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_id", ["absent", "unrelated"])
async def test_rejects_incorrect_config_entry(
    tmp_path: Path, entry_id: str
) -> None:
    """Reject missing or foreign integration entry IDs."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError, match="not a TP-Link Deco"):
        await _download(hass, config_entry_id=entry_id)


@pytest.mark.asyncio
async def test_rejects_unloaded_entry(tmp_path: Path) -> None:
    """Do not use cached router API data after config-entry unload."""
    hass = _hass(tmp_path)
    hass.config_entries.entries["first"].state = ConfigEntryState.NOT_LOADED
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await _download(hass, config_entry_id="first")


@pytest.mark.parametrize(
    "filename",
    ["../secret.log", "folder/secret.log", r"folder\secret.log", "CON.log", ".hidden.log",
     "evil.txt", "secret.log/..", "a" * 130 + ".log", "bad\x00.log"],
)
def test_filename_validation_blocks_traversal_and_reserved_names(filename: str) -> None:
    """Reject separators, reserved Windows names and unbounded filenames."""
    with pytest.raises(ServiceValidationError, match="filename"):
        _log_filename(filename)


@pytest.mark.asyncio
async def test_existing_file_is_not_overwritten(tmp_path: Path) -> None:
    """Preserve a previous export on filename collision."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    original = tmp_path / "tplink_deco_logs" / "existing.log"
    original.parent.mkdir()
    original.write_text("existing secret", encoding="utf-8")

    with pytest.raises(ServiceValidationError, match="already exists"):
        await _download(hass, config_entry_id="first", filename="existing.log")

    assert original.read_text(encoding="utf-8") == "existing secret"


@pytest.mark.asyncio
async def test_rejects_invalid_log_level_before_router_request(
    tmp_path: Path,
) -> None:
    """Apply strict selector validation before any sensitive API calls."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    with pytest.raises(vol.Invalid):
        await _download(
            hass, config_entry_id="first", filename="test.log", log_level="BROKEN"
        )
    hass.data[DOMAIN]["first"][COORDINATOR_DECOS_KEY].api.async_get_system_log.assert_not_awaited()
