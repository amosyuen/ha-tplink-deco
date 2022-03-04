"""Constants for TP-Link Deco."""
from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.components.device_tracker.const import (
    DEFAULT_CONSIDER_HOME as DEFAULT_CONSIDER_HOME_SPAN,
)

# Base component constants
NAME = "TP-Link Deco"
DOMAIN = "tplink_deco"
VERSION = "0.0.0"

ISSUE_URL = "https://github.com/amosyuen/ha-tplink-deco/issues"

DEFAULT_CONSIDER_HOME = DEFAULT_CONSIDER_HOME_SPAN.total_seconds()
DEFAULT_SCAN_INTERVAL = 30

DEVICE_CLASS_CLIENT = "client"
DEVICE_CLASS_DECO = "deco"

# Signals
SIGNAL_CLIENT_ADDED = f"{DOMAIN}-client-added"
SIGNAL_DECO_ADDED = f"{DOMAIN}-deco-added"

# Platforms
PLATFORMS = [DEVICE_TRACKER_DOMAIN]

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
