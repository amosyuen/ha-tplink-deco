---
name: deco-config-flow-validation
description: "Use when changing or testing Home Assistant configuration/options flows, polling interval selectors, test dependencies, Python/HA compatibility or CI for HiDiHo01/ha-tplink-deco. Covers the failure modes learned from PR #3 and PR #4; not for unrelated Home Assistant integrations."
---

# Validate Deco setup, options and test environments

1. Read `AGENTS.md` and any applicable `AI_POLICY.md`, then inspect `config_flow.py`, `select.py`, `const.py`, `requirements-test.txt`, `setup.cfg`, `.github/workflows/pytest.yaml`, and the existing tests before changing behavior.
2. Keep Home Assistant form schemas **JSON-serializable**. For fixed interval choices, use a `SelectSelector` dropdown with **string** options, not a bare numeric `vol.In` selector. Exercise the actual Home Assistant form-to-JSON serialization path in tests; this can vary across supported HA versions.
3. Preserve the existing supported scan intervals **10, 30, 60, 120 seconds** and the **30-second default**. Display persisted integer or numeric-string values as string selector defaults; store valid selections as integers to preserve coordinator/runtime-select behavior.
4. Import and use Home Assistant's `CONF_SCAN_INTERVAL` constant in
   fixtures and assertions; in the supported releases its key is
   `"interval_seconds"`, **not** the invented literal
   `"scan_interval"`. PR #30's existing MAC-linking regressions failed
   because the latter bypassed interval normalization, leaving the
   submitted `"30"` as a string. Assert the persisted canonical key
   holds integer `30` in both setup and options flows.
5. Validate submitted values in **both setup and options flows** before
   credential checks, API traffic or data mutation. For **numeric**
   interval fields, reject unsupported values, malformed strings,
   `None`, floats and booleans; never silently clamp or persist them.
   For **boolean** settings, require actual booleans and do not coerce
   integers or strings to consent. Return field-specific errors with
   matching `strings.json` and translation keys.
6. Keep the main client/performance polling interval distinct from the independent Deco `device_list_interval`. Preserve existing values, unique IDs and the original scan-interval selector. For the new field accept integer 0 (startup-only) or >=10 seconds; use a continuous serializable schema and validate the disjoint constraint at the flow layer in both setup and options, including rejected 1–9 without authentication.
7. Parameterize regressions across supported values, legacy defaults and invalid inputs. Mock authentication/network operations and verify that invalid inputs do **not** invoke them or update config entries. Cover successful integer persistence in both flows, other config fields remaining unchanged, and JSON serialization.
8. For any config-entry version migration, check the actual `ConfigEntry`
   API in **both supported Home Assistant versions** before choosing how to
   update version or data. The PR #24 review found that directly assigning
   `config_entry.version` raises `AttributeError` on real entries even
   though `SimpleNamespace` tests accepted it. Stage the version/data
   changes locally and commit them once with
   `hass.config_entries.async_update_entry(entry, data=..., version=...)`.
   Use a **real `ConfigEntry`** in migration regressions; assert the
   version remains unchanged before the mocked manager applies its write,
   that `version` and `data` are passed together, and that old persisted
   values are preserved. A mocked manager verifies the call only; it does
   not prove Home Assistant persisted the result. See the
   [client MAC-linking migration example](../deco-client-device-linking/SKILL.md).
9. Install test dependencies in an isolated environment using `requirements-test.txt` plus a separately pinned Home Assistant version. **Do not mix** this with `requirements.txt`, which pins legacy `homeassistant==2025.1.0`. Keep the local setup consistent with the CI matrix: Python 3.13/HA 2025.12 and Python 3.14/HA 2026.11.
10. Run `python -m pytest --no-cov tests/` for the focused suite; check formatting/pre-commit, HACS and Hassfest as available. The standalone regression workflow supports PRs, pushes, daily runs and manual `workflow_dispatch`; it must verify the pinned Home Assistant version and imports before pytest. Distinguish tests added from tests executed and passed; report missing dependencies, unavailable CI or failed checks explicitly.

## Reauthentication must preserve stored options (upstream test parity, issue #2)

- **Verified failure:** `async_step_reauth_confirm` previously called
  `_ensure_user_input_optionals` on the credentials-only reauth payload.
  That inserted empty Deco/client name prefixes and postfixes, which then
  overwrote the user's saved values when the reauth credentials were merged.
- On **reauthentication**, copy the existing config entry data and update
  only submitted credentials; do **not** populate absent optional naming
  fields as empty strings. Keep the optional-name defaulting helper for
  first-time setup and explicit options submissions, where missing fields
  have different semantics.
- Test the real reauth handler with both configured custom names and legacy
  entries without optional-name keys. Verify the exact credential-check and
  config-entry-update payloads; preserve scan intervals, opt-in SSID consent,
  client-device linking, TLS settings and other options. Invalid credentials
  must not write or reload an entry. Confirm Home Assistant's form can open
  without changing stored data.
- This is a focused behavioral backport of the upstream reauth preservation
  test; syslog forwarding is not yet implemented in the fork. Do not
  introduce syslog keys solely to copy upstream test fixtures.

## Optional SSID consent in setup and options (upstream #637, PR #42)

- Use the per-entry `CONF_EXPOSE_WIFI_SSIDS` key, with the default
  `DEFAULT_EXPOSE_WIFI_SSIDS = False`; an absent or malformed stored
  value must not imply consent. Only `True` enables name exposure.
- Use a JSON-serializable boolean checkbox in **both** form schemas.
  Reject non-boolean submitted values using the field-specific
  `invalid_expose_wifi_ssids` error **before** credential checks or
  config-entry writes. A valid `False` is an explicit opt-out, not an
  invalid or missing submission. Preserve existing values during reauth,
  and ensure unrelated options, scan intervals and entry IDs are
  unchanged.
- Test the real Home Assistant form-to-JSON path and setup/options
  persistence with `True` and `False`, legacy/missing settings,
  invalid strings, numeric `0`/`1`, `None`, arrays and objects.
  Assert that invalid requests cause neither API calls nor entry
  updates. Check labels and errors in `strings.json` and **all**
  shipped locale files. For downstream SSID retention and runtime
  privacy, follow
  [the WLAN validation skill](../deco-wireless-status-validation/SKILL.md).

## Windows local test commands

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt "homeassistant==2026.11.0"
.\.venv\Scripts\python.exe -m pytest --no-cov tests/
```

For repository-wide requirements and migration constraints, follow `AGENTS.md`.
