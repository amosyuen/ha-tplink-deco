"""Regression tests for the manual Deco plain-text system-log API."""

import asyncio
import gzip
import io
import logging
from pathlib import Path
import tarfile
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.tplink_deco import api as api_module
from custom_components.tplink_deco.api import SYSTEM_LOG_CONTEXT
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.exceptions import ForbiddenException
from custom_components.tplink_deco.exceptions import TransientConnectionException
from custom_components.tplink_deco.exceptions import UnexpectedApiException
from custom_components.tplink_deco.system_log import MAX_SYSTEM_LOG_ARCHIVE_MEMBERS
from custom_components.tplink_deco.system_log import MAX_SYSTEM_LOG_BYTES
from custom_components.tplink_deco.system_log import SystemLogLevel
from custom_components.tplink_deco.system_log import decode_system_log

SECRET = "PRIVATE_ROUTER_TOKEN_123"


def _api_and_session() -> tuple[TplinkDecoApi, MagicMock]:
    """Create an authenticated API with a mocked HTTP session."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post = AsyncMock()
    api = TplinkDecoApi(
        session=session,
        host="https://192.0.2.1",
        username="example",
        password="synthetic-secret",
        verify_ssl=True,
    )
    api._stok = SECRET
    api._cookie = "sysauth=PRIVATE_COOKIE"
    api._seq = 4
    api._encode_payload = MagicMock(return_value="encoded-data")
    api._async_post = AsyncMock(return_value={"data": "encrypted-placeholder"})
    api._decrypt_data = MagicMock(return_value={"error_code": 0})
    return api, session


def _response(
    body: bytes = b"first line\nsecond line\n",
    *,
    content_type: str = "text/plain",
    status: int = 200,
) -> MagicMock:
    """Return a simulated aiohttp response with bounded content reading."""
    response = MagicMock()
    response.content_type = content_type
    response.status = status
    response.history = ()
    response.content.read = AsyncMock(
        side_effect=[
            body[index : index + 65536] for index in range(0, len(body), 65536)
        ]
        + [b""]
    )
    response.release = MagicMock()
    response.raise_for_status = MagicMock()
    if status >= 400:
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=SimpleNamespace(real_url=f"https://router/;stok={SECRET}"),
            history=(),
            status=status,
            message=SECRET,
        )
    return response


@pytest.mark.asyncio
async def test_build_then_save_once_at_selected_level() -> None:
    """Build a filtered snapshot, then read its plain-text bytes one time."""
    api, session = _api_and_session()
    session.post.return_value = _response()

    result = await api.async_get_system_log(SystemLogLevel.WARNING)

    assert result == "first line\nsecond line\n"
    api._async_post.assert_awaited_once()
    assert api._async_post.await_args.args[0] == SYSTEM_LOG_CONTEXT
    assert api._async_post.await_args.kwargs["params"] == {"form": "feedback_log"}
    api._encode_payload.assert_called_once_with(
        {"operation": "build", "params": {"level": 4}}
    )
    assert session.post.await_args.kwargs["params"] == {"form": "save_log"}
    assert session.post.await_args.kwargs["cookies"] == {"sysauth": "PRIVATE_COOKIE"}
    assert session.post.return_value.content.read.await_count == 2
    session.post.return_value.content.read.assert_any_await(65536)
    session.post.return_value.release.assert_called_once()


@pytest.mark.asyncio
async def test_save_403_reauthenticates_once_with_fresh_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stale save token triggers one bounded rebuild and no secret logging."""
    api, session = _api_and_session()
    session.post.side_effect = [_response(status=403), _response(b"ok\n")]

    async def _login() -> None:
        """Provide a fresh synthetic login after invalidation."""
        api._stok = "new-token"
        api._cookie = "sysauth=new-cookie"
        api._seq = 3

    api.async_login = AsyncMock(side_effect=_login)
    with caplog.at_level(logging.DEBUG):
        result = await api.async_get_system_log()

    assert result == "ok\n"
    assert session.post.await_count == 2
    assert api._async_post.await_count == 2
    api.async_login.assert_awaited_once()
    assert SECRET not in caplog.text
    assert "PRIVATE_COOKIE" not in caplog.text


@pytest.mark.asyncio
async def test_repeated_403_stops_after_one_reauthentication() -> None:
    """Do not retry an expired log session without a finite limit."""
    api, session = _api_and_session()
    session.post.side_effect = [_response(status=403), _response(status=403)]

    async def _login() -> None:
        """Supply a second token for the one permitted retry."""
        api._stok = "fresh"
        api._cookie = "sysauth=fresh"
        api._seq = 3

    api.async_login = AsyncMock(side_effect=_login)
    with pytest.raises(ForbiddenException, match="System log authentication expired"):
        await api.async_get_system_log()

    assert session.post.await_count == 2
    api.async_login.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_json_response_reauthenticates_once() -> None:
    """Treat firmware timeout from save_log as an auth-expiry signal."""
    api, session = _api_and_session()
    session.post.side_effect = [
        _response(b'{"errorcode": "timeout"}', content_type="application/json"),
        _response(b"success\n"),
    ]

    async def _login() -> None:
        """Restore a fresh synthetic session."""
        api._stok = "fresh"
        api._cookie = "sysauth=fresh"
        api._seq = 3

    api.async_login = AsyncMock(side_effect=_login)
    assert await api.async_get_system_log() == "success\n"
    assert session.post.await_count == 2
    api.async_login.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response(b"bad", content_type="application/octet-stream"), "unsupported"),
        (_response(b"not-json", content_type="application/json"), "malformed"),
        (_response(b"\x1f\x8bcompressed"), "gzip snapshot is malformed"),
        (_response(b"\x00" * 257 + b"ustar" + b"\x00"), "tar snapshot is malformed"),
        (_response(b"\xff\xfe"), "encoding"),
        (_response(b"Z" * (MAX_SYSTEM_LOG_BYTES + 1)), "size limit"),
        (
            _response(b'{"errorcode": "-42"}', content_type="application/json"),
            "rejected",
        ),
        (_response(status=502), "HTTP request failed"),
    ],
)
async def test_rejects_bad_save_responses_without_raw_data(
    response: MagicMock, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Reject unsupported, malformed, oversized and HTTP error responses."""
    api, session = _api_and_session()
    session.post.return_value = response

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException, match=message) as caught:
            await api.async_get_system_log()

    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text
    response.release.assert_called_once()


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    """Never convert cancellation into a router or service error."""
    api, session = _api_and_session()
    session.post.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await api.async_get_system_log()


@pytest.mark.asyncio
async def test_log_build_http_error_does_not_log_authenticated_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exercise the bound shared HTTP method, not a mocked build method."""
    api, session = _api_and_session()
    api._async_post = TplinkDecoApi._async_post.__get__(api)
    session.post.return_value = _response(status=503)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException, match="System log HTTP") as caught:
            await api._async_post(
                SYSTEM_LOG_CONTEXT,
                api._log_export_url(),
                params={"form": "feedback_log"},
                data="encoded",
            )

    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_log_build_decrypt_failure_does_not_log_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed private log-build ciphertext cannot enter DEBUG logs."""
    api, _session = _api_and_session()
    api._decrypt_data = TplinkDecoApi._decrypt_data.__get__(api)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException, match="System log response"):
            api._decrypt_data(SYSTEM_LOG_CONTEXT, "PRIVATE_CIPHERTEXT")

    assert "PRIVATE_CIPHERTEXT" not in caplog.text


def _tar_snapshot(
    *members: tuple[str, bytes],
    symlink_name: str | None = None,
) -> bytes:
    """Build an in-memory tar fixture with optional unsafe link metadata."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        if symlink_name is not None:
            link = tarfile.TarInfo(symlink_name)
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            archive.addfile(link)
        for name, content in members:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (b"normal\n", "normal\n"),
        (gzip.compress(b"gzip\n"), "gzip\n"),
        (_tar_snapshot(("./syslog.log", b"tar\n")), "tar\n"),
        (
            gzip.compress(_tar_snapshot(("nested/syslog.log", b"nested\n"))),
            "nested\n",
        ),
        (
            _tar_snapshot(("other.log", b"other"), ("logs/syslog.log", b"selected")),
            "selected",
        ),
        (
            _tar_snapshot(("first.log", b"first"), ("second.log", b"second")),
            "first",
        ),
        (
            _tar_snapshot(("safe.log", b"safe"), symlink_name="syslog.log"),
            "safe",
        ),
        (_tar_snapshot(symlink_name="syslog.log"), ""),
        (_tar_snapshot(), ""),
        (gzip.compress(_tar_snapshot()), ""),
        (_tar_snapshot(("syslog.log", b"")), ""),
    ],
)
async def test_decodes_supported_snapshot_formats(
    snapshot: bytes, expected: str
) -> None:
    """Return only the selected text without changing router authentication."""
    api, session = _api_and_session()
    session.post.return_value = _response(snapshot)

    assert await api.async_get_system_log() == expected
    api._async_post.assert_awaited_once()
    session.post.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type",
    ["application/gzip", "application/x-gzip", "application/octet-stream"],
)
async def test_accepts_gzip_even_with_non_text_content_type(
    content_type: str,
) -> None:
    """Recognize compressed firmware snapshots without a text MIME type."""
    api, session = _api_and_session()
    session.post.return_value = _response(
        gzip.compress(b"alternate mime\n"), content_type=content_type
    )

    assert await api.async_get_system_log() == "alternate mime\n"


@pytest.mark.asyncio
async def test_decoding_does_not_block_event_loop() -> None:
    """Offload both archive parsing and inflation to a worker thread."""
    api, session = _api_and_session()
    session.post.return_value = _response(gzip.compress(b"thread\n"))

    def _check_thread(body: bytes) -> str:
        """Assert this parser executes outside the running event loop."""
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        return decode_system_log(body)

    with patch.object(
        api_module, "decode_system_log", side_effect=_check_thread
    ) as decoder:
        assert await api.async_get_system_log() == "thread\n"
    decoder.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("snapshot", "error"),
    [
        (gzip.compress(b"A" * (MAX_SYSTEM_LOG_BYTES + 1)), "size limit"),
        (gzip.compress(b"broken\n")[:-5], "gzip snapshot is malformed"),
        (b"\x1f\x8bnot-gzip", "gzip snapshot is malformed"),
        (gzip.compress(b"bad\xff"), "encoding is unsupported"),
        (_tar_snapshot(("syslog.log", b"\xff")), "encoding is unsupported"),
        (_tar_snapshot(("syslog.log", b"binary\x00value")), "binary data"),
        (
            _tar_snapshot(
                ("other.log", b"ok"), ("syslog.log", b"A" * (MAX_SYSTEM_LOG_BYTES + 1))
            ),
            "size limit",
        ),
    ],
)
async def test_rejects_corrupt_or_expanding_snapshots_without_auth_retry(
    snapshot: bytes,
    error: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject bad or expanding archives with fixed, secret-free errors."""
    api, session = _api_and_session()
    session.post.return_value = _response(snapshot)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(UnexpectedApiException, match=error) as caught:
            await api.async_get_system_log()
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text
    assert session.post.await_count == 1


def test_rejects_archives_with_excessive_members() -> None:
    """Cap tar metadata scanning independently of compressed transfer size."""
    members = tuple(
        (f"log-{index}", b"") for index in range(MAX_SYSTEM_LOG_ARCHIVE_MEMBERS + 1)
    )
    snapshot = _tar_snapshot(*members)
    with pytest.raises(UnexpectedApiException, match="too many members"):
        decode_system_log(snapshot)


def test_truncated_member_is_rejected_without_partial_log() -> None:
    """Reject tar headers claiming a larger file than available bytes."""
    snapshot = _tar_snapshot(("syslog.log", b"record\n"))
    incomplete = snapshot[: 512 + 3]
    with pytest.raises(UnexpectedApiException, match="incomplete|malformed"):
        decode_system_log(incomplete)


def test_tar_does_not_extract_files_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid disk writes even when archive member names contain traversal."""
    monkeypatch.chdir(tmp_path)
    snapshot = _tar_snapshot(("../private/syslog.log", b"safe\n"))
    assert decode_system_log(snapshot) == "safe\n"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_bad_binary_mime_is_not_treated_as_plain_text() -> None:
    """Reject arbitrary non-archive octet-stream responses."""
    api, session = _api_and_session()
    session.post.return_value = _response(
        b"not a snapshot", content_type="application/octet-stream"
    )
    with pytest.raises(UnexpectedApiException, match="content type is unsupported"):
        await api.async_get_system_log()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "error_response"),
    [
        ("text/plain", b'{"errorcode":"timeout"}'),
        ("application/octet-stream", b'{"error_code":-5002}'),
    ],
)
async def test_mislabeled_firmware_auth_error_reauthenticates_once(
    content_type: str,
    error_response: bytes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not export firmware auth-error JSON as ordinary log content."""
    api, session = _api_and_session()
    session.post.side_effect = [
        _response(error_response, content_type=content_type),
        _response(b"recovered\n"),
    ]

    async def _login() -> None:
        """Restore a synthetic session for exactly one retry."""
        api._stok = "fresh-session"
        api._cookie = "sysauth=fresh-cookie"
        api._seq = 3

    api.async_login = AsyncMock(side_effect=_login)
    with caplog.at_level(logging.DEBUG):
        assert await api.async_get_system_log() == "recovered\n"

    assert session.post.await_count == 2
    assert api._async_post.await_count == 2
    api.async_login.assert_awaited_once()
    assert SECRET not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["text/plain", "application/octet-stream"])
async def test_mislabeled_firmware_non_auth_error_is_rejected(
    content_type: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Reject firmware error JSON without exposing raw router information."""
    api, session = _api_and_session()
    session.post.return_value = _response(
        b'{"errorcode":123,"detail":"PRIVATE_ROUTER_TOKEN_123"}',
        content_type=content_type,
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(
            UnexpectedApiException, match="download was rejected"
        ) as caught:
            await api.async_get_system_log()

    assert api._async_post.await_count == 1
    assert session.post.await_count == 1
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_malformed_mislabeled_firmware_error_is_not_written() -> None:
    """A truncated firmware error object is malformed, not valid log text."""
    api, session = _api_and_session()
    session.post.return_value = _response(
        b'{"errorcode":"timeout",',
        content_type="text/plain",
    )
    with pytest.raises(UnexpectedApiException, match="response is malformed"):
        await api.async_get_system_log()
    assert session.post.await_count == 1


@pytest.mark.asyncio
async def test_valid_json_log_line_without_errorcode_is_preserved() -> None:
    """Normal JSON-formatted log text remains available as a system log."""
    api, session = _api_and_session()
    source = b'{"event":"router-restarted"}\n'
    session.post.return_value = _response(source, content_type="text/plain")
    assert await api.async_get_system_log() == source.decode("utf-8")


@pytest.mark.asyncio
async def test_manual_system_log_incomplete_response_does_not_retry() -> None:
    """Avoid rebuilding the expensive manual snapshot after truncated transport."""
    api, session = _api_and_session()
    api._timeout_error_retries = 3
    response = _response()
    response.content.read.side_effect = aiohttp.ClientPayloadError(
        "PRIVATE_ROUTER_TOKEN_123"
    )
    session.post.return_value = response
    with pytest.raises(TransientConnectionException, match="incomplete"):
        await api.async_get_system_log()

    assert api._async_post.await_count == 1
    assert session.post.await_count == 1
    response.release.assert_called_once()


@pytest.mark.asyncio
async def test_normal_api_transient_retries_remain_backward_compatible() -> None:
    """Keep the default transient retry policy for non-log API operations."""
    api, _session = _api_and_session()
    api._timeout_error_retries = 1
    request = AsyncMock(
        side_effect=[TransientConnectionException("temporary"), "restored"]
    )

    assert await api._async_call_with_retry(request) == "restored"
    assert request.await_count == 2
