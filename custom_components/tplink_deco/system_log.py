"""Deco system log data and paging state, independent of transport."""

from collections.abc import Hashable
from dataclasses import dataclass
from dataclasses import field
from enum import IntEnum
from itertools import takewhile


class SystemLogLevel(IntEnum):
    """Minimum severity for a log download. Each includes the levels before it.

    ALERT through DEBUG share the RFC 5424 syslog severity numbers. ALL is the
    router's no-filter value, not a severity.
    """

    ALERT = 1
    CRITICAL = 2
    ERROR = 3
    WARNING = 4
    NOTICE = 5
    INFO = 6
    DEBUG = 7
    ALL = 8


SYSTEM_LOG_PAGE_SIZE = 100
SYSTEM_LOG_EMPTY_PAGE_RETRIES = 3
SYSTEM_LOG_DEADLINE_SECONDS = 60


@dataclass
class SystemLog:
    """Deco system log lines, oldest first.

    complete is False if the deadline ended the download early.
    """

    lines: list[str]
    complete: bool


def parse_page_lines(result: dict) -> list[str]:
    return [entry.get("content", "") for entry in result.get("logList") or []]


def parse_page_count(result: dict) -> int:
    """Return the snapshot's page count, which every "read" result repeats."""
    return int(result.get("totalNum") or 0)


@dataclass
class SystemLogSnapshot:
    """Pages read from one router log snapshot, kept across retries of a download."""

    session: Hashable = None
    page_count: int | None = None
    pages: dict[int, list[str]] = field(default_factory=dict)

    def reset(self, session: Hashable) -> None:
        self.session = session
        self.page_count = None
        self.pages = {}

    @property
    def started(self) -> bool:
        return self.page_count is not None

    def start(self, page_count: int, first_lines: list[str]) -> None:
        self.page_count = max(page_count, 1)
        self.pages[0] = first_lines

    def add_page(self, index: int, lines: list[str]) -> None:
        self.pages[index] = lines

    def unread_page_indexes(self) -> list[int]:
        return [
            index
            for index in range(self.page_count - 1, 0, -1)
            if index not in self.pages
        ]

    @property
    def complete(self) -> bool:
        return self.started and len(self.pages) >= self.page_count

    def newest_lines(self) -> list[str]:
        """Return lines from the newest pages, stopping at the first unread one."""
        if not self.started:
            return []
        newest_first = range(self.page_count - 1, -1, -1)
        run = list(takewhile(lambda index: index in self.pages, newest_first))
        return [line for index in reversed(run) for line in self.pages[index]]

    def result(self) -> SystemLog:
        return SystemLog(self.newest_lines(), self.complete)
