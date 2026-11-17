"""Regression tests for explicit SSID consent on existing Deco WiFi sensors."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
import voluptuous as vol

from custom_components.tplink_deco import config_flow
from custom_components.tplink_deco.binary_sensor import TplinkDecoWirelessBinarySensor
from custom_components.tplink_deco.const import CONF_EXPOSE_WIFI_SSIDS
from custom_components.tplink_deco.const import DEFAULT_EXPOSE_WIFI_SSIDS
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.wireless import TplinkDecoWirelessUpdateCoordinator
from custom_components.tplink_deco.wireless import WIRELESS_NETWORKS
from custom_components.tplink_deco.wireless import parse_wireless_ssids
from custom_components.tplink_deco.wireless import wireless_ssid_attributes

PRIVATE_SSID = "Private-Network"
PRIVATE_PASSWORD = "TEST_ONLY_WIFI_PASSWORD"
NETWORK_RESPONSE = {
    "band2_4": {
        "host": {"enable": True, "ssid": "SG9tZQ==", "password": PRIVATE_PASSWORD},
        "guest": {"enable": True, "ssid": "Guests"},
    },
    "band5_1": {"host": {"enable": True, "ssid": "SG9tZS01Rw=="}},
    "iot": {"host": {"enable": False, "ssid": "Q2FzYS1Jb1Q=", "psk": PRIVATE_PASSWORD}},
    "unknown": {"ssid": PRIVATE_SSID},
}


def _coordinator(
    *responses: object, consent: bool = False
) -> TplinkDecoWirelessUpdateCoordinator:
    """Create an isolated wireless coordinator without router or HA I/O."""
    coordinator = object.__new__(TplinkDecoWirelessUpdateCoordinator)
    coordinator.api = MagicMock()
    coordinator.api.async_get_wireless = AsyncMock(side_effect=responses)
    coordinator._deco_coordinator = MagicMock(paused=False)
    coordinator.expose_ssids = consent
    coordinator.data = {}
    coordinator.ssids = {}
    coordinator._next_retry = 0.0
    coordinator._consecutive_failures = 0
    return coordinator


def _sensor(
    *, consent: bool, names: dict[str, dict[str, str]]
) -> TplinkDecoWirelessBinarySensor:
    """Create a sensor with a supported current master and stub coordinator."""
    sensor = object.__new__(TplinkDecoWirelessBinarySensor)
    sensor.entity_description = next(
        network for network in WIRELESS_NETWORKS if network.key == "guest"
    )
    sensor.coordinator = MagicMock()
    sensor.coordinator.expose_ssids = consent
    sensor.coordinator.ssids = names
    sensor.coordinator.data = {"guest": True}
    sensor.coordinator.last_update_success = True
    sensor._master_deco = SimpleNamespace(mac="02:00:00:00:63:01")
    sensor._deco_coordinator = MagicMock()
    sensor._deco_coordinator.data.master_deco.mac = sensor._master_deco.mac
    return sensor


def _flow(kind: str):
    """Prepare setup or options flows with mocked Home Assistant services."""
    entry = SimpleNamespace(entry_id="entry-one", data={CONF_SCAN_INTERVAL: 30})
    if kind == "user":
        flow = config_flow.TplinkDecoFlowHandler()
        flow.handler = DOMAIN
    else:
        flow = config_flow.TplinkDecoOptionsFlowHandler(entry)
        flow.handler = entry.entry_id
    flow.flow_id = "test-ssid-flow"
    flow.hass = MagicMock()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    return flow


def _form_input(choice: object) -> dict[str, object]:
    """Create a synthetic form payload without actual router credentials."""
    return {
        CONF_HOST: "http://192.0.2.1",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "test-only",
        CONF_SCAN_INTERVAL: "30",
        CONF_EXPOSE_WIFI_SSIDS: choice,
    }


@pytest.mark.parametrize(
    "stored, expected", [(None, False), (False, False), (True, True), ("true", False)]
)
def test_ssid_option_defaults_to_explicit_boolean_consent(
    stored: object, expected: bool
) -> None:
    """Legacy or invalid stored consent must never enable SSID exposure."""
    data = {} if stored is None else {CONF_EXPOSE_WIFI_SSIDS: stored}
    schema = vol.Schema(config_flow._get_schema(data))
    key = next(
        marker for marker in schema.schema if marker.schema == CONF_EXPOSE_WIFI_SSIDS
    )

    assert DEFAULT_EXPOSE_WIFI_SSIDS is False
    assert key.default() is expected
    result = _BaseFlowManagerView(MagicMock())._prepare_result_json(
        {"type": FlowResultType.FORM, "data_schema": schema}
    )
    assert json.dumps(result)
    assert any(
        field["name"] == CONF_EXPOSE_WIFI_SSIDS for field in result["data_schema"]
    )


@pytest.mark.parametrize("invalid", ["true", "false", None, 1, 0, [], {}])
@pytest.mark.parametrize("kind", ["user", "options"])
@pytest.mark.asyncio
async def test_ssid_option_rejects_non_boolean_before_network(
    kind: str, invalid: object
) -> None:
    """Reject coerced or malformed consent without calling the Deco API."""
    flow = _flow(kind)
    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock()
    ) as credentials:
        result = await (
            flow.async_step_user(_form_input(invalid))
            if kind == "user"
            else flow.async_step_init(_form_input(invalid))
        )
    assert result["type"] == "form"
    assert result["errors"] == {CONF_EXPOSE_WIFI_SSIDS: "invalid_expose_wifi_ssids"}
    credentials.assert_not_awaited()
    flow.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize("consent", [False, True])
@pytest.mark.parametrize("kind", ["user", "options"])
@pytest.mark.asyncio
async def test_ssid_option_is_persisted_in_both_flows(kind: str, consent: bool) -> None:
    """Preserve the boolean choice and the other setup configuration."""
    flow = _flow(kind)
    with patch.object(
        config_flow, "_async_test_credentials", AsyncMock(return_value={})
    ):
        result = await (
            flow.async_step_user(_form_input(consent))
            if kind == "user"
            else flow.async_step_init(_form_input(consent))
        )
    assert result["type"] == "create_entry"
    saved = (
        flow.async_create_entry.call_args.kwargs["data"]
        if kind == "user"
        else flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    )
    assert saved[CONF_EXPOSE_WIFI_SSIDS] is consent
    assert saved[CONF_SCAN_INTERVAL] == 30


def test_ssid_parser_limits_firmware_fields_and_decodes_names() -> None:
    """Parse Base64 and plain network names without retaining credentials."""
    result = parse_wireless_ssids(NETWORK_RESPONSE)
    assert result == {
        "main": {"band2_4": "Home", "band5_1": "Home-5G"},
        "guest": {"band2_4": "Guests"},
        "iot": {"iot": "Casa-IoT"},
    }
    assert PRIVATE_PASSWORD not in repr(result)
    assert PRIVATE_SSID not in repr(result)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"band2_4": {"guest": {"ssid": ""}}},
        {"band2_4": {"guest": {"ssid": [PRIVATE_SSID]}}},
        {"band2_4": {"guest": {"ssid": 12}}},
        {"band2_4": {"guest": {"password": PRIVATE_PASSWORD}}},
    ],
)
def test_ssid_parser_rejects_missing_and_malformed_names(payload: object) -> None:
    """Do not expose unknown or malformed SSIDs."""
    assert parse_wireless_ssids(payload) == {}


def test_ssid_parser_rejects_untrusted_band_attribute_suffixes() -> None:
    """Only compact numeric band identifiers can become attribute names."""
    response = {
        "band2_4": {"host": {"enable": True, "ssid": "SG9tZQ=="}},
        "band6_1": {"host": {"enable": True, "ssid": "SG9tZS02Rw=="}},
        "band5_private/key": {"host": {"enable": True, "ssid": PRIVATE_SSID}},
        "band5_bad": {"host": {"enable": True, "ssid": PRIVATE_SSID}},
        "band" + "9" * 64: {"host": {"enable": True, "ssid": PRIVATE_SSID}},
    }

    assert parse_wireless_ssids(response) == {
        "main": {"band2_4": "Home", "band6_1": "Home-6G"}
    }
    assert wireless_ssid_attributes(parse_wireless_ssids(response)["main"]) == {
        "ssid_band2_4": "Home",
        "ssid_band6_1": "Home-6G",
    }


def test_ssid_attributes_collapse_shared_names_or_distinguish_bands() -> None:
    """Use a single SSID for matching bands, otherwise stable per-band keys."""
    assert wireless_ssid_attributes({}) == {}
    assert wireless_ssid_attributes({"band2_4": "Home", "band5": "Home"}) == {
        "ssid": "Home"
    }
    assert wireless_ssid_attributes({"band5_1": "Home-5G", "band2_4": "Home"}) == {
        "ssid_band2_4": "Home",
        "ssid_band5_1": "Home-5G",
    }


@pytest.mark.asyncio
async def test_ssids_are_absent_by_default_and_only_retained_with_consent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Opted-out entries retain boolean network state but never store names."""
    caplog.set_level(logging.DEBUG)
    default = _coordinator(NETWORK_RESPONSE)
    enabled = _coordinator(NETWORK_RESPONSE, consent=True)

    assert await default._async_update_data() == {
        "main": True,
        "guest": True,
        "iot": False,
    }
    assert default.ssids == {}
    assert await enabled._async_update_data() == {
        "main": True,
        "guest": True,
        "iot": False,
    }
    assert enabled.ssids["guest"] == {"band2_4": "Guests"}
    assert enabled.ssids["main"] == {"band2_4": "Home", "band5_1": "Home-5G"}
    assert PRIVATE_PASSWORD not in caplog.text
    assert "Guests" not in caplog.text


@pytest.mark.asyncio
async def test_ssid_names_are_replaced_after_a_successful_response() -> None:
    """An absent or invalid network cannot keep stale private attributes."""
    coordinator = _coordinator(
        NETWORK_RESPONSE,
        {"band2_4": {"guest": {"enable": True}}},
        consent=True,
    )
    await coordinator._async_update_data()
    assert coordinator.ssids["main"]
    assert await coordinator._async_update_data() == {"guest": True}
    assert coordinator.ssids == {}


@pytest.mark.parametrize("consent", [False, True])
def test_wireless_sensor_hides_or_exposes_names_only_with_consent(
    consent: bool,
) -> None:
    """Existing entity identities remain unchanged when consent changes."""
    sensor = _sensor(consent=consent, names={"guest": {"band2_4": "Guests"}})
    assert sensor.extra_state_attributes == ({"ssid": "Guests"} if consent else None)


@pytest.mark.asyncio
async def test_ssid_decoder_failures_are_sanitized_and_use_wireless_backoff(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Avoid partial state, reset or private logs when name parsing fails."""
    coordinator = _coordinator(
        NETWORK_RESPONSE,
        NETWORK_RESPONSE,
        NETWORK_RESPONSE,
        NETWORK_RESPONSE,
        consent=True,
    )
    previous_states = await coordinator._async_update_data()
    coordinator.data = previous_states
    previous_names = {
        key: dict(bands) for key, bands in coordinator.ssids.items()
    }
    caplog.set_level(logging.DEBUG)

    with patch(
        "custom_components.tplink_deco.wireless.monotonic",
        side_effect=[100.0, 110.0, 120.0, 411.0],
    ):
        with patch(
            "custom_components.tplink_deco.wireless.decode_name_with_fallback",
            side_effect=ValueError(PRIVATE_PASSWORD),
        ):
            for attempt in (1, 2):
                with pytest.raises(
                    UpdateFailed, match="Unable to read optional wireless status"
                ) as raised:
                    await coordinator._async_update_data()
                assert raised.value.__cause__ is None
                assert raised.value.__suppress_context__
                assert coordinator._consecutive_failures == attempt
                assert coordinator.ssids == previous_names
                assert coordinator.data == previous_states

            assert coordinator._next_retry == 410.0
            with pytest.raises(UpdateFailed, match="retry is deferred"):
                await coordinator._async_update_data()
            assert coordinator.api.async_get_wireless.await_count == 3

        assert await coordinator._async_update_data() == previous_states
        assert coordinator.ssids == previous_names
        assert coordinator._consecutive_failures == 0
        assert coordinator._next_retry == 0.0

    assert PRIVATE_PASSWORD not in caplog.text


def test_former_master_or_unavailable_network_does_not_expose_names() -> None:
    """Do not show a network name if the owning master is no longer current."""
    sensor = _sensor(consent=True, names={"guest": {"band2_4": "Guests"}})
    sensor._deco_coordinator.data.master_deco.mac = "02:00:00:00:63:02"
    assert sensor.extra_state_attributes is None
    sensor._deco_coordinator.data.master_deco.mac = sensor._master_deco.mac
    sensor.coordinator.data = {}
    assert sensor.extra_state_attributes is None
