"""Tests for private, multi-entry manual log-download service behavior."""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from pathlib import Path
from types import SimpleNamespace
from types import TracebackType
from typing import Any
from typing import TextIO
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
import pytest
import voluptuous as vol

from custom_components.tplink_deco import async_setup
from custom_components.tplink_deco import services as log_services
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SERVICE_DOWNLOAD_SYSTEM_LOG
from custom_components.tplink_deco.exceptions import EmptyDataException
from custom_components.tplink_deco.exceptions import ForbiddenException
from custom_components.tplink_deco.exceptions import LoginForbiddenException
from custom_components.tplink_deco.exceptions import LoginInvalidException
from custom_components.tplink_deco.exceptions import TimeoutException
from custom_components.tplink_deco.exceptions import TransientConnectionException
from custom_components.tplink_deco.services import _log_filename
from custom_components.tplink_deco.system_log import SystemLogLevel


class FakeServices:
    """Store registered service handlers without a Home Assistant instance."""

    def __init__(self) -> None:
        """Initialize a minimal service handler registry."""
        self.handlers: dict[tuple[str, str], tuple[Any, Any]] = {}

    def async_register(
        self,
        domain: str,
        service: str,
        handler: Any,
        *,
        schema: Any,
        supports_response: Any,
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
    hass.data[DOMAIN]["first"][
        COORDINATOR_DECOS_KEY
    ].api.async_get_system_log.assert_not_awaited()
    hass.data[DOMAIN]["second"][
        COORDINATOR_DECOS_KEY
    ].api.async_get_system_log.assert_awaited_once_with(SystemLogLevel.WARNING)


@pytest.mark.asyncio
async def test_single_loaded_entry_is_selected_without_identifier(
    tmp_path: Path,
) -> None:
    """Automatically choose the only loaded entry."""
    hass = _hass(tmp_path)
    hass.config_entries.entries["second"].state = ConfigEntryState.NOT_LOADED
    await async_setup(hass, {})

    await _download(hass, filename="one.log")
    hass.data[DOMAIN]["first"][
        COORDINATOR_DECOS_KEY
    ].api.async_get_system_log.assert_awaited_once_with(SystemLogLevel.ALL)


@pytest.mark.asyncio
async def test_ambiguous_entry_requires_config_entry_id(tmp_path: Path) -> None:
    """Reject an action that could download from the wrong Deco."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError, match="config_entry_id"):
        await _download(hass)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_id", ["absent", "unrelated"])
async def test_rejects_incorrect_config_entry(tmp_path: Path, entry_id: str) -> None:
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
    [
        "../secret.log",
        "folder/secret.log",
        r"folder\secret.log",
        "CON.log",
        ".hidden.log",
        "evil.txt",
        "secret.log/..",
        "a" * 130 + ".log",
        "bad\x00.log",
    ],
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
    hass.data[DOMAIN]["first"][
        COORDINATOR_DECOS_KEY
    ].api.async_get_system_log.assert_not_awaited()


class _FailingLogWriter:
    """Simulate failure after a new file has already been created."""

    def __init__(self, stream: TextIO, failure_point: str) -> None:
        """Wrap a real file and preserve its close behavior."""
        self._stream = stream
        self._failure_point = failure_point

    def __enter__(self) -> "_FailingLogWriter":
        """Enter the underlying file context."""
        self._stream.__enter__()
        return self

    def write(self, data: str) -> None:
        """Write some data, then fail when testing a partial write."""
        self._stream.write(data[:7])
        if self._failure_point == "write":
            raise OSError("synthetic private write error")
        if self._failure_point == "encoding":
            raise UnicodeEncodeError(
                "utf-8", "PRIVATE_ROUTER_VALUE", 0, 1, "PRIVATE_ROUTER_REASON"
            )

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Close the underlying stream, optionally simulating close failure."""
        result = self._stream.__exit__(exception_type, exception, traceback)
        if self._failure_point == "close":
            raise OSError("synthetic private close error")
        return result


@pytest.mark.asyncio
async def test_rejects_symbolic_link_export_directory(tmp_path: Path) -> None:
    """Do not leak sensitive router logs into a web-served symlink target."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    public_folder = tmp_path / "www"
    public_folder.mkdir()
    export_directory = tmp_path / "tplink_deco_logs"
    try:
        export_directory.symlink_to(public_folder, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links unavailable on this test platform")

    with pytest.raises(ServiceValidationError, match="storage is inaccessible"):
        await _download(hass, config_entry_id="first", filename="secret.log")

    assert export_directory.is_symlink()
    assert not (public_folder / "secret.log").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["write", "close", "encoding"])
async def test_write_failure_removes_partial_file_and_allows_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """Remove only this attempt's incomplete export on write/close errors."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    export = tmp_path / "tplink_deco_logs" / "retry.log"
    original_fdopen = os.fdopen

    def _failing_fdopen(
        descriptor: int, *args: Any, **kwargs: Any
    ) -> _FailingLogWriter:
        """Wrap a real file so a write or close fails after file creation."""
        stream = original_fdopen(descriptor, *args, **kwargs)
        return _FailingLogWriter(stream, failure_point)

    with monkeypatch.context() as scoped:
        scoped.setattr(log_services.os, "fdopen", _failing_fdopen)
        with pytest.raises(
            ServiceValidationError, match="storage is inaccessible"
        ) as failure:
            await _download(hass, config_entry_id="first", filename="retry.log")
        assert failure.value.__cause__ is None
        assert failure.value.__context__ is None
        assert "PRIVATE_ROUTER_" not in "".join(
            traceback.format_exception(failure.value)
        )

    assert not export.exists()
    response = await _download(hass, config_entry_id="first", filename="retry.log")
    assert response["path"] == str(export)
    assert export.read_text(encoding="utf-8") == "first\n"

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_exception", "message"),
    [
        (EmptyDataException("PRIVATE_ROUTER_TOKEN"), "authentication failed"),
        (ForbiddenException("PRIVATE_ROUTER_TOKEN"), "authentication failed"),
        (LoginForbiddenException("PRIVATE_ROUTER_TOKEN"), "authentication failed"),
        (LoginInvalidException("PRIVATE_ROUTER_TOKEN"), "authentication failed"),
        (TimeoutException("PRIVATE_ROUTER_TOKEN"), "timed out"),
        (TransientConnectionException("PRIVATE_ROUTER_TOKEN"), "interrupted"),
        (RuntimeError("PRIVATE_ROUTER_TOKEN"), "download failed"),
    ],
)
async def test_api_errors_are_classified_without_leaking_router_data(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    api_exception: Exception,
    message: str,
) -> None:
    """Expose only fixed service errors with no private exception context."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    api = hass.data[DOMAIN]["first"][COORDINATOR_DECOS_KEY].api
    api.async_get_system_log.side_effect = api_exception

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ServiceValidationError, match=message) as failure:
            await _download(hass, config_entry_id="first", filename="secret.log")

    assert failure.value.__context__ is None
    assert failure.value.__cause__ is None
    assert "PRIVATE_ROUTER_TOKEN" not in "".join(
        traceback.format_exception(failure.value)
    )
    assert "PRIVATE_ROUTER_TOKEN" not in caplog.text
    assert not (tmp_path / "tplink_deco_logs" / "secret.log").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_result", [None, 42, {"content": "PRIVATE_ROUTER_TOKEN"}])
async def test_malformed_api_result_rejected_before_writing(
    tmp_path: Path, invalid_result: Any
) -> None:
    """Reject unexpected API result types with a fixed safe error."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    api = hass.data[DOMAIN]["first"][COORDINATOR_DECOS_KEY].api
    api.async_get_system_log.return_value = invalid_result

    with pytest.raises(ServiceValidationError, match="response is malformed"):
        await _download(hass, config_entry_id="first", filename="secret.log")

    assert not (tmp_path / "tplink_deco_logs" / "secret.log").exists()


@pytest.mark.asyncio
async def test_api_cancellation_is_never_masked(tmp_path: Path) -> None:
    """Propagate cancellation without saving any system log."""
    hass = _hass(tmp_path)
    await async_setup(hass, {})
    api = hass.data[DOMAIN]["first"][COORDINATOR_DECOS_KEY].api
    api.async_get_system_log.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _download(hass, config_entry_id="first", filename="secret.log")

    assert not (tmp_path / "tplink_deco_logs" / "secret.log").exists()
