"""Validate optional read-only Deco firmware diagnostics without logging payloads."""

import re

from homeassistant.const import MAX_LENGTH_STATE_STATE

DiagnosticValue = str | bool | int

_MAC_PATTERN = re.compile(
    r"[0-9a-f]{12}|[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}", re.I
)
_TOPOLOGY_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}")


def _text_value(value: object) -> str | None:
    """Accept nonempty, printable text that fits a Home Assistant state."""
    if (
        isinstance(value, str)
        and 0 < len(value) <= MAX_LENGTH_STATE_STATE
        and value.isprintable()
        and value.strip()
    ):
        return value
    return None


def _flag_value(value: object) -> bool | None:
    """Accept firmware booleans and integer flags without truthy coercion."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return None


def _signal_value(value: object) -> int | None:
    """Accept bounded integer levels without rescaling firmware measurements."""
    level = value
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= 10
    ):
        level = int(value)
    if type(level) is int and 0 <= level <= 2**31 - 1:
        return level
    return None


def _mac_value(value: object) -> str | None:
    """Validate a network identifier while preserving its firmware formatting."""
    if not isinstance(value, str) or not _MAC_PATTERN.fullmatch(value):
        return None
    digits = value.replace(":", "").replace("-", "").lower()
    return None if digits in {"000000000000", "ffffffffffff"} else value


def _topology_value(value: object) -> str | None:
    """Expose confirmed auto or fixed topology without inventing missing data."""
    if not isinstance(value, dict):
        return None
    auto = _flag_value(value.get("auto"))
    if auto is None:
        return None
    target = value.get("device_id")
    if target is None or target == "":
        return "auto" if auto else "fixed"
    if not isinstance(target, str) or not _TOPOLOGY_TARGET.fullmatch(target):
        return None
    return "auto" if auto else target


def parse_node_diagnostics(data: dict[str, object]) -> dict[str, DiagnosticValue]:
    """Select usable optional firmware values for the opt-in entity states."""
    values: dict[str, DiagnosticValue] = {}
    group_status = _text_value(data.get("group_status"))
    if group_status is not None:
        values["group_status"] = group_status
        if group_status.lower() in ("offline", "disconnected"):
            return values
    for key in ("nickname", "role", "interface"):
        text = _text_value(data.get(key))
        if text is not None:
            values[key] = text

    message = data.get("inet_error_msg")
    if isinstance(message, str):
        text = _text_value(" ".join(message.split())[:MAX_LENGTH_STATE_STATE])
        if text is not None:
            values["inet_error_msg"] = text

    internet = data.get("inet_status")
    if (text := _text_value(internet)) is not None:
        values["inet"] = text
    elif isinstance(internet, int) and internet in (0, 1):
        values["inet"] = internet

    role = values.get("role")
    if role in ("master", "slave"):
        values["master"] = role == "master"
        values["slave"] = role == "slave"

    for key in ("client_mesh", "set_gateway_support"):
        flag = _flag_value(data.get(key))
        if flag is not None:
            values[key] = flag

    for key in ("previous", "bssid_sta_2g", "bssid_sta_5g"):
        address = _mac_value(data.get(key))
        if address is not None:
            values[key] = address

    signal = data.get("signal_level")
    if isinstance(signal, dict):
        for band, key in (("band2_4", "signal_level24"), ("band5", "signal_level5")):
            level = _signal_value(signal.get(band))
            if level is not None:
                values[key] = level
                values.setdefault("signal_level", level)

    raw_topology = data.get("topology")
    topology = _topology_value(raw_topology)
    if topology is not None:
        values["topology"] = topology
    elif role == "master" and (raw_topology is None or raw_topology == {}):
        # The confirmed mesh master is the root node, but an absent mode
        # does not establish "fixed" topology as the legacy extra branch did.
        values["topology"] = "root"
    return values
