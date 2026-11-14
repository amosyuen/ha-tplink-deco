"""Regression checks for Home Assistant connection metadata compatibility."""

import json
from pathlib import Path

INTEGRATION_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "tplink_deco"
)


def test_config_flow_omits_deprecated_connection_class() -> None:
    """Keep deprecated config-flow connection class constants out of the code."""
    config_flow_source = (INTEGRATION_DIR / "config_flow.py").read_text(
        encoding="utf-8"
    )

    assert "CONNECTION_CLASS" not in config_flow_source
    assert "CONN_CLASS_CLOUD_POLL" not in config_flow_source


def test_manifest_preserves_local_polling_metadata() -> None:
    """Retain the supported manifest-based Home Assistant connection type."""
    manifest_content = (INTEGRATION_DIR / "manifest.json").read_text(
        encoding="utf-8"
    )
    manifest = json.loads(manifest_content)

    assert manifest["domain"] == "tplink_deco"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
