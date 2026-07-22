"""Diagnostics support for TP-Link Deco."""

from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .coordinator import TpLinkDeco
from .coordinator import TpLinkDecoClient
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    "access_token",
    "cookie",
    "refresh_token",
    "secret",
    "session",
    "session_id",
    "stok",
    "token",
}


def _coordinator_diagnostics(coordinator) -> dict[str, Any]:
    """Return non-sensitive coordinator state."""
    update_interval = coordinator.update_interval
    return {
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": (
            update_interval.total_seconds() if update_interval is not None else None
        ),
    }


def _deco_diagnostics(deco: TpLinkDeco, identifier: str) -> dict[str, Any]:
    """Return diagnostics for a Deco without personal identifiers."""
    return {
        "id": identifier,
        "device_model": deco.device_model,
        "hardware_version": deco.hw_version,
        "software_version": deco.sw_version,
        "online": deco.online,
        "internet_online": deco.internet_online,
        "master": deco.master,
        "connection_type": deco.connection_type,
        "interface": deco.interface,
        "signal_2_4_ghz": deco.signal_band2_4,
        "signal_5_ghz": deco.signal_band5,
        "backhaul_speed": deco.backhaul_speed,
        "backhaul_max_speed": deco.backhaul_max_speed,
        "cpu_usage": deco.cpu_usage,
        "cpu_usage_raw": deco.cpu_usage_raw,
        "memory_usage": deco.mem_usage,
        "memory_usage_raw": deco.mem_usage_raw,
    }


def _client_diagnostics(
    client: TpLinkDecoClient,
    identifier: str,
    deco_ids: dict[str, str],
) -> dict[str, Any]:
    """Return diagnostics for a client without personal identifiers."""
    last_activity: datetime | None = client.last_activity
    return {
        "id": identifier,
        "deco_id": deco_ids.get(client.deco_mac, "unassigned"),
        "online": client.online,
        "connection_type": client.connection_type,
        "interface": client.interface,
        "down_kilobytes_per_s": client.down_kilobytes_per_s,
        "up_kilobytes_per_s": client.up_kilobytes_per_s,
        "last_activity": last_activity.isoformat() if last_activity else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    deco_coordinator: TplinkDecoUpdateCoordinator = data[COORDINATOR_DECOS_KEY]
    client_coordinator: TplinkDecoClientUpdateCoordinator = data[
        COORDINATOR_CLIENTS_KEY
    ]

    decos = sorted(deco_coordinator.data.decos.items())
    clients = sorted(client_coordinator.data.items())
    deco_ids = {mac: f"deco_{index}" for index, (mac, _) in enumerate(decos, 1)}

    return {
        "config_entry": {
            "version": config_entry.version,
            "minor_version": config_entry.minor_version,
            "data": async_redact_data(config_entry.data, TO_REDACT),
            "options": async_redact_data(config_entry.options, TO_REDACT),
        },
        "deco_coordinator": {
            **_coordinator_diagnostics(deco_coordinator),
            "paused": deco_coordinator.paused,
            "master_deco_id": (
                deco_ids.get(deco_coordinator.data.master_deco.mac)
                if deco_coordinator.data.master_deco is not None
                else None
            ),
            "decos": [_deco_diagnostics(deco, deco_ids[mac]) for mac, deco in decos],
        },
        "client_coordinator": {
            **_coordinator_diagnostics(client_coordinator),
            "clients": [
                _client_diagnostics(client, f"client_{index}", deco_ids)
                for index, (_, client) in enumerate(clients, 1)
            ],
        },
    }
