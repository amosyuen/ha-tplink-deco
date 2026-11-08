"""Tests for the download_system_log action across config entries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
import pytest
import pytest_asyncio

from custom_components.tplink_deco import async_setup
from custom_components.tplink_deco import async_unload_entry
from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SERVICE_DOWNLOAD_SYSTEM_LOG
from custom_components.tplink_deco.system_log import SystemLogLevel


class FakeServices:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, service, handler, schema, supports_response):
        self.handlers[(domain, service)] = (handler, schema)

    def async_remove(self, domain, service):
        self.handlers.pop((domain, service), None)

    def has_service(self, domain, service):
        return (domain, service) in self.handlers

    async def async_call(self, domain, service, data):
        handler, schema = self.handlers[(domain, service)]
        return await handler(SimpleNamespace(data=schema(data)))


class FakeConfigEntries:
    def __init__(self, entries):
        self.entries = {entry.entry_id: entry for entry in entries}
        self.async_forward_entry_unload = AsyncMock(return_value=True)

    def async_entries(self, domain):
        return [entry for entry in self.entries.values() if entry.domain == domain]

    def async_get_entry(self, entry_id):
        return self.entries.get(entry_id)


def _entry(entry_id, domain=DOMAIN, state=ConfigEntryState.LOADED):
    return SimpleNamespace(
        entry_id=entry_id, domain=domain, state=state, title=entry_id.title()
    )


def _entry_data(lines):
    api = MagicMock()
    api.async_get_system_log = AsyncMock(
        return_value="".join(f"{line}\n" for line in lines)
    )
    api.async_logout = AsyncMock()
    deco_coordinator = MagicMock(
        api=api,
        async_close=AsyncMock(),
        async_shutdown=AsyncMock(),
    )
    clients_coordinator = MagicMock(
        async_close=AsyncMock(),
        async_shutdown=AsyncMock(),
    )
    return {
        COORDINATOR_DECOS_KEY: deco_coordinator,
        COORDINATOR_CLIENTS_KEY: clients_coordinator,
    }


async def _run_executor_job(target, *args):
    return target(*args)


@pytest_asyncio.fixture
async def hass(tmp_path):
    entries = [_entry("first"), _entry("second"), _entry("other", domain="hue")]
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                "first": _entry_data(["first log"]),
                "second": _entry_data(["second log", "more"]),
            }
        },
        config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts))),
        config_entries=FakeConfigEntries(entries),
        services=FakeServices(),
        async_add_executor_job=_run_executor_job,
    )
    assert await async_setup(hass, {}) is True
    return hass


def _api(hass, entry_id):
    return hass.data[DOMAIN][entry_id][COORDINATOR_DECOS_KEY].api


async def _download(hass, **data):
    return await hass.services.async_call(DOMAIN, SERVICE_DOWNLOAD_SYSTEM_LOG, data)


async def _unload(hass, entry_id):
    entry = hass.config_entries.entries[entry_id]
    assert await async_unload_entry(hass, entry) is True
    entry.state = ConfigEntryState.NOT_LOADED


@pytest.mark.asyncio
async def test_targets_selected_entry_when_two_are_loaded(hass, tmp_path):
    response = await _download(
        hass, config_entry_id="second", filename="deco.log", log_level="WARNING"
    )

    path = tmp_path / "tplink_deco_logs" / "deco.log"
    assert response == {"path": str(path), "line_count": 2}
    assert path.read_text() == "second log\nmore\n"
    _api(hass, "second").async_get_system_log.assert_awaited_once_with(
        SystemLogLevel.WARNING
    )
    _api(hass, "first").async_get_system_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_defaults_to_all_levels(hass):
    await _download(hass, config_entry_id="first")

    _api(hass, "first").async_get_system_log.assert_awaited_once_with(
        SystemLogLevel.ALL
    )


@pytest.mark.asyncio
async def test_omitted_entry_is_ambiguous_when_two_are_loaded(hass):
    with pytest.raises(ServiceValidationError, match="config_entry_id"):
        await _download(hass)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry_id", "message"),
    [
        ("missing", "not a TP-Link Deco entry"),
        ("other", "not a TP-Link Deco entry"),
    ],
)
async def test_rejects_entry_from_elsewhere(hass, entry_id, message):
    with pytest.raises(ServiceValidationError, match=message):
        await _download(hass, config_entry_id=entry_id)


@pytest.mark.asyncio
async def test_rejects_directory_in_filename(hass):
    with pytest.raises(ServiceValidationError, match="directory"):
        await _download(hass, config_entry_id="first", filename="../deco.log")
    _api(hass, "first").async_get_system_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_survives_unload_of_one_of_two_entries(hass):
    await _unload(hass, "first")

    assert hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD_SYSTEM_LOG)
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await _download(hass, config_entry_id="first")
    response = await _download(hass, filename="deco.log")
    assert response["line_count"] == 2
    _api(hass, "second").async_get_system_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_reports_no_entry_after_last_unload(hass):
    await _unload(hass, "first")
    await _unload(hass, "second")

    assert hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD_SYSTEM_LOG)
    with pytest.raises(ServiceValidationError, match="No TP-Link Deco entry"):
        await _download(hass)
