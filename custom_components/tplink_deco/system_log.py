"""System-log download limits and severity levels for TP-Link Deco."""

from enum import IntEnum

MAX_SYSTEM_LOG_BYTES = 8 * 1024 * 1024


class SystemLogLevel(IntEnum):
    """Router log severity threshold, where ALL disables severity filtering."""

    ALERT = 1
    CRITICAL = 2
    ERROR = 3
    WARNING = 4
    NOTICE = 5
    INFO = 6
    DEBUG = 7
    ALL = 8
