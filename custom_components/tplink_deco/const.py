"""Constants for TP-Link Deco."""
from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.components.device_tracker.const import (
    DEFAULT_CONSIDER_HOME as DEFAULT_CONSIDER_HOME_SPAN,
)

# Base component constants
DOMAIN = "tplink_deco"

COORDINATOR_CLIENTS_KEY = "clients"
COORDINATOR_DECOS_KEY = "decos"

DEFAULT_CONSIDER_HOME = DEFAULT_CONSIDER_HOME_SPAN.total_seconds()
DEFAULT_SCAN_INTERVAL = 30

DEVICE_CLASS_CLIENT = "client"
DEVICE_CLASS_DECO = "deco"

# Config
CONFIG_VERIFY_SSL = "verify_ssl"

# Signals
SIGNAL_CLIENT_ADDED = f"{DOMAIN}-client-added"
SIGNAL_DECO_ADDED = f"{DOMAIN}-deco-added"

# Services
SERVICE_REBOOT_DECO = "reboot_deco"

# Platforms
PLATFORMS = [DEVICE_TRACKER_DOMAIN]
