"""Forward the TP-Link Deco system log to a syslog server."""

import asyncio
from datetime import datetime
from datetime import timedelta
import logging
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import TplinkDecoApi
from .const import DOMAIN
from .const import SYSLOG_PROTOCOL_TCP

_LOGGER: logging.Logger = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Trailing lines remembered from the last poll, used to find where new lines start
ANCHOR_LINES = 20
UDP_DRAIN_TIMEOUT_TICKS = 500  # 10ms each

LOG_LEVELS = {
    "ALERT": 1,
    "CRITICAL": 2,
    "ERROR": 3,
    "WARNING": 4,
    "NOTICE": 5,
    "INFO": 6,
    "DEBUG": 7,
    "ALL": 8,
}

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
DECO_LINE_PATTERN = re.compile(
    r"^\w{3} (?P<ts>\w{3} +\d{1,2} \d{2}:\d{2}:\d{2} \d{4}) "
    r"(?P<facility>\w+)\.(?P<severity>\w+) "
    r"(?:(?P<app>[^\s:\[]+)(?:\[(?P<pid>\d+)\])?: )?"
    r"(?P<msg>.*)$"
)


def lines_after(anchor: list[str], fetched: list[str]) -> list[str] | None:
    """Return the lines in fetched after the last occurrence of anchor.

    If the oldest anchor lines have already rolled out of the Deco's log buffer,
    fetched may start with just the tail of anchor; that counts as a match too.
    Returns None when there's no overlap, i.e. the Deco rebooted or its log buffer
    wrapped completely since the last poll.
    """
    if not anchor:
        return fetched
    n = len(anchor)
    for i in range(len(fetched) - n, -1, -1):
        if fetched[i : i + n] == anchor:
            return fetched[i + n :]
    for k in range(min(n, len(fetched)), 0, -1):
        if fetched[:k] == anchor[-k:]:
            return fetched[k:]
    return None


def format_rfc5424(line: str, hostname: str, now: datetime | None = None) -> str:
    """Convert a Deco log line into an RFC 5424 syslog message.

    Deco timestamps have no time zone, so they're taken as Home Assistant's local time.
    Lines that don't parse are sent whole as user.notice stamped with the current time.
    """
    match = DECO_LINE_PATTERN.match(line)
    if match:
        try:
            timestamp = datetime.strptime(
                " ".join(match["ts"].split()), "%b %d %H:%M:%S %Y"
            ).replace(tzinfo=dt_util.get_default_time_zone())
        except ValueError:
            match = None
    if match is None:
        timestamp = now or dt_util.now()
        pri = DEFAULT_PRI
        app, pid, msg = "-", "-", line
    else:
        facility = FACILITIES.get(match["facility"], FACILITIES["user"])
        severity = SEVERITIES.get(match["severity"], SEVERITIES["notice"])
        pri = facility * 8 + severity
        app = match["app"] or "-"
        pid = match["pid"] or "-"
        msg = match["msg"]
    return (
        f"<{pri}>1 {timestamp.isoformat(timespec='seconds')} {hostname or '-'} "
        f"{app[:48]} {pid} - - {msg}"
    )


class _UdpProtocol(asyncio.DatagramProtocol):
    def error_received(self, exc):
        _LOGGER.debug("Syslog UDP error: %s", exc)


async def async_send_syslog(
    host: str, port: int, protocol: str, messages: list[str]
) -> None:
    """Send messages to a syslog server, one per UDP datagram or newline framed on TCP."""
    loop = asyncio.get_running_loop()
    if protocol == SYSLOG_PROTOCOL_TCP:
        _, writer = await asyncio.open_connection(host, port)
        try:
            for message in messages:
                writer.write(message.encode("utf-8", errors="replace") + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
        return

    transport, _ = await loop.create_datagram_endpoint(
        _UdpProtocol, remote_addr=(host, port)
    )
    try:
        for i, message in enumerate(messages):
            transport.sendto(message.encode("utf-8", errors="replace"))
            # Yield now and then so a large backlog doesn't overrun the socket buffer
            if i % 100 == 99:
                await asyncio.sleep(0.01)
        # Closing drops datagrams still queued in the transport, so let them flush
        for _ in range(UDP_DRAIN_TIMEOUT_TICKS):
            if not transport.get_write_buffer_size():
                break
            await asyncio.sleep(0.01)
    finally:
        transport.close()


class TplinkDecoLogForwarder:
    """Periodically pull the Deco system log and send new lines to syslog."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TplinkDecoApi,
        entry_id: str,
        hostname: str,
        syslog_host: str,
        syslog_port: int,
        syslog_protocol: str,
        level: int,
        interval: timedelta,
        is_paused=lambda: False,
    ) -> None:
        self._hass = hass
        self._api = api
        self._hostname = hostname
        self._syslog_host = syslog_host
        self._syslog_port = syslog_port
        self._syslog_protocol = syslog_protocol
        self._level = level
        self._interval = interval
        self._is_paused = is_paused
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.syslog")
        self._anchor: list[str] | None = None
        self._lock = asyncio.Lock()
        self._unsub = None
        self.last_forwarded_count = 0
        self.last_error: str | None = None

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        # A changed level means a different log view, so the old anchor won't match
        if stored.get("level") == self._level:
            self._anchor = stored.get("anchor") or []
        else:
            self._anchor = []
        self._unsub = async_track_time_interval(
            self._hass, self.async_poll, self._interval, cancel_on_shutdown=True
        )

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def async_poll(self, _now=None) -> None:
        if self._is_paused():
            _LOGGER.debug("Deco polling is paused, skipping syslog forward")
            return
        if self._lock.locked():
            _LOGGER.debug("Previous syslog forward still running, skipping")
            return
        async with self._lock:
            try:
                await self.async_forward_new_lines()
                self.last_error = None
            except Exception as err:
                self.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.warning("Failed to forward Deco system log: %s", err)

    async def async_forward_new_lines(self) -> int:
        fetched = [
            line for line in await self._api.async_get_system_log(self._level) if line
        ]
        new = lines_after(self._anchor, fetched)
        if new is None:
            _LOGGER.info(
                "Deco log has no overlap with the last forwarded lines (rebooted or "
                "wrapped); forwarding all %d lines",
                len(fetched),
            )
            new = fetched

        if new:
            now = dt_util.now()
            messages = [format_rfc5424(line, self._hostname, now) for line in new]
            await async_send_syslog(
                self._syslog_host, self._syslog_port, self._syslog_protocol, messages
            )
            # Only advance once sent, so a failed send is retried on the next poll
            self._anchor = fetched[-ANCHOR_LINES:]
            await self._store.async_save({"level": self._level, "anchor": self._anchor})

        self.last_forwarded_count = len(new)
        _LOGGER.debug("Forwarded %d Deco log lines to syslog", len(new))
        return len(new)
