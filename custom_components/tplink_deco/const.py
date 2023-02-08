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
DEFAULT_TIMEOUT_ERROR_RETRIES = 1
DEFAULT_TIMEOUT_SECONDS = 30

DEVICE_TYPE_CLIENT = "client"
DEVICE_TYPE_DECO = "deco"

# Attributes
ATTR_BSSID_BAND2_4 = "bssid_band2_4"
ATTR_BSSID_BAND5 = "bssid_band5"
ATTR_CONNECTION_TYPE = "connection_type"
ATTR_DECO_DEVICE = "deco_device"
ATTR_DECO_MAC = "deco_mac"
ATTR_DEVICE_MODEL = "device_model"
ATTR_DEVICE_TYPE = "device_type"
ATTR_DOWN_KILOBYTES_PER_S = "down_kilobytes_per_s"
ATTR_INTERFACE = "interface"
ATTR_INTERNET_ONLINE = "internet_online"
ATTR_MASTER = "master"
ATTR_SIGNAL_BAND2_4 = "signal_band2_4"
ATTR_SIGNAL_BAND5 = "signal_band5"
ATTR_UP_KILOBYTES_PER_S = "up_kilobytes_per_s"

# Config
CONF_TIMEOUT_ERROR_RETRIES = "timeout_error_retries"
CONF_TIMEOUT_SECONDS = "timeout_seconds"
CONF_VERIFY_SSL = "verify_ssl"

# Signals
SIGNAL_CLIENT_ADDED = f"{DOMAIN}-client-added"
SIGNAL_DECO_ADDED = f"{DOMAIN}-deco-added"

# Services
SERVICE_REBOOT_DECO = "reboot_deco"

# Platforms
PLATFORMS = [DEVICE_TRACKER_DOMAIN]
