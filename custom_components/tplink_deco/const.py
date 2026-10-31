"""Constants for TP-Link Deco."""

from homeassistant.components.device_tracker.const import (
    DEFAULT_CONSIDER_HOME as DEFAULT_CONSIDER_HOME_SPAN,
)

# Base component constants
DOMAIN = "tplink_deco"

COORDINATOR_CLIENTS_KEY = "clients"
COORDINATOR_DECOS_KEY = "decos"
LOG_FORWARDER_KEY = "log_forwarder"

DEFAULT_CONSIDER_HOME = DEFAULT_CONSIDER_HOME_SPAN.total_seconds()
DEFAULT_DECO_POSTFIX = "Deco"
DEFAULT_LINK_CLIENT_DEVICES = True
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT_ERROR_RETRIES = 1
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_SYSLOG_PORT = 514
DEFAULT_SYSLOG_LOG_LEVEL = "ALL"
DEFAULT_SYSLOG_SCAN_INTERVAL = 300

DEVICE_TYPE_CLIENT = "client"
DEVICE_TYPE_DECO = "deco"

# Attributes
ATTR_BSSID_BAND2_4 = "bssid_band2_4"
ATTR_BSSID_BAND5 = "bssid_band5"
ATTR_BACKHAUL_BSSID_BAND2_4 = "backhaul_bssid_band2_4"
ATTR_BACKHAUL_BSSID_BAND5 = "backhaul_bssid_band5"
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
CONF_DEVICE_LIST_INTERVAL = "device_list_interval"
CONF_LINK_CLIENT_DEVICES = "link_client_devices"
CONF_TIMEOUT_ERROR_RETRIES = "timeout_error_retries"
CONF_TIMEOUT_SECONDS = "timeout_seconds"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SYSLOG_HOST = "syslog_host"
CONF_SYSLOG_PORT = "syslog_port"
CONF_SYSLOG_PROTOCOL = "syslog_protocol"
CONF_SYSLOG_LOG_LEVEL = "syslog_log_level"
CONF_SYSLOG_SCAN_INTERVAL = "syslog_scan_interval"

SYSLOG_PROTOCOL_UDP = "udp"
SYSLOG_PROTOCOL_TCP = "tcp"

# Signals
SIGNAL_CLIENT_ADDED = f"{DOMAIN}-client-added"
SIGNAL_DECO_ADDED = f"{DOMAIN}-deco-added"

# Services
SERVICE_REBOOT_DECO = "reboot_deco"
SERVICE_PAUSE_POLLING = "pause_polling"
SERVICE_RESUME_POLLING = "resume_polling"
SERVICE_DOWNLOAD_SYSTEM_LOG = "download_system_log"

# Platforms
PLATFORMS = [
    "device_tracker",
    "sensor",
    "binary_sensor",
    "switch",
    "select",
    "button",
]
