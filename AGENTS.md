# Repository instructions for AI-assisted development

These instructions apply to the entire `ha-tplink-deco` repository. Read
[`AI_POLICY.md`](AI_POLICY.md) first: it governs AI-assisted development.
Follow this file for repository-specific implementation rules and report
conflicts before proceeding.

## Reusable repository skills

For repeatable workflows, use the relevant repository-local skill after
reading these instructions:

- [Deco upstream synchronization](.agents/skills/deco-upstream-sync/SKILL.md):
  compare and port upstream features in small, compatibility-safe PRs.
- [Config flow and test validation](.agents/skills/deco-config-flow-validation/SKILL.md):
  validate Home Assistant forms, polling interval storage and CI regressions.
- [Device-registry service validation](.agents/skills/deco-service-registry-validation/SKILL.md):
  validate Deco device selections, batch actions and service regression tests.
- [Deco device-registry parent links](.agents/skills/deco-device-registry-parent-links/SKILL.md):
  validate master/satellite `DeviceInfo` relationships, legacy/modern API compatibility and existing regression assumptions.
- [Deco truncated-response and client-state validation](.agents/skills/deco-transient-response-validation/SKILL.md):
  validate bounded retries, retained authentication, per-node clients and optional performance data.
- [Deco runtime lifecycle validation](.agents/skills/deco-lifecycle-validation/SKILL.md):
  validate entry setup/unload, coordinator shutdown, callbacks and safe logout.

These skills are task-specific procedures. This file remains the source of
repository-wide implementation rules; `AI_POLICY.md` remains the governing
policy for AI-assisted development.

## Mandatory capture of learned lessons, rules, skills and technical workflows

- After each substantive bug fix, upstream backport, review resolution,
  regression investigation or workflow improvement, evaluate and **save**
  verified, reusable lessons learned, repository rules, skills and technical
  workflows before calling the work complete. Saving means updating actual
  repository files, not merely summarizing the lesson in a chat or PR.
- Put stable, repository-wide implementation rules and testing requirements
  in `AGENTS.md`. Put repeatable, task-specific technical procedures in the
  relevant `.agents/skills/*/SKILL.md` file, or create a skill when needed.
  Link newly created skills from the reusable-skills section of `AGENTS.md`.
  Keep `AI_POLICY.md` for governing policy, not technical instructions.
- For a reusable technical workflow, document when to use it, prerequisites,
  safe implementation steps, exact commands **only when verified**, known
  failure modes, required tests and completion criteria. Preserve existing
  workflows and avoid conflicting or duplicated instructions.
- For every new rule or lesson, record its triggering failure or evidence,
  scope and mandatory prevention or validation step. Base instructions on
  actual code, review findings or test results; never invent guidance or
  promote unverified assumptions to repository rules.
- Commit necessary guidance updates on the same working branch as the
  related change and describe the updated files in the PR. Confirm the
  documented links and run relevant formatting and validation checks.
  If no new reusable lesson exists, leave the instructions unchanged.
- Report unverified tests and incomplete work accurately. Do not mark a
  review thread resolved or a tracking-issue task complete merely because
  its lesson has been documented.

## Keep linked and related GitHub issues synchronized

- Whenever a PR is created, materially updated, reviewed, closed or merged,
  identify its directly linked issues and any repository-owned related issues
  whose scope, implementation status or dependencies are actually affected.
  Update those issues in the same workflow; a PR description alone is not an
  adequate status update for a tracking issue.
- For an open PR, record the PR link, implemented scope, verified tests,
  limitations and current state as **in progress** in the relevant issue.
  Update the existing status entry when new commits change the facts; avoid
  duplicate comments or repeating the same status unnecessarily.
- After a merge, verify the PR's `merged_at` and `merge_commit_sha`, confirm
  the expected implementation on the target branch, and update only matching
  issue checklist items and any dependent issue status. If a PR is closed
  without merging, record that fact and keep unimplemented items open.
- Never check off work, close a tracking issue, or claim completion solely
  because a PR exists or its CI passes. Leave unrelated tasks and overall
  acceptance gates open. Use `Part of #2`, not `Fixes #2`, for partial ports
  so GitHub cannot automatically close the tracking issue.
- Do not mutate upstream or unrelated repositories just because their issues
  or PRs are cited as evidence. If an affected issue cannot be updated,
  explain the permission or access limitation in the PR handoff.

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

## Device-registry service identifier handling

- Home Assistant devices may have zero, one or multiple registry identifiers.
  Select identifiers by the integration's domain rather than assuming a
  singleton set; unrelated identifiers must not prevent a valid Deco action.
- A missing or empty Deco MAC must produce a descriptive service error before
  sending a router command. Validate all requested devices before rebooting,
  so a selection failure does not cause a partial reboot.
- Regressions must exercise both identifier extraction and the actual service
  handler: a valid Deco identifier alongside other identifiers, multiple
  selected Decos, missing devices and invalid identifiers.

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
  counts and exception _types_ for diagnostics when appropriate.
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

## Client tracker hostname and device naming (upstream PR #600)

- For `ScannerEntity` client trackers, expose the existing composed display
  name as `hostname`. Home Assistant may use it when registering a tracker
  device whose MAC address is already associated with another integration.
- Reuse the existing name/prefix/postfix logic; preserve `mac_address`,
  entity/device identifiers, manually assigned names and other tracker
  attributes. Do not substitute a client name for a stable registry ID.
- Test missing and empty names, Unicode names, optional prefixes/postfixes,
  nickname refreshes and unchanged MACs. Device naming at registration time
  may not be updated until Home Assistant reloads the integration.

## Optional wireless backhaul metadata (upstream PR #595)

- Treat `bssid_sta_2g` and `bssid_sta_5g` from the Deco device list as
  optional wireless backhaul metadata, distinct from `bssid_2g` and `bssid_5g`
  used for the existing access-point BSSID attributes.
- Expose supported backhaul identifiers only as read-only Deco tracker state
  attributes. Missing fields must remain `None`, not cause startup failures
  or change MAC-based device identity, parent relationships, sensors or polling.
- Test master and satellite entries, missing/one/both bands, subsequent
  updates that remove a band, and preservation of existing BSSID attributes.
  Avoid logging raw wireless identifiers or other sensitive network metadata.

## Home Assistant Marketplace and HACS metadata (upstream PR #638)

- In custom integration manifests, use an officially supported product
  category such as `computers_network.routers_network`. Do not use
  entity-platform categories for a Deco router integration. Validate with
  HACS and Hassfest; unknown categories fail HACS validation.
- Repository installation badges, `documentation` and `issue_tracker`
  metadata for this maintained fork must lead to
  `HiDiHo01/ha-tplink-deco`, not to the original upstream project.
  Preserve author attribution separately from installation/support links.
- Explain Marketplace's `Add from link` workflow for HA 2026.11+ and
  custom repositories in HACS for earlier versions; do not imply that
  the fork is automatically listed in either catalog.
- Keep the compatible `hacs_repository` redirect for both versions.
  Maintain one installation section, preserve manual installation and
  local regression test instructions, and exclude install-only prose from
  the Marketplace README view with balanced `ha-marketplace` markers.
- Test the manifest, redirect owner, duplicate installation headings,
  retained instructions and exclusion markers without changing the
  minimum HA version, existing runtime platforms or configuration data.

## Same-router HTTPS redirects and session cookies (upstream PR #539)

- Newer aiohttp versions drop per-request cookies when an HTTP-to-HTTPS
  redirect crosses origins. Some Deco firmware returns HTTP 307 for every
  request, causing authenticated API calls to receive an empty response.
- When a successful redirect starts with HTTP 307 and ends at HTTPS on the
  **same configured router hostname**, upgrade the API's runtime base URL to
  the destination HTTPS origin (including a nondefault port). Subsequent
  calls should avoid redirecting and carry their ordinary session cookie.
- Never rewrite the API host after an unrelated HTTP status, no redirect,
  a redirect to a different host, or when the configured URL is already
  HTTPS. Do not edit persisted configuration or create a new admin session
  merely to handle a trusted scheme upgrade.
- Exercise the actual `_async_post` path in regressions with simulated
  aiohttp redirect history, follow-up authenticated requests, custom
  ports, cross-host/invalid redirects and privacy-safe logging. Do not log
  the redirected request URL, session tokens or cookies.

## Coordinator shutdown and router logout (upstream PR #656)

- Never shut down coordinators or unsubscribe their callbacks before Home
  Assistant reports that **all** forwarded platforms unloaded successfully.
  A failed or raising platform unload must retain the live entry, polling
  coordinators, callbacks and authentication for a subsequent retry.
- Once platform unload succeeds, await each existing Deco and client
  `DataUpdateCoordinator.async_shutdown()` before running its custom
  `async_close()` callbacks. The Home Assistant coordinator shutdown
  cancels scheduled refreshes; custom close releases dispatcher listeners.
- Perform the router's best-effort logout after coordinator cleanup and
  always clear locally held auth, even when the router is offline or rejects
  logout. Do not close Home Assistant's shared aiohttp client session.
- Avoid logging raw router logout errors, credentials, tokens or cookies.
  Do not swallow task cancellation. A missing/partial login should not
  generate a logout request.
- Test ordering, failed/raising unloads, absent coordinators/entries,
  multiple entries retaining their own data, successful logout, missing
  auth, transport errors, cancellation and safe diagnostic logging in
  actual async entry and API paths.

## Deco master/satellite registry links (upstream PR #579)

- Register or retrieve the master before linking satellites. On Home Assistant
  2026.8+, resolve the master's config-entry-scoped registry ID and use
  `via_device_id`; a MAC identifier tuple is not a registry ID.
- Detect support through `DeviceInfo.__annotations__`; on older supported
  Home Assistant versions, including 2025.12, use the `"via_device"` fallback
  without importing the deprecated `ATTR_VIA_DEVICE`.
- Pass the Deco coordinator to every device-info caller (trackers, sensors,
  binary sensors, switch and select). Preserve stable MAC identifiers, entity
  unique IDs, config entries and fork-specific features.
- Test missing master and device data, legacy and modern API versions,
  multiple entries sharing MACs and satellite entity relationships. Check
  **existing** nickname/device-identity tests for deprecated `via_device`
  lookups: on modern Home Assistant `DeviceInfo` can raise `KeyError` for that
  field even though the new `via_device_id` relationship is correct. Use
  version-aware assertions without deleting the original regression coverage.
  Follow the device-registry parent-link skill for the full test procedure.
  Do not claim live hardware verification based solely on unit or CI results.

## Authenticated API expiry error -5002 (upstream PR #620)

- Some Deco firmware reports an expired authenticated LuCI session as
  `error_code=-5002` in the top-level HTTP JSON response or in decrypted
  payloads (`error_code` / `errorcode`). Treat it as an auth expiry
  **only for requests made with the current authenticated session**, not
  during the initial login or when querying an unrelated host.
- Clear the stale token, cookie and sequence and raise the existing
  `EmptyDataException` to reuse the existing single re-login retry.
  Add authenticated reboot operations to that same bounded retry path.
- Preserve login-time invalid-credentials semantics, other API error
  propagation, HTTP 401/403 invalidation and ordinary HTTP 500 handling.
  Do not retry indefinitely or log the complete API response or credentials
  when detecting `-5002`.
- Test top-level responses via mocked aiohttp, decrypted responses from
  all four current LuCI operations, one successful relogin, repeated
  `-5002` stopping after one relogin, login/unrelated-host exclusions,
  generic API errors and unaffected HTTP errors. Do not assume that the
  fork already supports upstream legacy outer-session encryption.

## Retry incomplete API responses without losing client state (upstream PR #590)

- Treat `aiohttp.ClientPayloadError` and `aiohttp.ServerDisconnectedError`
  as incomplete responses eligible for bounded retries; do not copy upstream
  behavior that clears valid authentication on a disconnect. HTTP 401/403 and
  authenticated `-5002` remain the explicit authentication-expiry cases.
- Use the configured `timeout_error_retries` value, including zero, as the
  upper bound on extra transient-response attempts. Count them independently
  from timeout and one-time relogin retries. Do not retry cancellations.
- For a transient per-node client poll failure after retries, preserve clients
  associated with that Deco, their online state, last activity and device
  mapping. Distinguish failed responses from successful empty lists so other
  nodes update normally and retain the existing `consider_home` policy.
- Treat performance polling as optional when a response remains incomplete:
  preserve cached CPU/memory values while still updating the discovered
  Decos. Do not silence unrelated errors or HTTP status failures.
- Never log raw transport exception messages or router payloads that may
  contain authentication or network identifiers. Suppress the original
  transport exception context to prevent sensitive details in tracebacks.
  Cover request and response
  body failures, retry exhaustion, zero retries, multi-node partial success,
  successful empty lists, privacy and previous regression expectations.
  Follow the transient-response validation skill for the complete workflow.

## Transport errors versus expired authentication (upstream PR #598)

- A disconnected HTTP transport or connector failure does not by itself
  prove that the router's authentication token, cookie, or sequence expired.
  Preserve session state on these temporary failures so the next refresh can
  reuse credentials without creating a new Deco admin session.
- Continue to invalidate authentication when the router explicitly returns
  HTTP 401/403 or an established authentication-expiry response. Do not
  change the caller's existing transport exception types or imply automatic
  retries when the fork does not yet implement them.
- Test real API request paths with mocked aiohttp responses: both transport
  failures, incomplete payload behavior, 401/403 invalidation, non-auth
  HTTP errors, retry on a subsequent poll without login, and no token/cookie
  contents in logs. Never use real credentials or physical router calls.

## Await Home Assistant platform setup (upstream PR #540)

- In `async_setup_entry`, await
  `hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)`
  directly instead of scheduling a fire-and-forget task. Otherwise the
  config-entry setup lock may be released while child platforms still load.
- Propagate platform setup failures rather than returning success prematurely.
  Do not register entry services or listeners until platform forwarding has
  completed successfully. Preserve existing platform names and config entries.
- Test the actual async entry setup with a blocked forwarding coroutine:
  verify setup remains pending, service registration occurs only afterward,
  failures propagate without registering services, and multiple config
  entries each forward their platforms exactly once.

## Deferred network total sensors (upstream PR #540)

- A configuration entry can be satellite-only or temporarily have no master
  Deco. Do not instantiate master-dependent network-wide sensors until the
  coordinator has a valid `master_deco`; continue registering per-Deco sensors.
- Discovery signals may fire during `_async_update_data`, before the new
  coordinator data is committed. Use the coordinator's post-update listener
  for deferred master-dependent entities and unregister it on coordinator
  shutdown.
- Register network-wide Total Down/Up exactly once per config entry using
  the established `<master_mac>_total_down` and `<master_mac>_total_up`
  unique IDs. Do not recreate them after transient master disappearance.
- Test master-present, initially absent and permanently absent scenarios,
  late master discovery, repeated updates, stable IDs, and independent config
  entries without real hardware.

## Client throughput aggregation lessons (PR #6)

- A client retained in coordinator data may still have nonzero cached upload
  and download rates after going offline. Calculate current throughput using
  only clients whose existing `online` state is truthy; treat `False` and
  unknown (`None`) as ineligible for live rate totals.
- Preserve both aggregation scopes: network totals include all online clients
  across Deco nodes; per-Deco totals include only online clients whose
  `deco_mac` matches that node. Cover both upload and download consistently.
- Do not zero historical client rates, alter `consider_home` grace-period
  behavior, or change tracker/connected-client-count semantics just to fix
  throughput totals. Those behaviors need separate review and tests.
- Keep throughput entity unique IDs, device associations, CPU/memory/backhaul
  sensors, and fork-specific polling controls unchanged when porting upstream
  sensor fixes.
- Add deterministic regression cases for online clients across multiple
  Deco nodes, offline clients with stale nonzero rates, missing/unknown online
  state, per-node isolation, online-to-offline-to-online transitions, and
  empty/offline-only inventories. Test sensor behavior, not only a helper.
- Distinguish tests added and source checks from tests actually executed:
  Home Assistant-dependent tests require a compatible installed runtime
  before reporting a passing integration test result.

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
- Keep pytest in `.github/workflows/pytest.yaml` with PR, push, scheduled
  and manual triggers; retain linting, HACS and Hassfest in
  `.github/workflows/tests.yaml` without a duplicate pytest job. Verify
  Home Assistant installation and required imports before test collection.
  Missing or skipped runtime tests do not count as successful CI validation.
- Keep version-specific transitive dependency constraints local to their
  affected matrix entry. Home Assistant 2025.12 uses `aiodns==3.5.0`,
  which cannot import `pycares>=5`; use `pycares<5` for that test
  entry only, without downgrading the newer Home Assistant 2026.11 entry.
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

## PR validation and upstream tracking lessons

- After an API or schema migration, inspect the **whole existing test suite**
  for stale field assumptions, not just new targeted tests. Retain tests for
  prior behaviors (such as nickname fallback and stable device identity),
  make their expectations valid for each supported Home Assistant API, and
  execute the full matrix on both versions before claiming compatibility.
- Treat Black, isort and Prettier hooks as formatting requirements: if a CI
  hook rewrites a test or README file, commit the exact formatting correction
  to the PR branch and require a fresh run against the **new head commit**.
  Passing runs on superseded commits do not validate the final diff.
- Review the actual GitHub Actions job results for both supported Python /
  Home Assistant test-matrix entries and for pre-commit, HACS and Hassfest.
  Distinguish failures, skipped jobs, jobs still running and genuine passes;
  include run links in the PR only after the relevant jobs complete.
- Before describing a PR as ready, verify it targets current `main`, is
  mergeable, and has no unaddressed review threads. Never mark issue #2's
  corresponding checklist entry complete merely because CI is green.
- After an actual merge, verify the implementation on `main`, record the
  merged PR, commit, scope limits and CI links in issue #2, and leave unrelated
  checklist items and repository-wide acceptance gates open. Identify the
  historical upstream comparison as a snapshot, not a fresh diff.

## Implementation quality

- Respect the code style and tooling already configured in this repository
  (`.ruff.toml`, `setup.cfg`, and `.pre-commit-config.yaml`).
- Use descriptive function names, Python type hints, and docstrings for new
  functions and methods; keep asynchronous operations and errors explicit.
- Make the smallest change that meets the issue's acceptance criteria,
  document user-visible behavior, and explain regression coverage in the PR.
