"""Check Home Assistant form translation parity for the fork's supported locales."""

import json
from pathlib import Path
from typing import Any

from homeassistant.components.device_tracker.const import CONF_SCAN_INTERVAL
import pytest

INTEGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "tplink_deco"
)


def _load_labels(file_name: str) -> dict[str, Any]:
    """Load a checked-in integration translation file as a JSON dictionary."""
    file_path = INTEGRATION_PATH / file_name
    with file_path.open(encoding="utf-8") as content:
        result = json.load(content)
    assert isinstance(result, dict), f"{file_name} must contain a JSON object"
    return result


def _leaf_paths(
    data: dict[str, Any],
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    """Return all nested translation leaf paths, retaining namespaced keys."""
    paths: set[tuple[str, ...]] = set()
    for field_name, field_value in data.items():
        field_path = (*prefix, field_name)
        if isinstance(field_value, dict):
            paths.update(_leaf_paths(field_value, field_path))
        else:
            paths.add(field_path)
    return paths


@pytest.mark.parametrize("locale", ["en", "nl", "sk", "sv", "nb", "fr"])
def test_canonical_translation_keys_are_present_in_locale(locale: str) -> None:
    """Avoid silently falling back on missing setup, options or entity labels."""
    source = _load_labels("strings.json")
    translated = _load_labels(f"translations/{locale}.json")

    missing = _leaf_paths(source) - _leaf_paths(translated)

    assert not missing, (
        f"The {locale} translation is missing canonical keys: "
        f"{sorted('.'.join(path) for path in missing)}"
    )


@pytest.mark.parametrize("step_name", [("config", "user"), ("options", "init")])
def test_scan_interval_translation_matches_real_home_assistant_form_key(
    step_name: tuple[str, str],
) -> None:
    """Label the persisted scan selector with its actual Home Assistant key."""
    section_name, form_step = step_name
    assert CONF_SCAN_INTERVAL == "interval_seconds"

    for file_name in (
        "strings.json",
        "translations/en.json",
        "translations/nl.json",
        "translations/sk.json",
        "translations/sv.json",
        "translations/nb.json",
        "translations/fr.json",
    ):
        labels = _load_labels(file_name)
        form_labels = labels[section_name]["step"][form_step]["data"]

        assert (
            CONF_SCAN_INTERVAL in form_labels
        ), f"{file_name} is missing the {section_name} scan-interval label"
        assert form_labels[CONF_SCAN_INTERVAL]


def test_dutch_legacy_labels_and_validation_messages_remain_available() -> None:
    """Keep previously shipped Dutch metadata and form errors unchanged."""
    dutch = _load_labels("translations/nl.json")

    assert dutch["config"]["step"]["user"]["title"] == "TP-Link Deco"
    assert dutch["options"]["step"]["init"]["title"] == "TP-Link Deco"
    for section_name in ("config", "options"):
        assert "invalid_scan_interval" in dutch[section_name]["error"]
        assert "invalid_device_list_interval" in dutch[section_name]["error"]
        assert "invalid_expose_wifi_ssids" in dutch[section_name]["error"]


def test_norwegian_existing_labels_and_metadata_are_retained() -> None:
    """Preserve shipped Norwegian consent text, titles and mobile sensor name."""
    norwegian = _load_labels("translations/nb.json")

    assert norwegian["config"]["step"]["user"]["title"] == "TP-Link Deco"
    assert norwegian["config"]["step"]["reauth_confirm"]["title"] == "TP-Link Deco"
    assert norwegian["options"]["step"]["init"]["title"] == "TP-Link Deco"
    assert norwegian["entity"]["sensor"]["mobile_data_usage"]["name"] == "Mobildatabruk"

    for section_name, step_name in (("config", "user"), ("options", "init")):
        labels = norwegian[section_name]["step"][step_name]["data"]
        assert labels["link_client_devices"] == (
            "Koble klientsporere til enheter via MAC-adresse"
        )
        assert labels["expose_wifi_ssids"] == (
            "Vis Wi-Fi-nettverksnavn på Wi-Fi-statussensorene"
        )
        assert norwegian[section_name]["error"]["invalid_expose_wifi_ssids"] == (
            "Velg på eller av for å vise Wi-Fi-nettverksnavn."
def test_french_existing_labels_and_metadata_are_retained() -> None:
    """Preserve existing French consent labels, titles and sensor names."""
    french = _load_labels("translations/fr.json")

    assert french["config"]["step"]["user"]["title"] == "TP-Link Deco"
    assert french["options"]["step"]["init"]["title"] == "TP-Link Deco"
    assert french["config"]["step"]["reauth_confirm"]["title"] == "TP-Link Deco"
    assert french["entity"]["sensor"]["mobile_data_usage"]["name"] == (
        "Consommation de données mobiles"
    )
    for section_name, step_name in (("config", "user"), ("options", "init")):
        labels = french[section_name]["step"][step_name]["data"]
        assert labels["link_client_devices"] == (
            "Associer les traceurs clients aux appareils par adresse MAC"
        )
        assert labels["expose_wifi_ssids"] == (
            "Afficher les noms des réseaux Wi-Fi sur les capteurs d’état Wi-Fi"
        )
