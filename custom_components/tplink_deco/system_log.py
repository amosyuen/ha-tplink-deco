"""Deco system log concepts, independent of transport."""

from enum import IntEnum


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
