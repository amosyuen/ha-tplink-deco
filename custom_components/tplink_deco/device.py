"""TP-Link Deco."""
from homeassistant.const import ATTR_VIA_DEVICE
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .coordinator import TpLinkDeco


def create_device_info(deco: TpLinkDeco, master_deco: TpLinkDeco) -> DeviceInfo:
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
        device_info[ATTR_VIA_DEVICE] = (DOMAIN, master_deco.mac)

    return device_info
