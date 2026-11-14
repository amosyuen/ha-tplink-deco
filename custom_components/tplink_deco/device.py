"""Build Home Assistant device information for TP-Link Deco nodes."""

from homeassistant.helpers import device_registry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import TpLinkDeco


def create_device_info(
    deco: TpLinkDeco | None,
    master_deco: TpLinkDeco | None,
    coordinator: DataUpdateCoordinator | None = None,
) -> DeviceInfo | None:
    """Return stable Deco device info, linking satellites to the master."""
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
    if master_deco is None or deco.mac == master_deco.mac:
        return device_info

    # Home Assistant 2025.12 predates via_device_id support.
    if "via_device_id" not in DeviceInfo.__annotations__:
        device_info["via_device"] = (DOMAIN, master_deco.mac)
    elif coordinator is not None and coordinator.config_entry is not None:
        master_device = device_registry.async_get(coordinator.hass).async_get_or_create(
            config_entry_id=coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, master_deco.mac)},
            name=f"{master_deco.name} Deco",
            manufacturer="TP-Link Deco",
            model=master_deco.device_model,
            sw_version=master_deco.sw_version,
            hw_version=master_deco.hw_version,
        )
        device_info["via_device_id"] = master_device.id

    return device_info
