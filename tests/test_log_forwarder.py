"""Tests for Deco system log download and syslog forwarding."""

from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import SYSLOG_PROTOCOL_TCP
from custom_components.tplink_deco.const import SYSLOG_PROTOCOL_UDP
from custom_components.tplink_deco.log_forwarder import TplinkDecoLogForwarder
from custom_components.tplink_deco.log_forwarder import async_send_syslog
from custom_components.tplink_deco.log_forwarder import format_rfc5424
from custom_components.tplink_deco.log_forwarder import lines_after

NOW = datetime(2026, 10, 15, 21, 0, 0, tzinfo=timezone.utc)


def test_lines_after():
    fetched = ["a", "b", "c", "d", "e"]
    assert lines_after([], fetched) == fetched
    assert lines_after(["b", "c"], fetched) == ["d", "e"]
    assert lines_after(["e"], fetched) == []
    assert lines_after(["x"], fetched) is None


def test_lines_after_partial_overlap_at_start():
    # The oldest anchor lines rolled out of the Deco's buffer
    assert lines_after(["a", "b", "c"], ["b", "c", "d"]) == ["d"]
    assert lines_after(["a", "b", "c"], ["c"]) == []


def test_lines_after_uses_last_occurrence():
    assert lines_after(["a"], ["a", "b", "a", "c"]) == ["c"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "Thu Oct 15 18:19:19 2026 daemon.err udhcpd[14146]: Sending ACK to 10.0.0.19",
            "<27>1 2026-10-15T18:19:19+00:00 10.0.0.1 udhcpd 14146 - - "
            "Sending ACK to 10.0.0.19",
        ),
        (
            "Thu Oct 15 18:19:03 2026 daemon.notice netifd: Interface 'wan' keep: 0",
            "<29>1 2026-10-15T18:19:03+00:00 10.0.0.1 netifd - - - "
            "Interface 'wan' keep: 0",
        ),
        (
            "Thu Oct  1 08:00:00 2026 kern.warn kernel: [ 1.0] usb 1-1: reset",
            "<4>1 2026-10-01T08:00:00+00:00 10.0.0.1 kernel - - - [ 1.0] usb 1-1: reset",
        ),
        (
            "something unexpected",
            "<13>1 2026-10-15T21:00:00+00:00 10.0.0.1 - - - - something unexpected",
        ),
    ],
)
def test_format_rfc5424(line, expected):
    assert format_rfc5424(line, "10.0.0.1", NOW) == expected


@pytest.mark.asyncio
async def test_send_syslog_udp():
    loop = asyncio.get_running_loop()
    received = asyncio.Queue()

    class Server(asyncio.DatagramProtocol):
        def datagram_received(self, data, addr):
            received.put_nowait(data)

    transport, _ = await loop.create_datagram_endpoint(
        Server, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        await async_send_syslog("127.0.0.1", port, SYSLOG_PROTOCOL_UDP, ["one", "two"])
        assert await asyncio.wait_for(received.get(), 5) == b"one"
        assert await asyncio.wait_for(received.get(), 5) == b"two"
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_send_syslog_tcp():
    received = asyncio.get_running_loop().create_future()

    async def handle(reader, writer):
        received.set_result(await reader.read())
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        await async_send_syslog("127.0.0.1", port, SYSLOG_PROTOCOL_TCP, ["one", "two"])
        assert await asyncio.wait_for(received, 5) == b"one\ntwo\n"


def _forwarder(api, stored=None, paused=False):
    store = MagicMock()
    store.async_load = AsyncMock(return_value=stored)
    store.async_save = AsyncMock()
    with patch("custom_components.tplink_deco.log_forwarder.Store", return_value=store):
        forwarder = TplinkDecoLogForwarder(
            MagicMock(),
            api,
            "entry",
            hostname="10.0.0.1",
            syslog_host="syslog.local",
            syslog_port=514,
            syslog_protocol=SYSLOG_PROTOCOL_UDP,
            level=8,
            interval=timedelta(minutes=5),
            is_paused=lambda: paused,
        )
    return forwarder, store


@pytest.fixture
def mock_send():
    with patch(
        "custom_components.tplink_deco.log_forwarder.async_send_syslog",
        new_callable=AsyncMock,
    ) as send:
        yield send


@pytest.fixture
def mock_track():
    with patch(
        "custom_components.tplink_deco.log_forwarder.async_track_time_interval"
    ) as track:
        yield track


def _sent_messages(mock_send):
    return [m.rsplit(" ", 1)[-1] for m in mock_send.call_args.args[3]]


@pytest.mark.asyncio
async def test_forwarder_sends_only_new_lines(mock_send, mock_track):
    api = MagicMock()
    api.async_get_system_log = AsyncMock(return_value=["l1", "l2", "", "l3"])
    forwarder, store = _forwarder(api, stored={"level": 8, "anchor": ["l1"]})
    await forwarder.async_start()

    await forwarder.async_poll()

    assert _sent_messages(mock_send) == ["l2", "l3"]
    store.async_save.assert_awaited_once_with(
        {"level": 8, "anchor": ["l1", "l2", "l3"]}
    )
    assert forwarder.last_forwarded_count == 2

    mock_send.reset_mock()
    api.async_get_system_log.return_value = ["l2", "l3", "l4"]
    await forwarder.async_poll()
    assert _sent_messages(mock_send) == ["l4"]

    mock_send.reset_mock()
    await forwarder.async_poll()
    mock_send.assert_not_awaited()
    assert forwarder.last_forwarded_count == 0

    await forwarder.async_stop()
    mock_track.return_value.assert_called_once()


@pytest.mark.asyncio
async def test_forwarder_sends_everything_without_overlap(mock_send, mock_track):
    api = MagicMock()
    api.async_get_system_log = AsyncMock(return_value=["n1", "n2"])
    forwarder, _ = _forwarder(api, stored={"level": 8, "anchor": ["old"]})
    await forwarder.async_start()

    await forwarder.async_poll()

    assert _sent_messages(mock_send) == ["n1", "n2"]


@pytest.mark.asyncio
async def test_forwarder_ignores_anchor_from_other_level(mock_send, mock_track):
    api = MagicMock()
    api.async_get_system_log = AsyncMock(return_value=["l1", "l2"])
    forwarder, _ = _forwarder(api, stored={"level": 3, "anchor": ["l1"]})
    await forwarder.async_start()

    await forwarder.async_poll()

    assert _sent_messages(mock_send) == ["l1", "l2"]


@pytest.mark.asyncio
async def test_forwarder_retries_lines_after_send_failure(mock_send, mock_track):
    api = MagicMock()
    api.async_get_system_log = AsyncMock(return_value=["l1", "l2"])
    forwarder, store = _forwarder(api)
    await forwarder.async_start()

    mock_send.side_effect = OSError("unreachable")
    await forwarder.async_poll()
    assert forwarder.last_error == "OSError: unreachable"
    store.async_save.assert_not_awaited()

    mock_send.side_effect = None
    await forwarder.async_poll()
    assert _sent_messages(mock_send) == ["l1", "l2"]
    assert forwarder.last_error is None


@pytest.mark.asyncio
async def test_forwarder_skips_when_paused(mock_send, mock_track):
    api = MagicMock()
    api.async_get_system_log = AsyncMock()
    forwarder, _ = _forwarder(api, paused=True)
    await forwarder.async_start()

    await forwarder.async_poll()

    api.async_get_system_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_forwarder_skips_overlapping_poll(mock_send, mock_track):
    api = MagicMock()
    api.async_get_system_log = AsyncMock()
    forwarder, _ = _forwarder(api)
    await forwarder.async_start()

    async with forwarder._lock:
        await forwarder.async_poll()

    api.async_get_system_log.assert_not_awaited()


@pytest.fixture
def api():
    session = MagicMock(spec=aiohttp.ClientSession)
    api = TplinkDecoApi(session, "http://10.0.0.1", "admin", "password", False)
    api._stok = "token"
    api._cookie = "sysauth=abc"
    api._seq = 1
    api._encode_payload = MagicMock(side_effect=lambda payload: payload)
    api._decrypt_data = MagicMock(side_effect=lambda context, data: data)
    return api


def _page(index, total, lines):
    return {
        "data": {
            "error_code": 0,
            "result": {
                "totalNum": total,
                "currentIndex": index,
                "logList": [{"content": line} for line in lines],
            },
        }
    }


@pytest.mark.asyncio
async def test_get_system_log_reads_all_pages(api):
    posts = []

    async def post(context, url, params, data):
        posts.append(data)
        if data["operation"] == "build":
            return {"data": {"error_code": 0}}
        index = data["params"]["index"]
        return _page(index, 2, [f"p{index}a", f"p{index}b"])

    api._async_post = AsyncMock(side_effect=post)

    assert await api.async_get_system_log(4) == ["p0a", "p0b", "p1a", "p1b"]
    assert posts[0] == {"operation": "build", "params": {"level": 4}}
    assert api._async_post.call_args.args[1] == (
        "http://10.0.0.1/cgi-bin/luci/;stok=token/admin/log_export"
    )
    assert api._async_post.call_args.kwargs["params"] == {"form": "feedback_log"}


@pytest.mark.asyncio
async def test_get_system_log_retries_empty_page_without_relogin(api):
    responses = [
        {"data": {"error_code": 0}},
        {"data": ""},
        _page(0, 1, ["line"]),
    ]
    api._async_post = AsyncMock(side_effect=responses)
    api.async_login = AsyncMock()

    assert await api.async_get_system_log() == ["line"]
    api.async_login.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_system_log_stops_on_empty_log_list(api):
    api._async_post = AsyncMock(
        side_effect=[{"data": {"error_code": 0}}, _page(0, 5, [])]
    )

    assert await api.async_get_system_log() == []
    assert api._async_post.await_count == 2
