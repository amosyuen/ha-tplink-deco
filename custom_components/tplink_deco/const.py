"""Constants for TP-Link Deco."""

from homeassistant.components.device_tracker.const import (
    DEFAULT_CONSIDER_HOME as DEFAULT_CONSIDER_HOME_SPAN,
)

# Base component constants
DOMAIN = "tplink_deco"

COORDINATOR_CLIENTS_KEY = "clients"
COORDINATOR_DECOS_KEY = "decos"

DEFAULT_CONSIDER_HOME = DEFAULT_CONSIDER_HOME_SPAN.total_seconds()
DEFAULT_DECO_POSTFIX = "Deco"
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT_ERROR_RETRIES = 1
DEFAULT_TIMEOUT_SECONDS = 30

DEVICE_TYPE_CLIENT = "client"
DEVICE_TYPE_DECO = "deco"

# Wireless networks exposed as read-only on/off status sensors. All three live
# inside the "wlan" form on the Deco X50 (guest/iot are NOT separate forms).
# "paths" point at the section(s) whose "enable" flag we read, relative to the
# wlan result:
#   main  -> band2_4.host / band5_1.host
#   guest -> band2_4.guest / band5_1.guest
#   iot   -> iot.host
# "band*" is a trailing-wildcard match so both 2.4G and 5G bands are covered.
# NOTE: enabling/disabling is not possible on the X50 firmware (the wireless
# write handler errors server-side), so these are status-only.
WIFI_NETWORKS = [
    {
        "key": "main",
        "form": "wlan",
        "name": "Main WiFi",
        "icon": "mdi:wifi",
        "paths": [["band*", "host"]],
    },
    {
        "key": "guest",
        "form": "wlan",
        "name": "Guest WiFi",
        "icon": "mdi:wifi-lock-open",
        "paths": [["band*", "guest"]],
    },
    {
        "key": "iot",
        "form": "wlan",
        "name": "IoT WiFi",
        "icon": "mdi:home-automation",
        "paths": [["iot", "host"]],
    },
]

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
ATTR_UI_DEVICE_NAME = "ui_device_name"

# Config
CONF_CLIENT_PREFIX = "client_prefix"
CONF_CLIENT_POSTFIX = "client_postfix"
CONF_DECO_PREFIX = "deco_prefix"
CONF_DECO_POSTFIX = "deco_postfix"
CONF_TIMEOUT_ERROR_RETRIES = "timeout_error_retries"
CONF_TIMEOUT_SECONDS = "timeout_seconds"
CONF_VERIFY_SSL = "verify_ssl"

# Signals
SIGNAL_CLIENT_ADDED = f"{DOMAIN}-client-added"
SIGNAL_DECO_ADDED = f"{DOMAIN}-deco-added"

# Services
SERVICE_REBOOT_DECO = "reboot_deco"
SERVICE_PAUSE_POLLING = "pause_polling"
SERVICE_RESUME_POLLING = "resume_polling"
# Platforms
PLATFORMS = ["device_tracker", "sensor", "binary_sensor", "switch", "select"]
