---
name: deco-config-flow-validation
description: "Use when changing or testing Home Assistant configuration/options flows, polling interval selectors, test dependencies, Python/HA compatibility or CI for HiDiHo01/ha-tplink-deco. Covers the failure modes learned from PR #3 and PR #4; not for unrelated Home Assistant integrations."
---

# Validate Deco setup, options and test environments

1. Read `AGENTS.md` and any applicable `AI_POLICY.md`, then inspect `config_flow.py`, `select.py`, `const.py`, `requirements-test.txt`, `setup.cfg`, `.github/workflows/tests.yaml`, and the existing tests before changing behavior.
2. Keep Home Assistant form schemas **JSON-serializable**. For fixed interval choices, use a `SelectSelector` dropdown with **string** options, not a bare numeric `vol.In` selector. Exercise the actual Home Assistant form-to-JSON serialization path in tests; this can vary across supported HA versions.
3. Preserve the existing supported scan intervals **10, 30, 60, 120 seconds** and the **30-second default**. Display persisted integer or numeric-string values as string selector defaults; store valid selections as integers to preserve coordinator/runtime-select behavior.
4. Validate submitted values in **both setup and options flows** before credential checks, API traffic or data mutation. Reject unsupported values, malformed strings, `None`, floats and booleans; do not silently clamp or persist them. Return a field-specific error with matching `strings.json` and relevant translations.
5. Do not conflate the main client polling interval with a future independently configurable device-list interval. Preserve config-entry values and entity unique IDs when adding another control.
6. Parameterize regressions across supported values, legacy defaults and invalid inputs. Mock authentication/network operations and verify that invalid inputs do **not** invoke them or update config entries. Cover successful integer persistence in both flows, other config fields remaining unchanged, and JSON serialization.
7. Install test dependencies in an isolated environment using `requirements-test.txt` plus a separately pinned Home Assistant version. **Do not mix** this with `requirements.txt`, which pins legacy `homeassistant==2025.1.0`. Keep the local setup consistent with the CI matrix: Python 3.13/HA 2025.12 and Python 3.14/HA 2026.11.
8. Run `python -m pytest --no-cov tests/` for the focused suite; check formatting/pre-commit, HACS and Hassfest as available. Distinguish tests added from tests executed and passed. Report missing dependencies, unavailable CI or failed checks explicitly.

## Windows local test commands

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt "homeassistant==2026.11.0"
.\.venv\Scripts\python.exe -m pytest --no-cov tests/
```

For repository-wide requirements and migration constraints, follow `AGENTS.md`.
