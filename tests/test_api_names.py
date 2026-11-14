"""Regression tests for decoded and plain-text Deco/client names."""

import base64
import logging

import pytest

from custom_components.tplink_deco.api import decode_name_with_fallback
from custom_components.tplink_deco.api import normalize_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Kitchen", "Kitchen"),
        ("Living Room", "Living Room"),
        ("Invalid???", "Invalid???"),
        ("<Error Decoding Kitchen>", "Kitchen"),
        ("", ""),
        (None, None),
    ],
)
def test_plain_text_and_legacy_names(name: str | None, expected: str | None) -> None:
    """Keep plain-text names and remove old decoding error wrappers."""
    assert decode_name_with_fallback(name) == expected


@pytest.mark.parametrize("name", ["Kitchen", "Living Room", "Deco S7", "Café"])
def test_base64_utf8_name(name: str) -> None:
    """Decode valid UTF-8 names without changing their contents."""
    encoded_name = base64.b64encode(name.encode("utf-8")).decode("ascii")

    assert decode_name_with_fallback(encoded_name) == name


def test_invalid_utf8_keeps_original_name() -> None:
    """Keep encoded text when the decoded bytes are not valid UTF-8."""
    assert decode_name_with_fallback("/w==") == "/w=="


def test_name_fallback_does_not_log_private_names(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not log router/client names when decoding fails."""
    with caplog.at_level(logging.DEBUG):
        assert decode_name_with_fallback("Sensitive client???") == "Sensitive client???"

    assert "Sensitive client" not in caplog.text


def test_normalize_name_leaves_unwrapped_names_unchanged() -> None:
    """Do not strip unrelated angle brackets from names."""
    assert normalize_name("<Kitchen>") == "<Kitchen>"
    assert normalize_name("<Error Decoding Kitchen>") == "Kitchen"
