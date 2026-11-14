"""Forward the Deco system log to a syslog server.

The tail is the end of the log as of the previous poll, saved per config
entry. Each poll sends the lines that follow it.
"""

import asyncio
from collections.abc import Callable
from collections.abc import Sequence
import contextlib
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
import logging
import re
from typing import NamedTuple
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import TplinkDecoApi
from .const import CONF_SYSLOG_ENABLED
from .const import CONF_SYSLOG_HOST
from .const import CONF_SYSLOG_INTERVAL
from .const import CONF_SYSLOG_LOG_LEVEL
from .const import CONF_SYSLOG_PORT
from .const import CONF_SYSLOG_PROTOCOL
from .const import DEFAULT_SYSLOG_ENABLED
from .const import DEFAULT_SYSLOG_INTERVAL
from .const import DEFAULT_SYSLOG_LOG_LEVEL
from .const import DEFAULT_SYSLOG_PORT
from .const import DEFAULT_SYSLOG_PROTOCOL
from .const import DOMAIN
from .const import SYSLOG_PROTOCOL_TCP
from .const import SYSLOG_PROTOCOL_UDP
from .coordinator import TplinkDecoUpdateCoordinator
from .exceptions import UnsupportedFirmwareException
from .system_log import SystemLogLevel

_LOGGER: logging.Logger = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Long enough that a run of identical lines is unlikely to match as the tail.
TAIL_LINES = 20
MAX_LINES_PER_BATCH = 1000
FORWARD_TIMEOUT_SECONDS = 30
SEND_TIMEOUT_SECONDS = 10
CLOSE_TIMEOUT_SECONDS = 5
UDP_BURST_DATAGRAMS = 100
UDP_BURST_PAUSE_SECONDS = 0.02

FACILITIES = {
    "kern": 0,
    "user": 1,
    "mail": 2,
    "daemon": 3,
    "auth": 4,
    "syslog": 5,
    "lpr": 6,
    "news": 7,
    "uucp": 8,
    "cron": 9,
    "authpriv": 10,
    "ftp": 11,
    **{f"local{n}": 16 + n for n in range(8)},
}
SEVERITIES = {
    "emerg": 0,
    "alert": 1,
    "crit": 2,
    "err": 3,
    "warn": 4,
    "warning": 4,
    "notice": 5,
    "info": 6,
    "debug": 7,
}
DEFAULT_PRI = FACILITIES["user"] * 8 + SEVERITIES["notice"]

# e.g. "Thu Oct 15 18:19:19 2026 daemon.err udhcpd[14146]: Sending ACK to 10.0.0.19"
# or, with an empty tag, "Sat Nov  7 12:19:32 2026 user.info : PRIVACY_ASSETS_INFO"
DECO_LINE_PATTERN = re.compile(
    r"^\w{3} (?P<ts>\w{3} +\d{1,2} \d{2}:\d{2}:\d{2} \d{4}) "
    r"(?P<facility>\w+)\.(?P<severity>\w+) "
    r"(?:(?P<app>[^\s:\[]*)(?:\[(?P<pid>\d+)\])?: )?"
    r"(?P<msg>.*)$"
)
# Request URLs carry the session token, and aiohttp errors quote the URL.
STOK_PATTERN = re.compile(r"stok=[^/?&'\"\s]*")


def _store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.syslog")


def lines_after(tail: list[str], fetched: list[str]) -> list[str] | None:
    """Return the lines of fetched that follow tail, or None without overlap.

    The oldest tail lines may have rolled out of the Deco's buffer, so a
    fetched log that begins partway through tail also matches.
    """
    if not tail:
        return fetched
    n = len(tail)
    for i in range(len(fetched) - n, -1, -1):
        if fetched[i : i + n] == tail:
            return fetched[i + n :]
    for k in range(min(n, len(fetched)) - 1, 0, -1):
        if fetched[:k] == tail[-k:]:
            return fetched[k:]
    return None


class _Header(NamedTuple):
    timestamp: datetime
    pri: int
    app: str
    pid: str


def _parse_deco_line(line: str) -> tuple[_Header, str] | None:
    """Return the header and message of a Deco line.

    Deco timestamps have no time zone, so they're taken as Home Assistant's.
    """
    match = DECO_LINE_PATTERN.match(line)
    if match is None:
        return None
    try:
        timestamp = datetime.strptime(
            " ".join(match["ts"].split()), "%b %d %H:%M:%S %Y"
        )
    except ValueError:
        return None
    facility = FACILITIES.get(match["facility"], FACILITIES["user"])
    severity = SEVERITIES.get(match["severity"], SEVERITIES["notice"])
    header = _Header(
        timestamp.replace(tzinfo=dt_util.get_default_time_zone()),
        facility * 8 + severity,
        (match["app"] or "-")[:48],
        match["pid"] or "-",
    )
    return header, match["msg"]


def format_rfc5424(
    lines: list[str],
    hostname: str | None,
    now: datetime,
    previous: Sequence[str] = (),
) -> list[str]:
    """Convert Deco log lines into RFC 5424 syslog messages.

    A line without a Deco header, such as the rest of a command's output,
    takes the timestamp, priority and app of the nearest header before it.
    previous holds the lines logged before the first of lines. A line with
    no header before it is sent as user.notice stamped with now.
    """
    header = _Header(now, DEFAULT_PRI, "-", "-")
    for line in previous:
        if (parsed := _parse_deco_line(line)) is not None:
            header, _ = parsed
    messages = []
    for line in lines:
        if (parsed := _parse_deco_line(line)) is not None:
            header, msg = parsed
        else:
            msg = line
        messages.append(
            f"<{header.pri}>1 {header.timestamp.isoformat(timespec='seconds')}"
            f" {hostname or '-'} {header.app} {header.pid} - - {msg}"
        )
    return messages


async def _async_send_udp(host: str, port: int, payloads: list[bytes]) -> None:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, remote_addr=(host, port)
    )
    try:
        for i, payload in enumerate(payloads):
            # A receive buffer holds a few hundred datagrams, so pause between
            # bursts to give the server time to drain it.
            if i and i % UDP_BURST_DATAGRAMS == 0:
                await asyncio.sleep(UDP_BURST_PAUSE_SECONDS)
            transport.sendto(payload)
        # Closing drops datagrams the socket hasn't accepted yet.
        while transport.get_write_buffer_size():
            await asyncio.sleep(0.01)
    finally:
        transport.close()


async def _async_send_tcp(host: str, port: int, payloads: list[bytes]) -> None:
    _, writer = await asyncio.open_connection(host, port)
    try:
        writer.writelines(payload + b"\n" for payload in payloads)
        await writer.drain()
    finally:
        writer.close()
        try:
            async with asyncio.timeout(CLOSE_TIMEOUT_SECONDS):
                await writer.wait_closed()
        except (TimeoutError, OSError):
            writer.transport.abort()


_SENDERS = {SYSLOG_PROTOCOL_TCP: _async_send_tcp, SYSLOG_PROTOCOL_UDP: _async_send_udp}


@dataclass(frozen=True)
class SyslogServer:
    host: str
    port: int
    protocol: str

    async def async_send(self, messages: list[str]) -> None:
        """Send messages to the server.

        UDP sends one datagram per message (RFC 5426). TCP frames each message
        with a newline (RFC 6587). Name resolution, connecting and sending
        share one deadline. Closing a TCP connection has its own.
        """
        payloads = [message.encode("utf-8", errors="replace") for message in messages]
        async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
            await _SENDERS[self.protocol](self.host, self.port, payloads)


def describe_error(err: Exception) -> str:
    """Return err for logging, without the Deco session token."""
    return STOK_PATTERN.sub("stok=REDACTED", f"{type(err).__name__}: {err}")


class TplinkDecoSyslogForwarder:
    """Periodically send new Deco system log lines to a syslog server."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: TplinkDecoApi,
        store: Store,
        *,
        hostname: str | None,
        server: SyslogServer,
        level: SystemLogLevel,
        interval: timedelta,
        is_paused: Callable[[], bool],
    ) -> None:
        self._hass = hass
        self._config_entry = config_entry
        self._api = api
        self._store = store
        self._hostname = hostname
        self._server = server
        self._level = level
        self._interval = interval
        self._is_paused = is_paused
        self._tail: list[str] | None = None
        self._missed_tail = False
        self._task: asyncio.Task | None = None
        self._unsub_interval: Callable[[], None] | None = None

    async def async_start(self) -> None:
        stored = await self._store.async_load()
        # A tail taken at another level may not appear at this one.
        if stored is not None and stored.get("level") == self._level:
            self._tail = stored["tail"]
        self._unsub_interval = async_track_time_interval(
            self._hass,
            self._async_schedule_poll,
            self._interval,
            cancel_on_shutdown=True,
        )
        self._async_schedule_poll()

    async def async_stop(self) -> None:
        self._cancel_interval()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _cancel_interval(self) -> None:
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    @callback
    def _async_schedule_poll(self, _now: datetime | None = None) -> None:
        if self._task is not None and not self._task.done():
            _LOGGER.debug("Previous Deco syslog run still in progress, skipping")
            return
        self._task = self._config_entry.async_create_background_task(
            self._hass, self.async_poll(), name="tplink_deco syslog forward"
        )

    async def async_poll(self) -> None:
        if self._is_paused():
            _LOGGER.debug("Deco polling is paused, skipping syslog forward")
            return
        try:
            await self.async_forward_new_lines()
        except UnsupportedFirmwareException as err:
            self._cancel_interval()
            _LOGGER.warning(
                "Stopped Deco syslog forwarding until the integration is reloaded: %s",
                describe_error(err),
            )
        except Exception as err:
            # The tail advances only after a successful send, so the next poll
            # retries these lines.
            _LOGGER.warning(
                "Failed to forward Deco system log to syslog: %s", describe_error(err)
            )

    async def async_forward_new_lines(self) -> int:
        """Send the lines logged since the last poll and return how many."""
        text = await self._api.async_get_system_log(self._level)
        fetched = [line for line in text.splitlines() if line]
        if not fetched:
            # The Deco sometimes returns an empty log. Saving it as the tail
            # would make the next poll resend the whole log.
            _LOGGER.debug("Deco returned an empty system log, skipping")
            return 0

        if self._tail is None:
            _LOGGER.info(
                "Deco syslog forwarding will send lines logged from now on; the"
                " %d existing lines are not sent",
                len(fetched),
            )
            await self._async_save_tail(fetched)
            return 0

        new = self._lines_after_tail(fetched)
        if new is None:
            return 0
        if not new:
            return 0

        start = len(fetched) - len(new)
        sent = 0
        async with asyncio.timeout(FORWARD_TIMEOUT_SECONDS):
            messages = await asyncio.to_thread(
                format_rfc5424,
                new,
                self._hostname,
                dt_util.now(),
                previous=fetched[max(0, start - TAIL_LINES) : start],
            )
            for offset in range(0, len(messages), MAX_LINES_PER_BATCH):
                if self._is_paused():
                    break
                batch = messages[offset : offset + MAX_LINES_PER_BATCH]
                await self._server.async_send(batch)
                # Checkpoint only completed batches, never the unsent snapshot end.
                end = start + offset + len(batch)
                await self._async_save_tail(fetched[max(0, end - TAIL_LINES) : end])
                sent += len(batch)
                await asyncio.sleep(0)
        _LOGGER.debug(
            "Forwarded %d of %d new Deco system log lines to syslog", sent, len(new)
        )
        return sent

    def _lines_after_tail(self, fetched: list[str]) -> list[str] | None:
        """Return all lines after the saved tail in their original order.

        Return None to skip this poll.
        """
        new = lines_after(self._tail, fetched)
        if new is None:
            if not self._missed_tail:
                # The Deco sometimes returns a stale or partial log, and the
                # next poll's log matches the tail again.
                self._missed_tail = True
                _LOGGER.debug(
                    "Deco system log has no overlap with the last forwarded lines, skipping"
                )
                return None
            _LOGGER.warning(
                "Deco system log has no overlap with the last forwarded lines"
                " for two polls; the Deco may have rebooted or lines may have"
                " been missed"
            )
            new = fetched
        self._missed_tail = False
        return new

    async def _async_save_tail(self, fetched: list[str]) -> None:
        tail = fetched[-TAIL_LINES:]
        await self._store.async_save({"level": self._level, "tail": tail})
        self._tail = tail


async def async_setup_syslog_forwarder(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    deco_coordinator: TplinkDecoUpdateCoordinator,
) -> TplinkDecoSyslogForwarder | None:
    """Start forwarding for config_entry, or return None when it's disabled."""
    store = _store(hass, config_entry.entry_id)
    data = config_entry.data
    if not data.get(CONF_SYSLOG_ENABLED, DEFAULT_SYSLOG_ENABLED):
        # A stale tail would resend old lines if forwarding is re-enabled.
        await store.async_remove()
        return None

    forwarder = TplinkDecoSyslogForwarder(
        hass,
        config_entry,
        deco_coordinator.api,
        store,
        hostname=urlparse(data[CONF_HOST]).hostname,
        server=SyslogServer(
            data[CONF_SYSLOG_HOST],
            data.get(CONF_SYSLOG_PORT, DEFAULT_SYSLOG_PORT),
            data.get(CONF_SYSLOG_PROTOCOL, DEFAULT_SYSLOG_PROTOCOL),
        ),
        level=SystemLogLevel[data.get(CONF_SYSLOG_LOG_LEVEL, DEFAULT_SYSLOG_LOG_LEVEL)],
        interval=timedelta(
            seconds=data.get(CONF_SYSLOG_INTERVAL, DEFAULT_SYSLOG_INTERVAL)
        ),
        is_paused=lambda: deco_coordinator.paused,
    )
    await forwarder.async_start()
    return forwarder


async def async_remove_syslog_store(hass: HomeAssistant, entry_id: str) -> None:
    await _store(hass, entry_id).async_remove()
