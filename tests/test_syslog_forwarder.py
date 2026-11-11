"""Tests for forwarding the Deco system log to syslog."""

from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import voluptuous as vol

from custom_components.tplink_deco import async_remove_entry
from custom_components.tplink_deco import async_unload_entry
from custom_components.tplink_deco import syslog_forwarder
from custom_components.tplink_deco.config_flow import _get_schema
from custom_components.tplink_deco.config_flow import _validate_syslog
from custom_components.tplink_deco.const import CONF_SYSLOG_ENABLED
from custom_components.tplink_deco.const import CONF_SYSLOG_HOST
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SYSLOG_FORWARDER_KEY
from custom_components.tplink_deco.const import SYSLOG_PROTOCOL_TCP
from custom_components.tplink_deco.const import SYSLOG_PROTOCOL_UDP
from custom_components.tplink_deco.exceptions import UnsupportedFirmwareException
from custom_components.tplink_deco.syslog_forwarder import SyslogServer
from custom_components.tplink_deco.syslog_forwarder import TplinkDecoSyslogForwarder
from custom_components.tplink_deco.syslog_forwarder import async_setup_syslog_forwarder
from custom_components.tplink_deco.syslog_forwarder import format_rfc5424
from custom_components.tplink_deco.syslog_forwarder import lines_after
from custom_components.tplink_deco.system_log import SystemLogLevel

NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, data=None):
        self.data = data
        self.removed = False

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data

    async def async_remove(self):
        self.data = None
        self.removed = True


def _config_entry(entry_id="entry", data=None):
    return SimpleNamespace(
        entry_id=entry_id,
        data=data or {},
        async_create_background_task=lambda _hass, target, name: asyncio.create_task(
            target
        ),
    )


def _log(*lines):
    return "".join(f"{line}\n" for line in lines)


def _api(*lines):
    """Return an API whose system log holds lines."""
    return MagicMock(async_get_system_log=AsyncMock(return_value=_log(*lines)))


def _forwarder(
    api,
    store=None,
    *,
    tail=None,
    level=SystemLogLevel.ALL,
    paused=False,
    entry_id="entry",
):
    """Return a forwarder that resumes after tail, or a new one without it."""
    forwarder = TplinkDecoSyslogForwarder(
        MagicMock(),
        _config_entry(entry_id),
        api,
        store if store is not None else FakeStore(),
        hostname="192.168.0.1",
        server=SyslogServer("syslog.example", 514, SYSLOG_PROTOCOL_UDP),
        level=level,
        interval=timedelta(seconds=300),
        is_paused=lambda: paused,
    )
    forwarder._tail = tail
    return forwarder


@pytest.fixture
def send():
    with patch.object(SyslogServer, "async_send", AsyncMock()) as send:
        yield send


def _sent_lines(send):
    """Return the Deco lines sent, without their syslog headers."""
    return [
        message.rsplit(" ", 1)[1]
        for call in send.await_args_list
        for message in call.args[0]
    ]


@pytest.mark.parametrize(
    ("tail", "fetched", "expected"),
    [
        ([], ["a", "b"], ["a", "b"]),
        (["b", "c"], ["a", "b", "c", "d", "e"], ["d", "e"]),
        (["b", "c"], ["b", "c", "x", "b", "c", "y"], ["y"]),
        (["a", "b", "c"], ["b", "c", "d"], ["d"]),
        (["a", "b"], ["x", "y"], None),
        (["a", "b"], ["a", "b"], []),
    ],
)
def test_lines_after(tail, fetched, expected):
    assert lines_after(tail, fetched) == expected


@pytest.fixture
def utc():
    with patch.object(
        syslog_forwarder.dt_util, "get_default_time_zone", return_value=timezone.utc
    ):
        yield


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "Thu Oct 15 18:19:19 2026 daemon.err udhcpd[14146]: Sending ACK",
            "<27>1 2026-10-15T18:19:19+00:00 deco udhcpd 14146 - - Sending ACK",
        ),
        (
            "Sat Nov  7 12:19:32 2026 user.info : PRIVACY_ASSETS_INFO",
            "<14>1 2026-11-07T12:19:32+00:00 deco - - - - PRIVACY_ASSETS_INFO",
        ),
    ],
)
def test_format_rfc5424_parses_deco_line(utc, line, expected):
    assert format_rfc5424([line], "deco", NOW) == [expected]


@pytest.mark.parametrize(
    "line", ["free-form text", "Thu Feb 30 18:19:19 2026 daemon.err udhcpd: x"]
)
def test_format_rfc5424_sends_line_without_header_whole(line):
    assert format_rfc5424([line], None, NOW) == [
        f"<13>1 2026-11-08T12:00:00+00:00 - - - - - {line}"
    ]


def test_format_rfc5424_continuation_lines_follow_previous_header(utc):
    header = "Sat Nov  7 12:19:42 2026 user.err fan[7]: at+qtemp"

    assert format_rfc5424(
        ['+QTEMP:"a","53"', header, '+QTEMP:"b","0"'], "deco", NOW, previous=[header]
    ) == [
        '<11>1 2026-11-07T12:19:42+00:00 deco fan 7 - - +QTEMP:"a","53"',
        "<11>1 2026-11-07T12:19:42+00:00 deco fan 7 - - at+qtemp",
        '<11>1 2026-11-07T12:19:42+00:00 deco fan 7 - - +QTEMP:"b","0"',
    ]


@pytest.mark.asyncio
async def test_first_poll_records_tail_without_sending_history(send):
    api = _api("a", "b")
    store = FakeStore()
    forwarder = _forwarder(api, store)

    assert await forwarder.async_forward_new_lines() == 0
    send.assert_not_awaited()
    assert store.data == {"level": SystemLogLevel.ALL, "tail": ["a", "b"]}

    api.async_get_system_log.return_value = _log("a", "b", "c")
    assert await forwarder.async_forward_new_lines() == 1
    assert _sent_lines(send) == ["c"]


@pytest.mark.asyncio
async def test_continuation_at_start_of_poll_follows_header_in_tail(send):
    header = "Sat Nov  7 12:19:42 2026 user.err fan[7]: at+qtemp"
    forwarder = _forwarder(_api(header, '+QTEMP:"a","53"'), tail=[header])

    await forwarder.async_forward_new_lines()

    assert send.await_args.args[0][0].startswith("<11>1 2026-11-07T12:19:42")


@pytest.mark.asyncio
async def test_stored_tail_resumes_after_restart(send):
    api = _api("a", "b", "c")
    store = FakeStore({"level": SystemLogLevel.ALL, "tail": ["a"]})
    forwarder = _forwarder(api, store)

    with patch.object(syslog_forwarder, "async_track_time_interval"):
        await forwarder.async_start()
    await forwarder._task

    assert _sent_lines(send) == ["b", "c"]
    assert store.data["tail"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_stored_tail_from_another_level_is_ignored(send):
    api = _api("x", "y")
    store = FakeStore({"level": SystemLogLevel.ALL, "tail": ["a"]})
    forwarder = _forwarder(api, store, level=SystemLogLevel.ERROR)

    with patch.object(syslog_forwarder, "async_track_time_interval"):
        await forwarder.async_start()
    await forwarder._task

    send.assert_not_awaited()
    assert store.data == {"level": SystemLogLevel.ERROR, "tail": ["x", "y"]}


@pytest.mark.asyncio
async def test_no_overlap_twice_forwards_newest_lines_up_to_cap(send, caplog):
    forwarder = _forwarder(_api("v", "w", "x", "y", "z"), tail=["a"])

    with patch.object(syslog_forwarder, "MAX_LINES_PER_POLL", 3):
        assert await forwarder.async_forward_new_lines() == 0
        send.assert_not_awaited()
        assert await forwarder.async_forward_new_lines() == 3

    assert _sent_lines(send) == ["x", "y", "z"]
    assert "no overlap" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_lines", [(), ("stale",)])
async def test_one_bad_log_keeps_tail(send, bad_lines):
    api = _api(*bad_lines)
    store = FakeStore()
    forwarder = _forwarder(api, store, tail=["a", "b"])

    assert await forwarder.async_forward_new_lines() == 0
    assert store.data is None

    api.async_get_system_log.return_value = _log("a", "b", "c")
    assert await forwarder.async_forward_new_lines() == 1
    assert _sent_lines(send) == ["c"]

    api.async_get_system_log.return_value = _log(*bad_lines)
    assert await forwarder.async_forward_new_lines() == 0
    assert _sent_lines(send) == ["c"]


@pytest.mark.asyncio
async def test_empty_log_on_first_poll_records_no_tail(send):
    api = _api()
    store = FakeStore()
    forwarder = _forwarder(api, store)

    await forwarder.async_forward_new_lines()

    assert store.data is None
    api.async_get_system_log.return_value = _log("a")
    await forwarder.async_forward_new_lines()
    send.assert_not_awaited()
    assert store.data["tail"] == ["a"]


@pytest.mark.asyncio
async def test_failed_send_keeps_tail_so_next_poll_retries(send):
    store = FakeStore()
    forwarder = _forwarder(_api("a", "b"), store, tail=["a"])
    send.side_effect = OSError("unreachable")

    await forwarder.async_poll()

    assert store.data is None
    send.side_effect = None
    await forwarder.async_poll()
    assert _sent_lines(send) == ["b", "b"]
    assert store.data["tail"] == ["a", "b"]


@pytest.mark.asyncio
async def test_poll_error_log_redacts_session_token(caplog):
    api = MagicMock(
        async_get_system_log=AsyncMock(
            side_effect=Exception(
                "forbidden, url='http://192.168.0.1/cgi-bin/luci/;stok=abc123/admin'"
            )
        )
    )
    forwarder = _forwarder(api)

    with caplog.at_level(logging.WARNING):
        await forwarder.async_poll()

    assert "abc123" not in caplog.text
    assert "stok=REDACTED/admin" in caplog.text


@pytest.mark.asyncio
async def test_unsupported_firmware_stops_forwarding_with_one_warning(caplog):
    api = MagicMock(
        async_get_system_log=AsyncMock(
            side_effect=UnsupportedFirmwareException("not supported")
        )
    )
    forwarder = _forwarder(api)
    unsub = MagicMock()

    with (
        patch.object(syslog_forwarder, "async_track_time_interval", return_value=unsub),
        caplog.at_level(logging.WARNING),
    ):
        await forwarder.async_start()
        await forwarder._task

    unsub.assert_called_once_with()
    assert len(caplog.records) == 1
    await forwarder.async_stop()
    unsub.assert_called_once_with()


@pytest.mark.asyncio
async def test_paused_polling_skips_router(send):
    api = MagicMock(async_get_system_log=AsyncMock())
    forwarder = _forwarder(api, paused=True)

    await forwarder.async_poll()

    api.async_get_system_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_is_skipped_while_previous_runs_and_stop_cancels_it():
    started = asyncio.Event()

    async def slow_log(_level):
        started.set()
        await asyncio.Event().wait()

    api = MagicMock(async_get_system_log=slow_log)
    forwarder = _forwarder(api)
    unsub = MagicMock()

    with patch.object(
        syslog_forwarder, "async_track_time_interval", return_value=unsub
    ):
        await forwarder.async_start()
    await started.wait()
    task = forwarder._task

    forwarder._async_schedule_poll()
    assert forwarder._task is task

    await forwarder.async_stop()
    unsub.assert_called_once_with()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_send_udp_pauses_between_bursts():
    transport = MagicMock(get_write_buffer_size=MagicMock(return_value=0))
    sent_before_pause = []

    async def pause(_seconds):
        sent_before_pause.append(transport.sendto.call_count)

    loop = asyncio.get_running_loop()
    with (
        patch.object(
            loop,
            "create_datagram_endpoint",
            AsyncMock(return_value=(transport, None)),
        ),
        patch.object(syslog_forwarder, "UDP_BURST_DATAGRAMS", 2),
        patch.object(syslog_forwarder.asyncio, "sleep", pause),
    ):
        await SyslogServer("127.0.0.1", 514, SYSLOG_PROTOCOL_UDP).async_send(
            ["1", "2", "3", "4", "5"]
        )

    assert sent_before_pause == [2, 4]
    assert transport.sendto.call_count == 5


@pytest.mark.asyncio
async def test_send_udp_delivers_one_datagram_per_message():
    received = asyncio.Queue()

    class Server(asyncio.DatagramProtocol):
        def datagram_received(self, data, addr):
            received.put_nowait(data)

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        Server, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        await SyslogServer("127.0.0.1", port, SYSLOG_PROTOCOL_UDP).async_send(
            ["one", "two"]
        )
        assert [await received.get(), await received.get()] == [b"one", b"two"]
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_send_tcp_frames_messages_with_newlines():
    received = asyncio.get_running_loop().create_future()

    async def handle(reader, writer):
        received.set_result(await reader.read())
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        await SyslogServer("127.0.0.1", port, SYSLOG_PROTOCOL_TCP).async_send(
            ["one", "two"]
        )
        assert await received == b"one\ntwo\n"


@pytest.mark.asyncio
async def test_send_tcp_times_out_on_unresponsive_server():
    async def never_connects(*_args):
        await asyncio.Event().wait()

    with (
        patch.object(syslog_forwarder, "SEND_TIMEOUT_SECONDS", 0.01),
        patch.object(syslog_forwarder.asyncio, "open_connection", never_connects),
        pytest.raises(TimeoutError),
    ):
        await SyslogServer("192.0.2.1", 514, SYSLOG_PROTOCOL_TCP).async_send(["one"])


@pytest.mark.asyncio
async def test_send_tcp_aborts_connection_that_does_not_close():
    async def never_closes():
        await asyncio.Event().wait()

    writer = MagicMock(drain=AsyncMock(), wait_closed=never_closes)

    with (
        patch.object(syslog_forwarder, "CLOSE_TIMEOUT_SECONDS", 0.01),
        patch.object(
            syslog_forwarder.asyncio,
            "open_connection",
            AsyncMock(return_value=(None, writer)),
        ),
    ):
        await SyslogServer("192.0.2.1", 514, SYSLOG_PROTOCOL_TCP).async_send(["one"])

    writer.transport.abort.assert_called_once_with()


@pytest.mark.parametrize(
    ("data", "errors"),
    [
        ({CONF_SYSLOG_ENABLED: True}, True),
        ({CONF_SYSLOG_ENABLED: True, CONF_SYSLOG_HOST: ""}, True),
        ({CONF_SYSLOG_ENABLED: True, CONF_SYSLOG_HOST: "log.lan"}, False),
        ({CONF_SYSLOG_ENABLED: False, CONF_SYSLOG_HOST: ""}, False),
    ],
)
def test_validate_syslog_requires_host_when_enabled(data, errors):
    assert bool(_validate_syslog(data)) is errors


def test_syslog_host_is_stripped_so_blank_hosts_fail_validation():
    schema = vol.Schema(_get_schema({}), extra=vol.ALLOW_EXTRA)

    assert schema({CONF_SYSLOG_HOST: " log.lan "})[CONF_SYSLOG_HOST] == "log.lan"
    assert schema({CONF_SYSLOG_HOST: "  "})[CONF_SYSLOG_HOST] == ""


@pytest.mark.asyncio
async def test_disabled_entry_removes_stale_tail():
    store = FakeStore({"level": SystemLogLevel.ALL, "tail": ["a"]})

    with patch.object(syslog_forwarder, "Store", return_value=store):
        forwarder = await async_setup_syslog_forwarder(
            MagicMock(), _config_entry(), MagicMock()
        )

    assert forwarder is None
    assert store.removed


@pytest.mark.asyncio
async def test_entries_forward_independently_and_unload_separately(send):
    stores = {}

    def store_for(_hass, _version, key):
        return stores.setdefault(key, FakeStore())

    unsubs = {}

    def track(_hass, action, _interval, cancel_on_shutdown):
        return unsubs.setdefault(len(unsubs), MagicMock())

    apis = {}
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_forward_entry_unload = AsyncMock(return_value=True)
    entries = {}
    with (
        patch.object(syslog_forwarder, "Store", side_effect=store_for),
        patch.object(syslog_forwarder, "async_track_time_interval", side_effect=track),
    ):
        for entry_id in ("first", "second"):
            apis[entry_id] = _api(entry_id)
            entries[entry_id] = _config_entry(
                entry_id,
                {
                    "host": f"http://{entry_id}.lan",
                    CONF_SYSLOG_ENABLED: True,
                    CONF_SYSLOG_HOST: "syslog.lan",
                },
            )
            forwarder = await async_setup_syslog_forwarder(
                hass, entries[entry_id], MagicMock(api=apis[entry_id], paused=False)
            )
            await forwarder._task
            hass.data[DOMAIN][entry_id] = {
                COORDINATOR_DECOS_KEY: MagicMock(
                    api=MagicMock(async_logout=AsyncMock()),
                    async_close=AsyncMock(),
                    async_shutdown=AsyncMock(),
                ),
                SYSLOG_FORWARDER_KEY: forwarder,
            }

    assert stores["tplink_deco.first.syslog"].data["tail"] == ["first"]
    assert stores["tplink_deco.second.syslog"].data["tail"] == ["second"]

    assert await async_unload_entry(hass, entries["first"]) is True

    unsubs[0].assert_called_once_with()
    unsubs[1].assert_not_called()
    assert "second" in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_removing_entry_deletes_its_tail():
    store = FakeStore({"level": SystemLogLevel.ALL, "tail": ["a"]})

    with patch.object(syslog_forwarder, "Store", return_value=store) as store_cls:
        await async_remove_entry(MagicMock(), SimpleNamespace(entry_id="entry"))

    assert store_cls.call_args.args[2] == "tplink_deco.entry.syslog"
    assert store.removed
