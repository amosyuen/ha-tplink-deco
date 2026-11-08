"""Forward the Deco system log to a syslog server.

Each poll downloads the whole log and sends only the lines after the tail
remembered from the previous poll. The tail is persisted per config entry, so
lines logged while Home Assistant was stopped are forwarded on the next start.
The first poll after forwarding is enabled only records a tail; the log
history from before that is never sent.
"""

import asyncio
from collections.abc import Callable
import contextlib
from datetime import datetime
from datetime import timedelta
import logging
import re
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
from .system_log import SystemLogLevel

_LOGGER: logging.Logger = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Long enough that a run of identical lines can't be mistaken for the tail.
TAIL_LINES = 20
MAX_LINES_PER_POLL = 1000
SEND_TIMEOUT_SECONDS = 10
CLOSE_TIMEOUT_SECONDS = 5

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
# Request URLs carry the session token, and aiohttp errors quote the URL.
STOK_PATTERN = re.compile(r"stok=[^/?&'\"\s]*")


def storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.syslog"


def lines_after(tail: list[str], fetched: list[str]) -> list[str] | None:
    """Return the lines in fetched after the last occurrence of tail.

    fetched may start with only the end of tail when the oldest tail lines
    have rolled out of the Deco's buffer; that counts as a match too. Returns
    None when there's no overlap: the Deco rebooted or its buffer wrapped.
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


def format_rfc5424(line: str, hostname: str | None, now: datetime) -> str:
    """Convert a Deco log line into an RFC 5424 syslog message.

    Deco timestamps have no time zone, so they're read as Home Assistant's.
    A line that doesn't parse is sent whole as user.notice, stamped with now.
    """
    match = DECO_LINE_PATTERN.match(line)
    timestamp = now
    if match:
        try:
            timestamp = datetime.strptime(
                " ".join(match["ts"].split()), "%b %d %H:%M:%S %Y"
            ).replace(tzinfo=dt_util.get_default_time_zone())
        except ValueError:
            match = None
    if match is None:
        pri, app, pid, msg = DEFAULT_PRI, "-", "-", line
    else:
        facility = FACILITIES.get(match["facility"], FACILITIES["user"])
        severity = SEVERITIES.get(match["severity"], SEVERITIES["notice"])
        pri = facility * 8 + severity
        app = (match["app"] or "-")[:48]
        pid = match["pid"] or "-"
        msg = match["msg"]
    return (
        f"<{pri}>1 {timestamp.isoformat(timespec='seconds')} {hostname or '-'} "
        f"{app} {pid} - - {msg}"
    )


async def _async_send_udp(host: str, port: int, payloads: list[bytes]) -> None:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, remote_addr=(host, port)
    )
    try:
        for payload in payloads:
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


async def async_send_syslog(
    host: str, port: int, protocol: str, messages: list[str]
) -> None:
    """Send messages to a syslog server.

    UDP sends one datagram per message (RFC 5426). TCP frames each message
    with a newline (RFC 6587). Name resolution, connecting and sending share
    one deadline; closing a TCP connection has its own.
    """
    payloads = [message.encode("utf-8", errors="replace") for message in messages]
    send = {SYSLOG_PROTOCOL_TCP: _async_send_tcp, SYSLOG_PROTOCOL_UDP: _async_send_udp}[
        protocol
    ]
    async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
        await send(host, port, payloads)


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
        host: str,
        port: int,
        protocol: str,
        level: SystemLogLevel,
        interval: timedelta,
        is_paused: Callable[[], bool],
    ) -> None:
        self._hass = hass
        self._config_entry = config_entry
        self._api = api
        self._store = store
        self._hostname = hostname
        self._host = host
        self._port = port
        self._protocol = protocol
        self._level = level
        self._interval = interval
        self._is_paused = is_paused
        self._tail: list[str] | None = None
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
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @callback
    def _async_schedule_poll(self, _now: datetime | None = None) -> None:
        if self._task is not None and not self._task.done():
            _LOGGER.debug("Previous Deco syslog forward still running, skipping")
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
        except Exception as err:
            # The failed lines stay after the saved tail, so the next poll
            # retries them.
            _LOGGER.warning(
                "Failed to forward Deco system log to syslog: %s", describe_error(err)
            )

    async def async_forward_new_lines(self) -> int:
        """Send the lines logged since the last poll and return how many."""
        text = await self._api.async_get_system_log(self._level)
        fetched = [line for line in text.splitlines() if line]

        if self._tail is None:
            _LOGGER.info(
                "Deco syslog forwarding will send lines logged from now on; the"
                " %d existing lines are not sent",
                len(fetched),
            )
            await self._async_save_tail(fetched)
            return 0

        new = lines_after(self._tail, fetched)
        if new is None:
            _LOGGER.warning(
                "Deco system log has no overlap with the last forwarded lines;"
                " the Deco may have rebooted or lines may have been missed"
            )
            new = fetched
        if len(new) > MAX_LINES_PER_POLL:
            _LOGGER.warning(
                "Forwarding only the newest %d of %d Deco system log lines",
                MAX_LINES_PER_POLL,
                len(new),
            )
            new = new[-MAX_LINES_PER_POLL:]

        if new:
            now = dt_util.now()
            await async_send_syslog(
                self._host,
                self._port,
                self._protocol,
                [format_rfc5424(line, self._hostname, now) for line in new],
            )
        await self._async_save_tail(fetched)
        _LOGGER.debug("Forwarded %d Deco system log lines to syslog", len(new))
        return len(new)

    async def _async_save_tail(self, fetched: list[str]) -> None:
        self._tail = fetched[-TAIL_LINES:]
        await self._store.async_save({"level": self._level, "tail": self._tail})


async def async_setup_syslog_forwarder(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    api: TplinkDecoApi,
    is_paused: Callable[[], bool],
) -> TplinkDecoSyslogForwarder | None:
    """Start forwarding for config_entry, or return None when it's disabled."""
    store = Store(hass, STORAGE_VERSION, storage_key(config_entry.entry_id))
    data = config_entry.data
    if not data.get(CONF_SYSLOG_ENABLED, DEFAULT_SYSLOG_ENABLED):
        # Re-enabling later starts from a fresh tail instead of a stale one.
        await store.async_remove()
        return None

    forwarder = TplinkDecoSyslogForwarder(
        hass,
        config_entry,
        api,
        store,
        hostname=urlparse(data[CONF_HOST]).hostname,
        host=data[CONF_SYSLOG_HOST],
        port=data.get(CONF_SYSLOG_PORT, DEFAULT_SYSLOG_PORT),
        protocol=data.get(CONF_SYSLOG_PROTOCOL, DEFAULT_SYSLOG_PROTOCOL),
        level=SystemLogLevel[data.get(CONF_SYSLOG_LOG_LEVEL, DEFAULT_SYSLOG_LOG_LEVEL)],
        interval=timedelta(
            seconds=data.get(CONF_SYSLOG_INTERVAL, DEFAULT_SYSLOG_INTERVAL)
        ),
        is_paused=is_paused,
    )
    await forwarder.async_start()
    return forwarder


async def async_remove_syslog_store(hass: HomeAssistant, entry_id: str) -> None:
    await Store(hass, STORAGE_VERSION, storage_key(entry_id)).async_remove()
