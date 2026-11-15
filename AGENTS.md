# Repository instructions for AI-assisted development

These instructions apply to the entire `ha-tplink-deco` repository. Read
[`AI_POLICY.md`](AI_POLICY.md) first: it governs AI-assisted development.
Follow this file for repository-specific implementation rules and report
conflicts before proceeding.

## Integration-specific behavior and invariants

- **Read [`home-assistant.md`](home-assistant.md) before changing the
  `tplink_deco` integration.** It records this fork's current API,
  coordinator, firmware, entity, registry, polling, service and lifecycle
  behavior, together with invariants to preserve across code changes.
- Update that guide in the same PR whenever an integration-specific behavior
  or invariant changes. Confirm new claims against the current code and
  distinguish deployed behavior from pending upstream/backport work.
- Keep general Home Assistant, Python, security, testing and review standards
  in `AGENTS.md`, `AI_POLICY.md` and `CLAUDE.md` when present; do not
  duplicate those general rules in the integration guide. `AI_POLICY.md`
  remains governing policy and applicable repository skills still apply.

## Reusable repository skills

For repeatable workflows, use the relevant repository-local skill after
reading these instructions:

- [Deco upstream synchronization](.agents/skills/deco-upstream-sync/SKILL.md):
  compare and port upstream features in small, compatibility-safe PRs.
- [GitHub merge-reference synchronization](.agents/skills/github-merge-sync/SKILL.md):
  validate secure merge-triggered updates to linked issues and related open PRs.
- [GitHub PR branch maintenance](.agents/skills/github-pr-branch-maintenance/SKILL.md):
  distinguish rebaseability from mergeability and rewrite branches with lease protection.
- [Config flow and test validation](.agents/skills/deco-config-flow-validation/SKILL.md):
  validate Home Assistant forms, polling interval storage and CI regressions.
- [Device-registry service validation](.agents/skills/deco-service-registry-validation/SKILL.md):
  validate Deco device selections, batch actions and service regression tests.
- [Deco device-registry parent links](.agents/skills/deco-device-registry-parent-links/SKILL.md):
  validate master/satellite `DeviceInfo` relationships, legacy/modern API compatibility and existing regression assumptions.
- [Deco runtime discovery](.agents/skills/deco-runtime-discovery-validation/SKILL.md):
  validate immediate node publication, dispatcher ordering and idempotent entities.
- [Deco client restore-state compatibility](.agents/skills/deco-client-restore-validation/SKILL.md):
  recover unavailable client trackers across HA restore APIs and reconcile provisional Decos.
- [Deco polling-switch registry migration](.agents/skills/deco-polling-switch-registry-migration/SKILL.md):
  validate per-config-entry switch IDs and owner-checked in-place migrations.
- [Deco client-device MAC linking](.agents/skills/deco-client-device-linking/SKILL.md):
  validate opt-out settings, stable client identifiers and safe cleanup of old client devices.
- [Deco truncated-response and client-state validation](.agents/skills/deco-transient-response-validation/SKILL.md):
  validate bounded retries, retained authentication, per-node clients and optional performance data.
- [Deco HTTP 5xx client polling backoff](.agents/skills/deco-client-backoff-validation/SKILL.md):
  validate capped delays, partial mesh recovery, session privacy and compatibility.
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
- **PR #19 lesson:** opening a PR and adding `Part of #2` to its description
  did not update issue #2's progress automatically. Verify the issue body
  contains a current PR status entry and preserves the unchecked item before
  reporting the PR handoff.
- The merge workflow `.github/workflows/sync-merged-references.yml` runs
  only for pull requests actually merged to the default branch. It uses
  trusted default-branch code with narrowly scoped write permissions, not
  the untrusted PR head. Follow the GitHub merge-reference synchronization
  skill when modifying its implementation or testing GitHub API behavior.
- At merge time, update only same-repository issues linked explicitly in the
  PR body or GitHub closing-issue references. Check only issue checklist
  lines that explicitly name the merged PR. Notify only related **open** PRs
  and use idempotent bot comments. Never auto-close tracking issues, rebase
  other branches or claim that a merge event validates runtime functionality.
  Manually verify the merged implementation when assessing overall issue
  completion; the workflow does not replace this review.

## GitHub PR branch maintenance and final-head verification

- **PR #36 evidence:** GitHub reported `rebaseable=false` while
  `mergeable=true`, `mergeable_state=clean`, and the PR head was already
  up to date with `main`. These fields describe different conditions:
  never equate a failed rebaseability check with a merge conflict. Compare
  the actual head/base SHAs, merge base, ahead/behind counts and changed
  paths before deciding whether any branch update is needed.
- Rewrite a PR branch only when the user explicitly requests a rebase or
  another justified change. Preserve the intended diff and do not silently
  replace a multi-commit history with a squash. If history is rewritten,
  use `--force-with-lease` (or an equivalent update using the observed
  head SHA as an expected value); reject stale leases instead of
  overwriting concurrent commits.
- **PR #36 follow-up:** changing commit history can reset reviews and
  invalidate earlier CI, even if the resulting file tree is identical.
  Check the final PR head, branch comparison, mergeability, review threads,
  approvals and _all_ required CI jobs again. A running or skipped check
  is not a passed check; `mergeable_state=unstable` while CI runs is not
  proof of a content conflict.
- Automated reviewers may edit PR descriptions or append outdated
  summaries after a push. Re-read the live PR body and issue tracker
  before reporting completion; correct only verified stale claims about
  scope, head SHA or CI. Preserve independently useful review history
  rather than overwriting it unnecessarily. See the
  [PR branch-maintenance skill](.agents/skills/github-pr-branch-maintenance/SKILL.md).

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

## Restored unavailable client identity (upstream #619)

- **Observed failure:** Home Assistant can persist an unavailable device
  tracker without `device_type`. Skipping that restored state permanently
  loses a formerly known offline client even when its stable registry
  unique ID and original name are available. Restore it provisionally as
  a client, while preserving already classified Deco entries.
- **Review lesson (PR #26):** a missing `device_type` can also belong to
  an offline Deco absent from the first router response. Its entity
  registry record can still link to a device with identifier
  `(DOMAIN, entry.unique_id)`. Restore that entity as a **Deco** before
  the provisional client fallback. Do not classify merely because its
  linked device contains **another** Deco MAC: legitimate clients can
  share their parent's device. Test both cases and a late Deco return.
- **Version compatibility:** HA 2025.12 exposes `last_states`; HA 2026.11
  provides `async_get_stored_state(entity_id)` with registry-aware
  storage. Use capability detection and tests for both, rather than
  assuming that the same mapping exists in all supported releases.
- **Malformed restore-state hardening (PR #36):** the verified failure
  path dereferenced `stored_state.state.attributes` without checking the
  nested state or mapping shape. Validate those fields before reading
  `device_type`. Skip only malformed _records_ with a fixed warning that
  excludes entity IDs, names and saved values. A valid mapping without
  `device_type` is not malformed; an unknown discriminator still requires
  the exact Deco registry-identifier check. Do not hide exceptions from
  the restore storage API, registry lookup or initial Deco refresh.
  Test damaged and valid records together, including error propagation,
  with both supported Home Assistant restore APIs.
- **Reconciliation and safety:** skip disabled or non-tracker entities
  and missing restore records. After the successful initial Deco refresh,
  remove provisional clients identified as actual Deco MACs **before**
  creating the client coordinator. Do not clear genuine offline clients,
  change MAC-based entity IDs or modify another config entry's state.
  **Upstream #621 test-parity lesson:** coordinator setup takes a fixed
  positional argument contract. Test its argument ordering, per-entry
  configuration values, actual `timedelta` polling interval and restored
  `original_name` values for multiple offline clients on both supported
  Home Assistant versions. Avoid catch-all `*args, **kwargs` fixtures
  that conceal a changed integration call signature. Such tests improve
  regression coverage but do **not** complete upstream test-suite parity.
  Follow the
  [client restore validation skill](.agents/skills/deco-client-restore-validation/SKILL.md).

## Deco runtime node-discovery ordering (upstream #643)

- **Review finding:** the Deco coordinator previously sent
  `SIGNAL_DECO_ADDED` while its `data` still referred to the old inventory.
  Synchronous tracker, binary-sensor and per-node sensor callbacks therefore
  could not see the newly discovered MAC until a later signal.
- **Rule:** build and assign the full `TpLinkDecoData` snapshot **before**
  calling `async_dispatcher_send`, and return that same snapshot from the
  coordinator. Only signal when new MACs were actually found; retain
  already-known offline nodes and their object identities.
- Use `@callback` for synchronous Home Assistant dispatcher handlers and
  preserve the per-platform MAC deduplication. Master-dependent network
  totals still use the coordinator's post-update listener, not only the
  discovery signal. Test a real coordinator invoking all three platform
  handlers, repeated polls and offline/missing nodes. See
  [the runtime discovery skill](.agents/skills/deco-runtime-discovery-validation/SKILL.md).

## Privacy-safe downloadable diagnostics (upstream #575, fork PR #31)

- **Evidence and boundary:** PR #30 introduced coordinator health sensors,
  while PR #31 added the separate Home Assistant config-entry diagnostics
  download. The export is not a per-device diagnostic, system-log download
  or future Wi-Fi/mobile coordinator export. Do not infer that a sensor
  implies download support, or that an exported function alone proves
  Home Assistant has registered the diagnostic handler.
- **Stable, minimal schema:** export a versioned, JSON-serializable
  **allowlist** of cached coordinator health/status scalars and anonymous
  aggregate counts. Require a privacy review and focused tests for every
  added or renamed field. Never return `config_entry.data`/`.options`,
  entry IDs, MAC/IP/BSSID addresses, client or router names, SSIDs,
  credentials, tokens, cookies, session material, exceptions, individual
  client/device collections or raw firmware responses. Generic payload
  redaction is **not** an alternative to selecting safe fields.
- **Error-label provenance:** record error labels from controlled exception
  **types** or fixed internal markers, never from upstream exception
  messages. An `isidentifier()` or string-length check alone cannot prove
  privacy: a secret containing only letters is also an identifier. Audit
  new error sources before exporting them; add adversarial regression tests
  for both malformed and plausible identifier-shaped private strings.
- **No side effects or false state:** read only the current config entry's
  cached coordinators, without router requests, refresh scheduling or
  entity/registry mutations. Preserve aware ISO 8601 timestamps, meaningful
  zero/null values, paused/backoff/incomplete states and separation between
  multiple config entries. Missing initial data must not invent devices.
- **Verification gates:** inspect the actual diagnostics hook in both
  supported Home Assistant releases. Test exact allowed keys and types,
  JSON serialization, private sentinel exclusion at _all_ nested levels,
  missing data, no additional API calls and multi-entry isolation. Direct
  invocation of `async_get_config_entry_diagnostics` validates the data
  contract, **not** the Home Assistant diagnostics platform registration;
  check discovery separately before claiming UI availability. Consult the
  upstream-sync skill and final-commit CI rules.

## Coordinator health sensors without extra API polling (upstream #575)

- **Observed gap:** the fork exposes coordinator updates but has no
  durable, privacy-safe health metrics or optional sensor entities to
  distinguish actual API failures from paused, deferred or incomplete
  cycles. Upstream #575 tracks update timestamps, response times, errors,
  timeouts and query mode with no new router requests.
- **Rule:** capture health around the actual existing Deco and client
  API poll methods; never change existing client-backoff, retry or
  restoration semantics. Skip updating health for paused, empty-inventory
  and backoff-deferred cycles. Treat an all-failed per-node client cycle
  as incomplete even if the old client dictionary is returned. A valid
  empty list is a successful response. Preserve the last successful
  timezone-aware timestamp across later errors, and sanitize errors
  to exception class names only. Do not log or retain error messages,
  response bodies, credentials, SSIDs or raw client lists.
- **Entity contract:** add opt-in diagnostic sensors to the master
  Deco only, once its inventory is known. Use stable
  `<master_mac>_<metric_key>` unique IDs; disable all health sensors by
  default and keep historical error values available during failures.
  Report `per_node` query mode for the current fork; do not imply the
  global client-list fallback is implemented.
- **Review finding (PR #30):** Home Assistant 2025.12 and 2026.11
  `DataUpdateCoordinator._async_refresh` skip ordinary listener
  notifications when both the previous and current refresh failed.
  Updating `CoordinatorHealth` in memory and overriding sensor
  `available` alone cannot publish subsequent timeout-count, latency,
  or error-type changes. Provide a **health-specific notification path**
  for repeated failures that updates only health consumers, without
  falsely marking the data coordinator successful or forcing all
  unrelated entities to refresh. Register and remove any health
  listeners with their owner, avoiding orphaned callbacks.
  **Applied in PR #30:** `CoordinatorHealth` owns a separate subscriber
  registry and emits each recorded result; health sensors subscribe as
  push-based `SensorEntity` objects and unregister through
  `async_on_remove`. Subscriber exceptions are contained and logged by
  exception class only so they cannot turn a good Deco poll into a failure.
- **Regression:** test success/failure/timeout classification,
  partial-vs-all-failed polls, valid empty replies, skip conditions,
  timestamp timezones, sanitized errors, unchanged API request counts,
  late-master creation, once-per-entry registration, stable device/unique
  IDs and multi-entry isolation. Test _real_ `async_refresh()` behavior
  through two or more consecutive failures on **both** supported Home
  Assistant versions: enabled health sensors must publish each changed
  failure count/error/duration, while unrelated entities and
  `last_update_success` remain correct. Calling only
  `_async_update_data()` does not test listener delivery.
  Follow the upstream-sync skill.

## Non-blocking initial client refresh (upstream #645)

- **Observed startup path:** `async_create_and_refresh_coordinators`
  awaits the first client refresh after Deco discovery. A slow optional
  client-list request therefore holds up Home Assistant entry setup and
  platform forwarding even when restored clients and the Deco inventory
  are already available. Upstream #645 uses entry-owned background tasks
  and `async_refresh()` rather than a debounced refresh request.
- **Rule:** continue awaiting the first **Deco** device-list refresh and
  reconcile provisional Deco/client identities before constructing the
  client coordinator. Do not await the initial optional **client** refresh.
  After all platforms are forwarded, schedule the client's
  `async_refresh()` via `ConfigEntry.async_create_background_task`.
  Using `async_request_refresh()` may create foreground debouncer tasks.
- **Regression:** verify no client API request is awaited during coordinator
  construction; entry setup awaits platform forwarding before scheduling;
  initial task ownership belongs to the same config entry; first-refresh
  failure does not block setup; and previously restored clients, stable
  MAC IDs, connected-client count readiness, shutdown and multiple entries
  remain unaffected. Do not add unsupported wireless/mobile coordinators
  as part of this client-only port. See the upstream-sync skill.

## Startup client-count correctness (upstream #567/#597)

- **Observed failure:** a restored offline client can have a known Deco
  association despite no current connection, and count sensors may be
  registered before a valid node-specific client-list response. Counting all
  historical associations inflates the `Connected clients` diagnostic;
  creating it early misrepresents unverified nodes as having zero clients.
- **Rule:** count only clients with a matching `deco_mac` and truthy
  `online`. Track which Deco MACs have returned a successful list (an
  empty list is valid), independently of all-failed polls, HTTP 5xx
  backoff, paused refreshes and partially successful meshes. Register
  each `<mac>_client_count` entity once, only after that node's first
  valid response; use the normal post-update listener so newly discovered
  nodes get their count later.
- **Regression:** test empty lists, offline/restored clients, grace-period
  presence, failed first polls and recovery, per-node partial success,
  repeated callbacks, multi-config-entry isolation and unchanged unique
  IDs. Do not alter throughput, tracker state or sessions to change counts.

## Client tracker discovery after coordinator refresh (upstream #569)

- **Observed gap:** `SIGNAL_CLIENT_ADDED` is emitted during the client
  coordinator's `_async_update_data`, before Home Assistant commits the
  returned client mapping to `coordinator.data`. A dispatcher-only handler
  can miss the newly discovered MAC when it reads the previous mapping.
- **Rule:** subscribe client tracker discovery to the normal client
  coordinator update listener **as well as** the existing dispatcher.
  Both callbacks use the same MAC deduplication set; unsubscribe both through
  `coordinator_clients.on_close`. Do not change device IDs, client-presence
  behavior, linked-device options or connected-client count semantics.
- **Regression:** simulate the early dispatcher callback and a subsequent
  committed client snapshot. Verify immediate post-refresh discovery,
  exactly-once entity creation after repeated notifications, per-entry
  isolation and unchanged MAC identities and opt-out behavior. See the
  upstream synchronization skill; the separate startup count fixes
  (upstream #567/#597) still require their own implementation and tests.

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

## Independent device-list cadence (upstream #616/#669/#670)

- **Contract:** the existing `CONF_SCAN_INTERVAL` values (10/30/60/120,
  default 30) continue to drive client and performance updates and the
  existing polling select. A new, optional config-entry
  `device_list_interval` controls only Deco inventory requests.
  **Absent means inherit the current main interval**; `0` fetches
  inventory once on initial setup, then only on explicit manual refresh.
  Other values must be integers of at least ten seconds. Do not
  silently change old entries, entity IDs, device registry associations,
  CPU/memory smoothing or the client coordinator's backoff policy.
- **Scheduling:** do not add a third coordinator, extra background
  refresh or periodic timer; check a monotonic timestamp in the existing
  Deco coordinator before each ordinary update. Continue performance
  updates while inventory polling is skipped. On failed device requests,
  preserve the last valid data and do not advance the refresh clock;
  a manual request must bypass interval/startup-only and the pause flag.
  Process new nodes and notify discovery only on actual inventory
  responses. Keep the master identity stable for unchanged MACs.
- **Forms:** preserve the existing string selector for the main cadence.
  Add the new number field using a **serializable continuous schema**
  (`vol.Coerce(int)` and `vol.Range(min=0)`); enforce the disjoint
  valid set (0 or >=10) in explicit setup/options validation, _before_
  authentication or entry updates. Reject booleans, float values and
  malformed inputs; display translated, field-specific errors.
  Store values as integers and do not migrate existing entries simply
  to add the option.
- **Button and privacy:** the new manual refresh button belongs to the
  owning config entry and master Deco, with a stable new unique ID.
  Never log router inventory payloads or access credentials. Export only
  the numeric interval in diagnostics, not new identifiers or lists.
- **Validation:** test first refresh, interval boundaries, startup-only
  performance updates, manual override while paused, failure retries,
  discovery identity, two independent meshes, form serialization on
  both supported Home Assistant versions, integer persistence in setup
  and options flows, rejected values before login and all required
  full-head CI. Only check off the corresponding issue #2 item after
  the complete feature has merged.

- **Failure contracts (PR #34):** reject a non-list device reply,
  invalid/duplicate MAC identifiers and malformed optional signal mappings
  _before_ modifying cached Deco objects or advancing inventory cadence.
  Raise fixed, descriptive exceptions that never interpolate upstream
  content. Keep the last valid inventory, its successful-poll timestamp
  and retry eligibility on failure, **but update health failure counters
  and sanitized exception-type status**; a failed poll is not a success.
  Commit a validated inventory independently from optional performance;
  expected transient/timeout performance failures preserve last CPU/memory
  samples, while authentication and unexpected failures must propagate.
- **Nullable signal-level firmware regression (issue #2):** a missing
  optional `signal_level` was already accepted, but an explicit JSON
  `null` previously failed inventory validation and `TpLinkDeco.update`.
  Treat only missing/`None` as an empty mapping, without changing the
  interpretation of valid measurements. Reject lists, strings, numbers
  and other non-mappings before mutating cached nodes. Exercise both
  direct model handling and real coordinator refreshes, including a
  newly discovered satellite, stable master identity, unchanged optional
  performance, successful-poll cadence and the existing invalid-response
  health contract. Do not log raw router data or weaken validation.
- **Manual failure feedback:** Home Assistant's coordinator `async_refresh`
  can consume an API exception; check `last_update_success` and raise a
  sanitized `HomeAssistantError` for the button. If refresh propagates
  an exception, translate upstream failures into a fixed HA error; retain
  `ConfigEntryAuthFailed` as a **type**, but replace its potentially
  sensitive message. Suppress raw exception chaining (`from None`) and
  do not intercept cancellation. Always clear the forced-request override
  in `finally`, on either result or exception, so failed manual presses
  do not bypass a paused switch; a later press may retry explicitly.
  Test absorbed and propagated failures, error-message redaction, health
  counters, cache preservation, paused behavior and auth propagation
  on both supported HA versions.

## Legacy firmware numeric telemetry (upstream #589, partial backport)

- **Observed on fork `main`:** client rates are converted with direct
  division and Deco CPU/memory fractions with direct multiplication.
  Older firmware may provide these JSON numeric values as strings, which
  raises during an otherwise valid refresh. This is separate from S7's
  legacy **encrypted HTTP login**; numeric parsing alone does not enable
  an unsupported authentication path.
- **Rule:** normalize only client down/up rates and master CPU/memory
  fractions to finite floats before existing arithmetic. Accept finite
  JSON integers, floats and numeric strings (including `"0"`); reject
  booleans, missing/malformed values, infinity/NaN and oversized numbers
  without raising or logging input. Preserve existing byte-rate units,
  identities, CPU/memory raw values and 70/30 smoothing. A malformed
  optional performance measurement must not overwrite the last valid
  reading or interrupt device discovery; zero is a valid measurement.
  **Downstream contract:** existing live throughput sensors sum numeric
  client attributes for online clients. Invalid or absent client rates
  must therefore be stored as numeric `0.0`, **not** `None`, while
  genuinely valid zero is also preserved. Do not change established
  units, sensor IDs or client association/presence when normalizing rates.
- **Validation:** test rates through `TpLinkDecoClient.update`, actual
  coordinator performance refreshes, successful subsequent updates,
  smooth transitions and invalid-value retention. Add boundary tests
  for non-finite numbers and large integer overflow. Verify the actual
  `TplinkTotalClientDataRateSensor` aggregation for mixed valid and
  invalid **online** clients, in addition to testing the numeric helper;
  an isolated parsing unit test cannot prove downstream compatibility.
  **PR #33 review lesson:** when a reviewer proposes changing a
  downstream sum after malformed firmware data, trace the complete
  producer-to-consumer path first. If the established sensor contract
  requires numeric rates, normalizing invalid input to `0.0` at the
  client-update boundary may fix the verified defect with less risk
  than changing every consumer. Prove the chosen correction with the
  actual online-client aggregation test, not just a parsing helper.
  Reply with the verified code path, final-head CI evidence and remaining
  hardware limitations; resolve only after the fix is committed and
  verified, then recheck all unresolved threads. Check behavior against
  the latest `main` and rerun all required CI on the final PR commit.
  Do not mark the upstream S7 legacy-session checkbox complete until
  its distinct authentication/transport functionality is implemented
  and tested.

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

## Bounded multi-node client queries (upstream #556, partial backport)

- **Verified fork contract:** retain per-Deco client queries and their
  existing partial-success state recovery, 5xx backoff, user-configured
  main polling interval, stable MAC-based identities and factual
  `per_node` query-mode diagnostics. Upstream #556 also includes a
  **global-client-list fallback**, which is **not** part of this
  concurrency-only port. Never mark the global fallback complete solely
  because concurrent requests are bounded.
- **Concurrency and retries:** permit **at most two** concurrent
  `client_list` requests _per coordinator_, using an async semaphore
  (never `sleep()` or a global lock). Pass a request-local timeout retry
  budget of **zero** to each per-node request to avoid multiplying
  timeouts across a mesh. Other authenticated API calls keep the
  configured retry budget. Validate the override as a non-negative
  integer, rejecting booleans and strings without contacting the router.
- **Failure isolation:** a timed-out node is **incomplete**, not a valid
  empty client list and not an HTTP 5xx backoff event. Successful peers
  still update; cached online state, last activity and node associations
  of failed peers survive. **Health metrics:** if one or more nodes
  time out during a client poll, increase the client timeout counter
  **once per poll cycle**, including a partially successful cycle.
  Keep a successful timestamp and zero consecutive failures for valid
  peer responses, and retain a failure count for all-failed responses;
  publish the timeout type to health sensors in the same notification.
  Do not record multiple coordinator failures for multiple failed nodes.
  Unexpected and authentication errors still propagate. On an exception
  or cancellation, cancel and await all scheduled sibling requests,
  including ones awaiting the semaphore; never leave abandoned router
  requests or leak session messages.
- **Tests:** assert a deterministic maximum of two in-flight requests
  with more than two nodes, sibling cleanup after unexpected exceptions
  and cancellation, true timeout-vs-5xx classification, partial recovery,
  a zero-override request with the real API retry wrapper and unchanged
  ordinary API retry defaults. Keep existing 5xx/backoff and truncated
  response tests green on both supported HA versions, plus final-head
  pre-commit/HACS/Hassfest. Do not claim hardware validation without
  physical router checks.

## Capped HTTP 5xx backoff for Deco client polling (upstream PR #624)

- After a client-list HTTP 5xx response, pause further client-list requests
  per config entry for 30, 60, 120, 240, then at most 300 seconds.
  Use monotonic time and non-blocking skips, **not** event-loop sleeps.
  Do not conflate 5xx backoff with configured timeout or transient-body retries.
- Preserve valid credentials and existing clients (including `online`,
  `last_activity`, and node identity) during skipped polls. When one node
  fails, still accept successful peer-node replies. When all nodes fail,
  retain every previous client, including those with no known Deco mapping.
- Reset the delay only after all queried nodes provide valid responses;
  an empty successful list is valid and retains the current
  `consider_home` semantics. Non-5xx HTTP/auth failures still propagate.
- Never interpolate `aiohttp.ClientResponseError` or its request URL
  into client-list logs because LuCI `stok` tokens can occur in URLs.
  Test sanitized logging, the 300-second cap, recovery and multi-node
  failures against both Home Assistant versions. Use the
  [client backoff validation skill](.agents/skills/deco-client-backoff-validation/SKILL.md).
- Dedicated global-client-list fallback and coordinator-health sensors
  are separate upstream work. Do not invent them to complete backoff.

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
  Cover request dispatch and response-body failures, retry exhaustion, zero
  retries, multi-node partial success, successful empty lists, privacy and
  previous regression expectations.
  Follow the transient-response validation skill for the complete workflow.

## Transport errors versus expired authentication (upstream PR #598)

- A disconnected HTTP transport or connector failure does not by itself
  prove that the router's authentication token, cookie, or sequence expired.
  Preserve session state on these temporary failures so the next refresh can
  reuse credentials without creating a new Deco admin session.
- Continue to invalidate authentication when the router explicitly returns
  HTTP 401/403 or an established authentication-expiry response. Preserve
  `ClientConnectorError` propagation without clearing the session; only
  incomplete payloads and server disconnects enter the bounded
  `TransientConnectionException` retry path from PR #19.
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

## Optional client-device MAC linking (upstream #605)

- **Compatibility invariant:** a client tracker must retain its MAC-derived
  `unique_id` regardless of `link_client_devices`. The default is
  `True` to preserve existing Home Assistant device matching; opting out
  suppresses the scanner MAC property but makes the address available
  as a client state attribute. The physical Deco tracker and its device
  relationships must not change.
- **Registry safety:** disabling matching does not automatically sever
  cross-integration device links. Permit manual removal only for a
  MAC-only legacy client device owned **exclusively** by the requesting
  config entry; refuse shared, foreign or identified devices and every
  physical Deco device. See the
  [client-device MAC linking skill](.agents/skills/deco-client-device-linking/SKILL.md).
- **Upgrade behavior (PR #24 review):** `ConfigEntry.version` is
  immutable in the supported Home Assistant releases. Migrating version
  6→7 (and older versions) must stage the new version locally and call
  `hass.config_entries.async_update_entry(entry, data=..., version=...)`
  **once**; never assign `entry.version` directly. Preserve explicit
  `False` opt-outs. Verify this with a **real** `ConfigEntry`, not
  `SimpleNamespace` that silently permits invalid attribute writes.
  Cover config/options persistence, form serialization, multiple entries,
  stable tracker IDs and owner-only cleanup in regressions.

## Per-entry polling-switch identity migration (upstream #655)

- The historical polling-switch unique ID `tplink_deco_polling` is shared
  between config entries. New switches use
  `tplink_deco_polling_<config_entry.entry_id>` so independent Deco
  installations do not collide in the Home Assistant entity registry.
- Look up the legacy entry with `entity_registry.async_get_entity_id`
  and migrate **only when its recorded `config_entry_id` matches** the
  currently setting-up integration entry. Use
  `entity_registry.async_update_entity(..., new_unique_id=...)` before
  `async_add_entities`; never delete/recreate the entity or rename its
  Home Assistant `entity_id`. Leave another entry's old switch untouched.
- Skip nonexistent, stale or already-migrated entries and guard against
  conflicts when the scoped ID already exists. Keep the original visible
  name, icon, services, refresh semantics and master Deco device link.
- **Downgrade limitation (review PR #22):** once the legacy
  `tplink_deco_polling` registry unique ID is migrated, older integration
  versions using that global ID cannot rediscover the migrated switch and
  may create another entity. Document downgrades across this migration as
  unsupported in the user-facing README; preserve the in-place forward
  migration and advise making an entity-registry backup before upgrading.
- **Stateful migration-regression lesson (PR #22 CodeRabbit finding):**
  simply parametrizing both config-entry setup orders did not verify the
  real registry transition: the original mock still found the legacy
  `unique_id` even after `async_update_entity`. For registry or persisted
  identifier migrations, use a real test registry or a stateful double
  whose lookups reflect successful writes. Assert the legacy identity is
  absent afterwards, the migrated identity still resolves to the same
  `entity_id`, a separate entry keeps its own distinct identity, and
  only the owner may migrate. Test both setup orders and idempotent
  reloads; mock call counts alone cannot prove these invariants.
- Always inspect earlier regression tests for assumptions about stable
  `unique_id` values, especially `test_via_device_registry_links.py`.
  Retain existing entity/device identifier checks while updating only
  the intentional polling-switch unique ID expectation. Run both
  supported HA versions and follow the
  [switch migration skill](.agents/skills/deco-polling-switch-registry-migration/SKILL.md).

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
- **CI bootstrap failure lesson (PR #30):** the repository's GitHub Actions
  policy requires every external `uses:` reference to be pinned to a verified
  **full-length commit SHA**. Jobs using floating references such as
  `actions/checkout@v6`, `actions/setup-python@v6.2.0`,
  `hacs/action@main` or `home-assistant/actions/hassfest@master` can
  fail at `Set up job` before any test or linter executes. Check actual
  job logs and separate workflow-policy failures from source failures.
  Fix any affected workflow in a deliberately scoped workflow change
  using upstream-verified action commit SHAs, preserving versions and
  required checks; never guess SHAs or relax the allowlist/pinning policy.
  An attempted run stopped during action setup is **not** a test result.
- **PR #30 regression lesson (312 tests on both HA versions):** when
  changing config-entry startup or introducing optional diagnostic entities,
  revisit existing tests that mock the whole integration, not just new
  feature tests. Startup fixtures must provide both
  `COORDINATOR_DECOS_KEY` and `COORDINATOR_CLIENTS_KEY`, including a
  mocked async client refresh, so tests exercise the real setup contract
  instead of failing with an irrelevant `KeyError`. Assert existing
  throughput totals by sensor class/unique ID, not by the total size of
  `async_add_entities` batches that can legitimately include additional,
  disabled-by-default diagnostics. In config-flow tests, import the
  canonical Home Assistant `CONF_SCAN_INTERVAL` key (currently
  `interval_seconds`) instead of inventing `scan_interval`, and verify
  integer persistence after selector input. Check undefined test names
  and imports with Flake8 before treating pytest failures as runtime bugs.
  After applying precise formatting fixes from the full-repository
  pre-commit log, require fresh green Python 3.13/HA 2025.12 and
  Python 3.14/HA 2026.11 pytest, pre-commit, HACS and Hassfest runs on
  the **same final head SHA**. A 312/312 result from an earlier head
  does not validate later documentation or code changes.
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
