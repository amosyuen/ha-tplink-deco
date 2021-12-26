"""Constants for TP-Link Deco."""

from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN

# Base component constants
NAME = "TP-Link Deco"
DOMAIN = "tp_link_deco"
VERSION = "0.0.0"

ISSUE_URL = "https://github.com/amosyuen/tp-link-deco/issues"

# Signals
SIGNAL_CLIENT_ADDED = f"{DOMAIN}-client-added"

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
