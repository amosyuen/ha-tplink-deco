"""Privacy-preserving Home Assistant diagnostics for the TP-Link Deco integration."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import COORDINATOR_WIRELESS_KEY
from .const import DOMAIN
from .coordinator import CoordinatorHealth
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator


def _health_snapshot(health: CoordinatorHealth) -> dict[str, Any]:
    """Export only measured health values, never API exception messages."""
    last_error = health.last_error
    if (
        not isinstance(last_error, str)
        or len(last_error) > 80
        or (last_error != "0" and not last_error.isidentifier())
    ):
        last_error = "UnknownError"

    return {
        "last_successful_update": (
            health.last_successful_update.isoformat()
            if health.last_successful_update is not None
            else None
        ),
        "response_time_ms": health.response_time_ms,
        "timeout_count": health.timeout_count,
        "consecutive_failures": health.consecutive_failures,
        "last_error": last_error,
    }


def _coordinator_snapshot(
    coordinator: TplinkDecoUpdateCoordinator | TplinkDecoClientUpdateCoordinator,
) -> dict[str, Any]:
    """Describe existing coordinator health without triggering an API refresh."""
    update_interval = coordinator.update_interval
    return {
        **_health_snapshot(coordinator.health),
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": (
            update_interval.total_seconds() if update_interval is not None else None
        ),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return anonymized, JSON-safe diagnostics for one configuration entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    deco_coordinator: TplinkDecoUpdateCoordinator = data[COORDINATOR_DECOS_KEY]
    client_coordinator: TplinkDecoClientUpdateCoordinator = data[
        COORDINATOR_CLIENTS_KEY
    ]

    deco_data = deco_coordinator.data
    decos = deco_data.decos if deco_data is not None else {}
    clients = client_coordinator.data or {}

    result = {
        "schema_version": 1,
        "deco_coordinator": {
            **_coordinator_snapshot(deco_coordinator),
            "paused": deco_coordinator.paused,
            "device_list_interval_seconds": (
                deco_coordinator.device_list_interval_seconds
            ),
            "known_decos": len(decos),
            "online_decos": sum(bool(deco.online) for deco in decos.values()),
            "master_present": (
                deco_data is not None and deco_data.master_deco is not None
            ),
        },
        "client_coordinator": {
            **_coordinator_snapshot(client_coordinator),
            "query_mode": client_coordinator.client_query_mode,
            "backoff_remaining_seconds": client_coordinator.remaining_backoff_seconds,
            "has_successful_refresh": client_coordinator.has_successful_refresh,
            "known_clients": len(clients),
            "online_clients": sum(bool(client.online) for client in clients.values()),
        },
    }
    wireless_coordinator = data.get(COORDINATOR_WIRELESS_KEY)
    if wireless_coordinator is not None:
        result["wireless_coordinator"] = {
            "last_update_success": wireless_coordinator.last_update_success,
            "retry_remaining_seconds": wireless_coordinator.retry_remaining_seconds,
            "available_networks": sorted(wireless_coordinator.data or {}),
        }
    return result
