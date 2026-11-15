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
5. Validate submitted values in **both setup and options flows** before credential checks, API traffic or data mutation. Reject unsupported values, malformed strings, `None`, floats and booleans; do not silently clamp or persist them. Return a field-specific error with matching `strings.json` and relevant translations.
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

## Windows local test commands

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt "homeassistant==2026.11.0"
.\.venv\Scripts\python.exe -m pytest --no-cov tests/
```

For repository-wide requirements and migration constraints, follow `AGENTS.md`.
