"""TP-Link Deco."""

from homeassistant.helpers import device_registry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import TpLinkDeco


def create_device_info(
    deco: TpLinkDeco,
    master_deco: TpLinkDeco,
    coordinator: DataUpdateCoordinator | None = None,
) -> DeviceInfo:
    """Return device info."""
    if deco is None:
        return None
    device_info = DeviceInfo(
        identifiers={(DOMAIN, deco.mac)},
        name=f"{deco.name} Deco",
        manufacturer="TP-Link Deco",
        model=deco.device_model,
        sw_version=deco.sw_version,
        hw_version=deco.hw_version,
    )
    if master_deco is not None and deco != master_deco:
        if not hasattr(device_registry, "async_get_device_id_by_identifier"):
            # Compatibility with Home Assistant versions before via_device_id.
            device_info["via_device"] = (DOMAIN, master_deco.mac)
        elif coordinator is not None:
            master_device_id = (
                device_registry.async_get(coordinator.hass)
                .async_get_or_create(
                    config_entry_id=coordinator.config_entry.entry_id,
                    identifiers={(DOMAIN, master_deco.mac)},
                    name=f"{master_deco.name} Deco",
                    manufacturer="TP-Link Deco",
                    model=master_deco.device_model,
                    sw_version=master_deco.sw_version,
                    hw_version=master_deco.hw_version,
                )
                .id
            )
            device_info["via_device_id"] = master_device_id

    return device_info
