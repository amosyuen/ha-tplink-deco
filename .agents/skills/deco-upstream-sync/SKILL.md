---
name: deco-upstream-sync
description: "Use when comparing, backporting, reviewing, or implementing changes from amosyuen/ha-tplink-deco into HiDiHo01/ha-tplink-deco, especially tracking issue #2, compatibility fixes, device naming and PR regressions. Do not use for unrelated repositories."
---

# Safely port TP-Link Deco upstream changes

1. Read the current repository `AGENTS.md`, any applicable `AI_POLICY.md`, and nested instructions before editing. Inspect current `main`, the target issue, the upstream change, and related fork PRs. Do not assume a missing upstream commit means missing behavior.
2. Choose one independently testable part of [tracking issue #2](https://github.com/HiDiHo01/ha-tplink-deco/issues/2). Create a branch from the latest fork `main`; avoid a bulk upstream merge.
3. Compare the **behavior**, not just the diff. Keep the fork's `sensor.py`, CPU/memory and backhaul diagnostics, connected-client entities, configurable polling, switch/select entities, pause/resume services, and existing configuration flows.
4. Preserve MAC-based device identifiers, entity unique IDs, master/satellite links, config-entry data and automations. If a migration is necessary, add regression tests for existing installations.
5. Account for firmware variability: Base64 UTF-8 and plain-text names, legacy `<Error Decoding ...>` wrappers, absent/empty nicknames, multiple mesh nodes, and optional API fields. Normalize a candidate name **before** checking whether it is empty. Fall back from custom nickname to firmware nickname to MAC.
6. Protect privacy: never log complete raw device/client lists, passwords, tokens or other sensitive firmware payloads. Test log redaction at the API-response-handler level, not solely at a decoding helper.
7. Add focused tests for the change and run the available checks. For test setup and HA form regressions, use the related `deco-config-flow-validation` skill. Report test limitations explicitly; do not say tests passed merely because they are present.
8. Open or update a **small PR** linked as `Part of #2`, not `Fixes #2`. Address valid review findings and resolve threads only after the corresponding change is committed or an explanation is supplied. Update issue #2's checklist only after the relevant scope has been merged; leave unported items open.

## Independent Deco inventory scheduling (upstream #616/#669/#670)

Port this feature as one compatible, independently tested backport.
Use the config-flow validation skill for the setup/options portion.

1. Compare the fork's existing scan-interval selector, two-coordinator
   startup, pause switch, client-list backoff and discovery dispatch with
   upstream #616, #669 and #670 before editing. An old config entry
   without `device_list_interval` must keep its original cadence.
2. Separate `device_list` polling from performance and client polling
   **inside the existing Deco coordinator**. Use `monotonic()` and a
   last-successful-device-list timestamp; `0` means startup-only.
   Keep performance updates and their previous-value semantics even
   when the inventory request is skipped. Never advance the timestamp
   on a failed request or invent a new master/registry identity.
3. Provide one per-entry, master-linked `Refresh Deco status` button.
   Its immediate refresh must override startup-only and pause, while
   propagating failures safely. Do not use a debouncer or trigger extra
   refresh cycles to simulate device-list scheduling.
4. Use a serializable number schema (`vol.Coerce(int)` plus
   `vol.Range(min=0)`) and **flow-level** validation to reject 1–9,
   negative, boolean and malformed values. Ensure both setup and
   options flows return `invalid_device_list_interval` before testing
   credentials. Store integers, add English/Dutch labels and errors,
   and preserve the canonical `CONF_SCAN_INTERVAL` selector.
5. Test real coordinator startup/cache/interval/manual/failure behavior,
   actual Home Assistant form JSON serialization, two independent
   config entries, identity stability, device discovery and
   diagnostics. Validate both supported Python/Home Assistant
   matrices, pre-commit, HACS and Hassfest on the final head SHA.
   Keep hardware validation explicitly unverified when not performed.
6. Update the README and integration-specific guide and track the PR
   as `Part of #2`, not an automatic issue closer. The issue #2
   checklist remains open until a verified merge.

### Error-handling regression checklist for PR #34

- Validate the **entire** inventory payload before modifying any existing
  Deco: non-list responses, missing/duplicate identifiers, malformed names
  and invalid signal mappings must raise a fixed, privacy-safe error.
  A failed poll leaves cached nodes and the _last successful_ inventory
  timestamp untouched, **while recording the error type and failure
  counter**. Test failures occurring after a valid earlier refresh, not
  only on an empty initial cache.
- Process validated inventory before optional performance so a timeout or
  truncated performance reply cannot discard mesh discovery. Catch only
  expected performance timeout/transient exceptions; retain existing
  CPU/memory values. Authentication and unexpected API errors must remain
  failures, not become an apparently healthy refresh.
- Verify the manual button with **both** Home Assistant behaviors:
  `async_refresh()` swallowing a failure (`last_update_success=False`)
  and an upstream exception escaping from refresh. Emit a fixed
  `HomeAssistantError` without copying its message or exception context.
  Preserve `ConfigEntryAuthFailed` as the authentication error type but
  replace its message, and do not catch cancellation. In `finally`,
  clear the one-shot forced-refresh flag so a failed manual request cannot
  accidentally unpause later automatic polling; another press may retry.
- Exercise actual coordinator refreshes, retained identities, error/timeout
  health diagnostics, optional performance, and manual button behavior;
  verify both supported Home Assistant/Python matrices. Apply any
  Black/isort/Prettier corrections from the exact CI diff, then rerun the
  full checks on the **new final head**. A previous green head cannot
  validate later documentation-only commits or tests.

## Legacy numeric telemetry compatibility (upstream #589)

The fork's Deco/client coordinators previously used firmware fields
directly in arithmetic. Before porting the larger encrypted S7 session
support, isolate the **numeric-value** change into a small backport:

1. Inspect `TpLinkDecoClient.update`, `bytes_to_bits` and the master
   CPU/memory processing in `TplinkDecoUpdateCoordinator`. Preserve the
   existing units, polling, smoothing, stored client IDs and network totals.
2. Parse numeric JSON integers, floats and strings to **finite** floats,
   including real zero. Treat booleans, nulls, malformed strings, NaN,
   infinities and overflow as absent measurements. Never log untrusted
   input values; do not translate them into authentication failures.
3. For malformed CPU/memory values, keep prior raw and smoothed values;
   process the other valid field independently and continue Deco
   discovery. For malformed/missing client rates, store numeric zero
   rather than `None`: existing per-Deco/network throughput sensors
   sum online clients directly. Preserve client association, online
   state, historical identity and timeout behavior.
4. Add parameterized parsing tests, client-update tests, real
   coordinator-refresh tests for invalid-to-valid transitions and 70/30
   smoothing, **and tests of the actual throughput sensor aggregation**
   with mixed valid/invalid online client rates. Confirm a failed
   optional measurement does not propagate into unrelated entities.
   Apply exact Black/isort fixes from CI rather than relaxing hooks.
   Rerun both supported Home Assistant/Python pytest matrices plus
   pre-commit, HACS and Hassfest on the **final head SHA**.
5. Review any P2 findings against the **latest** producer-to-consumer
   path. PR #33's review suggested a downstream sensor change, but the
   validated narrow fix was to guarantee numeric `0.0` in
   `TpLinkDecoClient.update`, preserving the existing sum contract.
   Compare the code, actual online-client sensor test and final-head
   CI results before replying. State the chosen fix and hardware
   limitations in the review response, resolve only after verification,
   and recheck that no threads remain open.
6. Report this as a **partial** upstream #589 backport. Leave the issue
   #2 S7 encrypted-session support unchecked. The HTTP outer session,
   login fallback and cryptographic request format require a separate
   security-reviewed PR.

## Sensor and throughput backports (PR #6)

- Read the fork's sensor/coordinator behavior before applying an upstream
  change; the fork has extra diagnostics and different entity definitions.
- For throughput, filter using the existing client `online` state **before**
  summing cached rates. Network totals span all nodes; per-Deco totals also
  filter by the client's `deco_mac`. Do not change client-count sensors,
  tracker presence or `consider_home` semantics as a side effect.
- Verify both directions, stale offline rates, unknown status, multiple
  Decos, empty inventories, reconnects and stable sensor unique IDs.
- Add targeted runtime regression tests and distinguish successful tests
  from unexecuted Home Assistant-dependent checks. See `AGENTS.md` for
  the repository-wide constraints.

## Device-registry service backports (PR #8)

When porting Home Assistant services that consume device registry IDs, follow
[Deco device-registry service validation](../deco-service-registry-validation/SKILL.md).
It covers domain-specific identifier lookup, validating all selected devices
before router calls, real service-handler tests and preservation of stable IDs.

## Unavailable client tracker restoration (upstream #619)

A restored `unavailable` tracker may have no `device_type` but still
have a valid MAC-based entity-registry identity. Do not silently drop it.
Restore it provisionally as a client and reconcile against the confirmed
Deco inventory after the first device refresh. Support the two Home
Assistant restore-state API shapes, and skip disabled/unrelated entries.
Follow [Deco client restore-state validation](../deco-client-restore-validation/SKILL.md);
preserve stable entity IDs and fork-specific client retention/backoff.

## Runtime Deco entity discovery (upstream #643)

The Deco coordinator's `SIGNAL_DECO_ADDED` notifies current platforms
synchronously. The refreshed MAC-keyed Deco inventory must therefore be
assigned to `coordinator.data` **before** the signal, not only returned
from `_async_update_data()`. Preserve existing nodes, the complete
performance calculations, late-master network totals and MAC-based entity
IDs. Mark the binary-sensor discovery handler with `@callback`.
Follow [Deco runtime discovery validation](../deco-runtime-discovery-validation/SKILL.md).

## Downloadable coordinator health diagnostics (upstream #575, PR #31)

**When to use:** review or modify the Home Assistant config-entry
diagnostics export introduced by PR #31. It is distinct from PR #30's
health sensors and does not implement per-device exports or system logs.

1. Read the current `AI_POLICY.md`, `AGENTS.md`, this skill and
   `diagnostics.py` before editing. Verify Home Assistant's
   `async_get_config_entry_diagnostics(hass, config_entry)` signature
   against the supported 2025.12 and 2026.11 core versions.
2. Map each exported field to a trusted **cached** source. Keep a
   versioned, allowlisted schema of anonymous aggregate counts, UTC-aware
   last-success timestamps, response times, fixed error-type labels,
   timeout/failure counters and existing polling/backoff status. Do not
   perform an API call, refresh, registry mutation or cross-entry lookup.
3. Inspect the final JSON, including nested keys and values. Never include
   config data/options, entry IDs, MAC/IP/BSSID addresses, client or
   router names, SSIDs, cookies, tokens, credentials, session material,
   individual client/device listings or raw upstream exceptions. Generic
   recursive redaction of a broad payload is **not** a substitute for
   choosing safe fields.
4. Audit error-label provenance. `type(error).__name__` and fixed internal
   status markers are acceptable; untrusted error **messages** are not.
   Length checks and `str.isidentifier()` are insufficient to establish
   that a string is non-sensitive: `PrivateSessionToken` also passes
   those checks. Test malformed values and plausible identifier-shaped
   secrets if health values can be injected or overwritten.
5. Add tests asserting exact top-level/nested keys, JSON serialization,
   absent/null data, real zero counts, aware timestamps, no router calls,
   configuration-entry isolation and private sentinel exclusion. A direct
   call to the diagnostics function verifies its data contract, **not**
   Home Assistant's registration of the Download diagnostics handler;
   verify platform registration separately before claiming UI availability.
6. Run both supported pytest matrices, pre-commit, HACS and Hassfest on
   the **same final commit SHA**. In PR #31, Black fixed function wrapping
   before isort flagged `json` import ordering on the next run. Use the
   exact hook diff to correct files, then rerun all required workflows
   against the new head. Earlier 316/316 results do not validate later
   commits. Record unperformed physical-router checks explicitly.
7. Update README and `home-assistant.md` when behavior changes and
   synchronize issue #2 accurately. PR #31 is merged; check off only the
   diagnostics-export item, not unrelated upstream acceptance criteria.

## Optional coordinator health diagnostics (upstream #575)

First inspect the existing fork's Deco and client update methods and
optional/failed API semantics. Keep existing response handling, per-node
client polling, cache retention, startup order and 5xx backoff unchanged.
Record health around **actual API attempts only**: a paused or deferred
coordinator must not manufacture a new success or latency. A returned
historical client dictionary after an all-failed poll must not be treated
as a successful query; a valid empty list does count as success.

Store the last successful aware UTC timestamp, measured API duration,
sanitized error **type** (never exception text), and client timeout
count. Keep current `client_query_mode` factual (`per_node` until the
global fallback exists). Do not add router requests solely for health.
Attach all new sensor entities to the known master, disabled by default,
with stable MAC-prefixed unique IDs. Register them once and support late
master discovery, partial mesh failures and separate config entries.
Do not change existing diagnostics or network throughput sensors.

**Repeated-failure notification trap (PR #30 review):** Verify the
`DataUpdateCoordinator._async_refresh` implementation on the supported
Home Assistant releases. Both HA 2025.12 and 2026.11 return before
`async_update_listeners()` when two consecutive refreshes fail. Recording
`health.record_failure()` alone updates in-memory metrics but does **not**
publish fresh health sensor state on later failures; `available=True`
does not change that. Before accepting a health feature, implement a
separate, lifecycle-safe health notification mechanism for each changed
failure metric, without turning an unsuccessful refresh into a success
or notifying unrelated entities. Ensure listener removal on unload.
The PR #30 fix uses independent `CoordinatorHealth.async_add_listener`
subscriptions: health sensors are nonpolling `SensorEntity` instances,
unsubscribe via `async_on_remove`, and receive updates on success,
failure and incomplete polls. A faulty subscriber must not abort or
reclassify an API poll; do not log its unredacted error message.

Add focused tests for actual and skipped refreshes, failures, valid
empty/all-failed client polls, sanitized API errors, timestamp timezone,
idempotent sensor registration and device identity. Include integration
regressions that invoke `async_refresh()` through **success → failure
→ failure → recovery**, asserting that enabled health sensors receive
both failure changes, their values update, and existing coordinator
success/availability contracts are preserved. Directly calling
`_async_update_data()` only tests the data path, not Home Assistant
listener propagation. Execute the Python 3.13/HA 2025.12 and Python
3.14/HA 2026.11 CI matrix plus formatting and HACS/Hassfest when
available, or report exact limitations. The diagnostics export was merged separately in fork PR #31;
use the whitelist and validation procedure above.

## Initial optional client refresh without startup blocking (upstream #645)

When this fork's `async_create_and_refresh_coordinators` awaits the client
coordinator's first refresh, slow per-node requests block platform setup.
Leave the first **Deco device** refresh awaited and keep provisional-client
reconciliation before constructing the client coordinator. For configured
entries, defer only the **client** first refresh until after platform
forwarding and service/listener setup, then use
`ConfigEntry.async_create_background_task(hass, clients.async_refresh(), ...)`.
Do **not** use `async_request_refresh()` here: its debouncer can create a
foreground task and defeat the intended startup behavior.

Add deterministic tests for setup returning before the pending initial
client request resolves, platform-forwarding order, entry-owned coroutine
scheduling, and failure during platform forwarding. Update existing
restoration tests that previously expected an awaited client first refresh.
Verify the existing Deco first-refresh failure still prevents unsafe client
construction, and confirm later count-sensor discovery uses its own first
successful client poll. Test both supported Home Assistant versions and
lifecycle/unload behavior when available. This is a client-only subset of
upstream #645; wireless and mobile initial refreshes remain out of scope
until those optional coordinator platforms exist in the fork.

## Startup client counts (upstream #567/#597)

Inspect `sensor.py` and the fork's existing client coordinator before
porting upstream. The sensor's `<deco_mac>_client_count` identity must stay
unchanged. Separate a **valid empty response** from an unverified state:
when all node queries fail, polling is paused or HTTP 5xx backoff suppresses
requests, do not create a new zero-count sensor. Track each Deco's first
successful client poll; a successful peer does not validate a failed node.

Register the count entity once per confirmed node via the client
coordinator's post-update listener, including nodes discovered at runtime.
Only count clients whose node matches and `online` is truthy; keep the
existing `consider_home` grace behavior and retained offline trackers.
Verify early and repeated events, partial-mesh failures, recovery, valid
empty lists, stable identifiers and independent config entries. Update
existing runtime-discovery tests that previously assumed count sensors
were created before a client poll. Run both Python/HA test configurations
and lint/HACS/Hassfest, or report precisely what could not run.

## Client tracker registration after coordinator refresh (upstream #569)

The fork currently publishes `SIGNAL_CLIENT_ADDED` while computing
`_async_update_data`, before the new client dictionary becomes
`coordinator_clients.data`. For a missing tracker, check whether the
platform sees stale data during dispatcher delivery before changing the
coordinator's shared timing contract. Add a post-update
`coordinator_clients.async_add_listener(add_untracked_clients)` subscription
alongside the existing dispatcher, and register both unsubscribe callbacks
with `coordinator_clients.on_close`.

Validate with a regression that fires the early dispatcher before the data
change, then commits the new client dictionary and invokes the post-update
listener. Verify per-MAC deduplication across repeated refreshes and
notifications, newly discovered clients on later refreshes, isolation between
configuration entries, stable tracker unique IDs and the optional MAC device
linking behavior. Do not alter `sensor.py` connected-client counts or the
`consider_home` grace period in this narrowly scoped fix; upstream #567/#597
require separate review. Run the existing Python/Home Assistant matrix and
pre-commit/HACS/Hassfest when available, and report unrun checks explicitly.

## Master/satellite device-registry migrations (upstream #579, fork PR #18)

For changes to entity `device_info` parent relationships, follow
[Deco device-registry parent-link validation](../deco-device-registry-parent-links/SKILL.md).
This is distinct from the service-action registry validation workflow.

The PR #18 regression showed that updating `create_device_info` and adding
new tests does **not** guarantee a passing full suite: an existing nickname
test still expected `via_device` on a Home Assistant version exposing
`via_device_id`. Search existing tests and all entity-platform callers,
preserve the original identity/name assertions, and run **both** supported
Home Assistant versions after updating stale expectations. Keep the main
tracking issue open until the PR has actually been merged.

## Optional client-device MAC linking (upstream #605)

For opt-out MAC matching, preserve the client tracker's original MAC-based
entity `unique_id` and the default-enabled scanner MAC. Disabling the
option must affect only scanner matching, not physical Deco nodes or
entity identity. Add a versioned config migration and protect shared and
foreign registry devices from the manual cleanup hook. Use the
[client MAC-linking skill](../deco-client-device-linking/SKILL.md) for the
config-flow and registry regression matrix.

## Per-config-entry polling switch registry migration (upstream #655)

When multiple Deco entries can exist, do not keep the single shared
`tplink_deco_polling` switch unique ID. Use a scoped unique ID per
`ConfigEntry.entry_id`, but migrate the legacy registry entry in place
only for the actual owning config entry. This preserves existing
`switch.deco_polling` entity IDs, user customizations and automations
without linking the wrong mesh. Follow the
[Deco polling-switch migration skill](../deco-polling-switch-registry-migration/SKILL.md).
Review older cross-platform registry tests for a global unique ID
assertion. Keep switch functionality, master-device identity and all
other platforms unchanged.

## HTTP 5xx client polling backoff (upstream #624)

For client-list HTTP 500/502/503, capped non-blocking 30–300-second
retry delays, session retention, partial mesh failures and sanitized
response logging, follow
[Deco client-backoff validation](../deco-client-backoff-validation/SKILL.md).
Preserve the fork's per-node client data and pending distinct global
client-list fallback; no global query-mode or health infrastructure is
required for this narrow port.

## Incomplete response and client-state recovery (upstream #590)

For `ClientPayloadError`, server disconnects and per-node client-state
preservation, follow [Deco transient-response validation](../deco-transient-response-validation/SKILL.md).
The fork's authenticated-session retention on transport failure (PR #14)
takes priority over upstream's older disconnect-based `clear_auth` behavior.
Keep HTTP 500 backoff (#624) and global client-list fallback (#527/#556)
outside this small port. Tests must distinguish failed responses from
successful empty lists and preserve known clients after retry exhaustion.

## Coordinator and session lifecycle backports (upstream #656)

For setup/unload, scheduled-refresh cleanup and router logout, follow
[Deco lifecycle validation](../deco-lifecycle-validation/SKILL.md).
The fork currently has Deco and client coordinators; review available
components before copying a newer upstream teardown implementation.

## Regression repair after startup and diagnostic changes (PR #30)

Use this procedure when an upstream backport changes coordinator setup,
adds new sensor entities, or fails the repository's full regression suite:

1. Read the **actual** Python 3.13/HA 2025.12 and Python 3.14/HA 2026.11
   pytest job logs; group failures by root cause before modifying code.
   In PR #30, 18 failed test cases shared four causes rather than
   18 independent production defects.
2. Check all existing tests mocking
   `custom_components.tplink_deco.async_create_config_data`. Once the
   integration schedules a first client refresh, the mock result must
   contain **both** `COORDINATOR_DECOS_KEY` and
   `COORDINATOR_CLIENTS_KEY`; provide
   `MagicMock(async_refresh=AsyncMock())` for the latter. Preserve
   assertions that platforms finish forwarding before background work,
   and that failed platform forwarding does not schedule client polling.
3. For sensor tests, filter added entities by class and stable
   `unique_id`. Eight opt-in health diagnostics can share the master
   Deco's first `async_add_entities` call with two throughput totals;
   an assertion that the entire batch has length two is no longer
   valid. Assert existing totals remain exactly two **and** health
   sensors remain present, disabled by default and nonduplicated.
4. In config-flow tests, import `CONF_SCAN_INTERVAL` from Home Assistant
   rather than using the literal `"scan_interval"`. The supported key
   is currently `"interval_seconds"`; submit the string selector value
   `"30"` and verify persisted value `30` is an integer. Check both
   setup and options flows without weakening the original contract.
5. Fix missing or misspelled test imports with Flake8, then inspect the
   full-repository Black, isort and Prettier hook diffs. Apply only
   verified formatting changes (including existing files touched by the
   all-files hooks); do **not** disable hooks or change production code
   to satisfy an obsolete test assumption.
6. Rerun all required workflows against the new PR-head SHA, inspect
   each matrix job and pre-commit/HACS/Hassfest separately, and update
   the PR and tracking issue with the **final** run links. Keep physical
   hardware validation explicitly unverified if it was not performed.

## CI repair and issue #2 bookkeeping

1. Inspect the actual PR-head commit and both workflows:
   `.github/workflows/pytest.yaml` runs both Python/Home Assistant
   combinations; `.github/workflows/tests.yaml` covers pre-commit, HACS
   and Hassfest. A successful test on an older commit is not sufficient.
2. If Black, isort or Prettier changes a file in CI, read the hook diff,
   apply only those required formatting changes to the PR branch, and
   recheck every required workflow on the resulting head. Never weaken a
   CI gate just to make it pass.
   **PR #30 bootstrap failure:** if every job fails at `Set up job`,
   download the failing job logs before changing application code.
   This repo enforces full-length commit SHA pinning for external
   `uses:` actions. The unpinned `actions/checkout@v6`,
   `actions/setup-python@v6.2.0`, `hacs/action@main`, and
   `home-assistant/actions/hassfest@master` references were rejected
   before tests began. Keep code changes separate from CI policy repair;
   in a targeted workflow fix, verify and pin the correct upstream action
   commit SHA for **each** reference and rerun both matrix entries plus
   pre-commit, HACS and Hassfest. Never relax action restrictions to force
   a run. Report `not executed: blocked at action download`, rather than
   claiming a pytest or lint failure in the integration itself.
3. Check mergeability and unresolved review threads independently of CI.
   Explain skipped or pending checks; do not call a PR validated until
   every required job actually passes. Record exact run links in the PR.
4. As soon as a PR is opened, record its link, precise scope, current CI
   status and limitations in the associated tracking issue (issue #2).
   Keep the matching checkbox **unchecked** and the issue open. If new
   commits materially change status, update the existing issue record
   rather than leaving the issue behind or adding duplicate updates.
   Check other repository-owned related issues and update them only when
   their scope or dependencies are genuinely affected.
5. After the PR merges, verify both `merged_at`/`merge_commit_sha`
   and the expected changed code on the new `main`. Then mark **only**
   the matching checklist item complete in issue #2. Add a concise
   merged-PR record (commit, tests, preserved behavior, limitations).
   If a PR closes unmerged, record that state without checking off work.
6. Keep the remaining checklist and cross-feature acceptance gates
   untouched. Historical upstream/fork commit counts remain a historical
   baseline until a **new comparison** is actually performed; do not
   describe an updated heading as a fresh comparison.

## Handoff checklist

- State exactly which upstream change was ported and which behaviors remain out of scope.
- Confirm no existing fork-specific entities or services were removed.
- Identify the tests actually executed, pending CI, and any blocked checks.
- Check current merge conflicts and unresolved review threads before reporting completion.
- Evaluate verified lessons from the change/review; update `AGENTS.md` or the relevant skill on this branch when reusable, otherwise state that no guidance update was needed.

`AGENTS.md` remains the source of repository-wide policy and quality requirements.
