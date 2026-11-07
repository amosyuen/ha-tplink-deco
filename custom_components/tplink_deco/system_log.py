"""Deco system log data and paging state, independent of transport."""

from dataclasses import dataclass
from dataclasses import field
from itertools import takewhile

# Deco system log levels, most severe first. Each includes the levels before it.
SYSTEM_LOG_LEVELS = {
    "ALERT": 1,
    "CRITICAL": 2,
    "ERROR": 3,
    "WARNING": 4,
    "NOTICE": 5,
    "INFO": 6,
    "DEBUG": 7,
    "ALL": 8,
}
DEFAULT_SYSTEM_LOG_LEVEL = "ALL"

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


@dataclass
class SystemLogPage:
    lines: list[str]
    total_pages: int


def parse_system_log_page(result: dict) -> SystemLogPage:
    """Return the lines and snapshot page count from a "read" result."""
    return SystemLogPage(
        [entry.get("content", "") for entry in result.get("logList") or []],
        int(result.get("totalNum") or 0),
    )


@dataclass
class SystemLogCheckpoint:
    """Pages read from one log snapshot, kept across retries of a download."""

    session: tuple | None = None
    total_pages: int | None = None
    pages: dict[int, list[str]] = field(default_factory=dict)

    def reset(self, session: tuple) -> None:
        self.session = session
        self.total_pages = None
        self.pages = {}

    def record_first_page(self, page: SystemLogPage) -> None:
        self.pages[0] = page.lines
        self.total_pages = max(page.total_pages, 1)

    def record_page(self, index: int, page: SystemLogPage) -> None:
        self.pages[index] = page.lines

    def unread_pages(self) -> list[int]:
        return [
            index
            for index in range(self.total_pages - 1, 0, -1)
            if index not in self.pages
        ]

    @property
    def complete(self) -> bool:
        return self.total_pages is not None and len(self.pages) >= self.total_pages

    def newest_lines(self) -> list[str]:
        """Return lines from the newest pages, stopping at the first unread one."""
        if self.total_pages is None:
            return []
        newest_first = range(self.total_pages - 1, -1, -1)
        run = list(takewhile(lambda index: index in self.pages, newest_first))
        return [line for index in reversed(run) for line in self.pages[index]]

    def result(self) -> SystemLog:
        return SystemLog(self.newest_lines(), self.complete)
