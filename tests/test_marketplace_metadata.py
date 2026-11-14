"""Regression tests for fork-specific Marketplace and HACS metadata."""

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = REPOSITORY_ROOT / "custom_components" / "tplink_deco"
FORK_REPOSITORY_URL = "https://github.com/HiDiHo01/ha-tplink-deco"
FORK_INSTALL_LINK = (
    "https://my.home-assistant.io/redirect/hacs_repository/"
    "?owner=HiDiHo01&repository=ha-tplink-deco&category=integration"
)


def test_manifest_marketplace_category_and_fork_support_links() -> None:
    """Categorize Deco routers and send users to this fork for support."""
    manifest = json.loads(
        (INTEGRATION_DIR / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["categories"] == ["computers_network.routers_network"]
    assert manifest["documentation"] == FORK_REPOSITORY_URL
    assert manifest["issue_tracker"] == f"{FORK_REPOSITORY_URL}/issues"
    assert manifest["integration_type"] == "hub"
    assert manifest["iot_class"] == "local_polling"
    assert manifest["config_flow"] is True


def test_readme_supports_marketplace_and_legacy_hacs() -> None:
    """Explain both versions without promising the fork is in the catalog."""
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "Marketplace (Home Assistant 2026.11 and newer)" in readme
    assert "Settings > Marketplace > Add from link" in readme
    assert "HACS (Home Assistant 2026.10 and earlier)" in readme
    assert "HACS > Integrations" in readme
    assert readme.count(FORK_REPOSITORY_URL) >= 2


def test_install_badge_targets_fork_and_retains_legacy_redirect() -> None:
    """Use the compatible HACS redirect, not the upstream repository."""
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.count(FORK_INSTALL_LINK) == 1
    assert "owner=amosyuen&repository=ha-tplink-deco" not in readme
    assert "my.home-assistant.io/badges/hacs_repository.svg" in readme


def test_installation_instructions_are_unique_and_marketplace_excluded() -> None:
    """Preserve manual and development instructions without duplicate blocks."""
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    start_tag = "<!-- ha-marketplace:exclude-start -->"
    end_tag = "<!-- ha-marketplace:exclude-end -->"

    assert readme.count(start_tag) == 1
    assert readme.count(end_tag) == 1
    assert readme.count("## Installation\n") == 1
    start = readme.index(start_tag)
    end = readme.index(end_tag)
    install = readme.index("## Installation\n")
    assert start < install < end
    assert readme.count("### Manual\n") == 1
    assert readme.count("### Local regression tests\n") == 1
    assert readme.index("### Manual\n") < end
    assert readme.index("### Local regression tests\n") < end
