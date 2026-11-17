---
name: deco-mobile-usage-validation
description: "Use when adding, reviewing or maintaining read-only 4G/5G Deco mobile usage, background setup, ownership and privacy (upstream #631 / tracking issue #2)."
---

# Validate optional TP-Link Deco mobile WAN usage

## Prerequisites

1. Read repository `AI_POLICY.md`, `AGENTS.md`, `home-assistant.md`,
   the upstream synchronization skill and the lifecycle skill.
   Inspect the actual current `api.py`, `mobile.py`, `sensor.py`,
   `__init__.py`, `config_flow.py`, `diagnostics.py` and the test suite.
2. Compare the behavior of upstream #631 against the fork. Do **not** merge
   upstream `sensor.py` wholesale or replace the mandatory Deco/client
   coordinators, their entities, MAC IDs or client polling semantics.

## Read-only API boundary and data contract

3. Use the existing authenticated encrypted LuCI session and **read only**
   `admin/network?form=internet` with `{"operation": "read"}`.
   Validate the outer encrypted envelope, decrypted mapping and authenticated
   firmware error code before touching the optional `mobile_cpe.data_usage`.
   Preserve the existing single authentication refresh and propagate
   cancellation. Avoid extra timeout retries on this optional endpoint.
4. Probe only an actual master whose model advertises 4G/5G. A missing
   `mobile_cpe` or usage counter means **unsupported**, not numeric zero.
   Accept only non-negative bounded integer KiB values, including zero,
   and plain ASCII decimal strings; reject booleans, floats, negatives,
   huge strings, malformed mappings and arbitrary firmware data.
   Never log the payload, usage, credentials, session URLs or exception
   message. Ordinary errors become a fixed sanitized `UpdateFailed`
   outside `except`, with neither `__cause__` nor `__context__`.
   **P1 review lesson:** a safe coordinator exception is too late if
   `TplinkDecoApi._async_post` or `_decrypt_data` already logged a raw
   HTTP error, nonzero outer response, connection exception or ciphertext.
   Extend the existing WLAN-sensitive boundary to the **exact**
   `Get mobile data usage` / `form=internet` read operation without
   changing unrelated LuCI errors. Test the **real bound methods**,
   not a fixture that replaces both with `AsyncMock`, using synthetic
   authenticated `request_info.real_url`, secret-containing error
   messages, nonzero API JSON, connection failures and decrypt errors.
   Preserve the existing HTTP 401/403 and one-relogin semantics.

## Coordinator ownership and sensor lifecycle

5. Use a **per-entry optional** five-minute DataUpdateCoordinator. Schedule
   the first refresh using `config_entry.async_create_background_task`
   **after** awaiting platform forwarding, never a blocking initial read.
   Mobile failures cannot prevent mandatory Deco/client polling.
   When paused, no mobile API request runs.
6. Capture master MAC and per-entry generation **before** awaiting usage;
   register a Deco listener with config-entry unload ownership, invalidate
   old data when the master changes and re-check MAC/generation when the
   request returns. An A -> B -> A switch must discard an old A response
   even when the final MAC equals the starting MAC. Never reuse one
   entry's usage or API session for another entry.
7. Register a mobile sensor only when **current-owner** data is available;
   zero is valid. Deduplicate by master MAC and retain the fixed
   `<master_mac>_mobile_data_usage` unique ID. Make previous-owner
   entities unavailable on a master switch; do not delete their registry
   records. Sensor and coordinator listeners must be removed with
   Home Assistant entry/entity unload. A standard optional coordinator
   uses `async_shutdown()`, **not** the fork-specific `async_close()`.
8. Keep diagnostics aggregate and non-sensitive: update success, whether
   current data is supported and update interval; never export the actual
   counter, raw data, model, names or credentials. Translate the entity
   name in every shipped locale and document Recorder/history exposure
   without promising retroactive deletion. **P2 review lesson:** a class-level
   `_attr_name` overrides the translated `_attr_translation_key` in both
   supported Home Assistant versions. Do not set `_attr_name` on the mobile
   entity; test the real `Entity.name` resolution with Dutch platform
   translations, not merely JSON key presence.

## Regression and completion gate

9. Use `tests/test_mobile_data.py` with real API parsing under mocked
   transport and actual coordinator callback behavior. Cover model gating,
   zero/negative/non-integer/oversized data, empty responses, malformed
   encrypted envelopes and auth codes, errors with synthetic secrets,
   cancellation, pause, failed read with retained prior state, A -> B and
   A -> B -> A in-flight transitions, delayed/idempotent sensor discovery,
   entry isolation, setup ordering, unload and redacted diagnostics.
   Synchronize races with `asyncio.Event`, not sleeps. Update every
   constructor-bypassing fixture if coordinator state changes.
10. Run the full repository commands in CI:
    `python -m pytest --no-cov -ra tests/` on
    Python 3.13/HA 2025.12 and Python 3.14/HA 2026.11, plus
    `pre-commit run --all-files --show-diff-on-failure --color=always`,
    HACS and Hassfest. Apply exact formatter corrections and repeat
    **all** checks on the final PR head.
11. Link the partial change as `Part of #2`, not `Fixes #2`.
    Update issue #2's mobile usage and background-refresh work as
    **in progress** while the PR is open; mark those checklist items
    complete only after confirming a merge on `main`. Do not claim
    physical 4G/5G hardware compatibility from mocked CI.
