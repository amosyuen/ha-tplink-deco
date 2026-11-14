# Repository instructions for AI-assisted development

These instructions apply to the entire `ha-tplink-deco` repository. Read this
file before making changes. If `AI_POLICY.md` is added later, follow it as the
repository's governing policy and resolve any conflicts before proceeding.

## Reusable repository skills

For repeatable workflows, use the relevant repository-local skill after
reading these instructions:

- [Deco upstream synchronization](.agents/skills/deco-upstream-sync/SKILL.md):
  compare and port upstream features in small, compatibility-safe PRs.
- [Config flow and test validation](.agents/skills/deco-config-flow-validation/SKILL.md):
  validate Home Assistant forms, polling interval storage and CI regressions.

These skills are task-specific procedures. This file remains the source of
repository-wide rules; any future `AI_POLICY.md` remains the governing policy.

## Preserve fork compatibility

- Treat upstream synchronization (tracking issue #2) as a series of small,
  independently validated PRs. Verify behavior in the current fork and the
  current upstream version before porting a change; missing upstream commits
  do not necessarily mean missing functionality.
- Do not replace the fork's `sensor.py` wholesale. Reconcile changes and
  preserve fork-specific CPU/memory, backhaul, connected-client, polling and
  other entities, services, and diagnostics.
- Keep existing entity unique IDs, device-registry identifiers, configuration
  entries, and automation compatibility stable. Add migration tests whenever
  an identifier or relationship must change.
- Test changes against incomplete firmware responses, offline devices,
  multiple Decos, and multiple configuration entries where relevant.

## Name decoding and privacy lessons (PR #3)

- Firmware may return Base64-encoded UTF-8 names, plain-text names, empty
  names, or names wrapped by older versions as `<Error Decoding ...>`.
  Decode when valid; otherwise preserve the original text and normalize
  legacy wrappers without logging the supplied name.
- When naming a Deco, use the nonempty custom nickname first, then its
  firmware nickname, then the MAC address. Missing fields must not raise
  exceptions. Renaming must not change MAC-based device identifiers.
- Do not log complete device/client lists, raw firmware responses, names,
  credentials, session tokens, or other sensitive API data. Use sanitized
  counts and exception *types* for diagnostics when appropriate.
- Add tests at both the helper and API-response-handler levels; a helper
  unit test alone does not verify that incoming firmware payloads are
  processed or logged safely.

## Configuration and polling interval lessons (PR #4)

- Home Assistant config/option forms must use schema validators that the
  installed HA version can serialize for the UI. For a fixed choice of polling
  intervals, use `selector.SelectSelector` with string options instead of
  a numeric `vol.In(...)` control; test serialization through Home Assistant's
  actual flow response path, not only Voluptuous schema validation.
- Preserve the fork's supported scan intervals (10, 30, 60 and 120 seconds)
  and the existing 30-second default. Treat persisted integers and valid
  numeric strings as equivalent when displaying selector defaults.
- Normalize accepted selector values back to integers before saving config
  entries. The polling coordinators and the runtime interval select depend on
  compatible persisted settings; do not change their entity IDs or semantics.
- Validate submitted intervals in both initial configuration and options
  flows before checking credentials, making router calls, or persisting data.
  Reject unsupported values, booleans, floats, malformed strings and nulls
  with a field-specific error, without changing stored settings.
- Keep field errors in `strings.json` and relevant translations (at least
  English and Dutch). Confirm that invalid form submissions display an error
  rather than initiating an unnecessary network request.
- Regression coverage should include form serialization, supported and
  invalid values, defaults from older config entries, string-to-int
  conversion, initial setup, options updates and preservation of other
  configuration fields.
- Keep the scan-interval control separate from any future independent Deco
  device-list polling interval. Port only upstream behavior that applies to
  the current fork, and test against each supported Home Assistant version
  because form serialization internals can differ across releases.

## Local dependencies and tests

- `requirements.txt` is the existing development constraints file and
  currently pins `homeassistant==2025.1.0`. Do not install it into the
  modern regression-test environment alongside Home Assistant 2026.11.
- Put direct regression-test dependencies in `requirements-test.txt`.
  Install Home Assistant separately at the version being tested. Keep the
  GitHub Actions test job and local setup aligned with this shared file.
- On Windows, use an isolated Python 3.14 virtual environment, then run:

  ```powershell
  py -3.14 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -r requirements-test.txt "homeassistant==2026.11.0"
  .\.venv\Scripts\python.exe -m pytest --no-cov tests/
  ```

- The regression CI matrix tests Python 3.13 / Home Assistant 2025.12
  and Python 3.14 / Home Assistant 2026.11. Keep both versions in mind
  when introducing imports or Home Assistant API changes.
- Run `python -m pytest --no-cov tests/` for focused regression tests:
  `setup.cfg` enables coverage reporting with a 100% threshold by
  default. Do not report a successful full-coverage run when only the
  focused suite has been executed.
- Cover missing and empty nicknames, Base64/Unicode and unencoded names,
  legacy wrappers, stable registry IDs, satellite-to-master relationships,
  privacy-safe logging, and end-to-end API decoding behavior.
- After changes, run available pytest and formatting/pre-commit checks,
  then confirm HACS, Hassfest, and CI status where available. Report
  checks that were not run or could not be verified; never claim success
  from tests that have merely been added.

## Implementation quality

- Respect the code style and tooling already configured in this repository
  (`.ruff.toml`, `setup.cfg`, and `.pre-commit-config.yaml`).
- Use descriptive function names, Python type hints, and docstrings for new
  functions and methods; keep asynchronous operations and errors explicit.
- Make the smallest change that meets the issue's acceptance criteria,
  document user-visible behavior, and explain regression coverage in the PR.
