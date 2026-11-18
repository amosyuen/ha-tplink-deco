# TP-Link Deco — Home Assistant integration behavior and invariants

This guide describes **behavior specific to this repository's `tplink_deco`
integration**. Read it before changing the integration's API, coordinators,
entities, config flow, device registry, services or lifecycle.

General Home Assistant development, Python, security, testing and review
standards belong in [`AGENTS.md`](AGENTS.md) and
[`AI_POLICY.md`](AI_POLICY.md), as well as `CLAUDE.md` **when present**.
This file does not replace those instructions or the task-specific procedures
in [`.agents/skills/`](.agents/skills/). The repository's governing policy
remains `AI_POLICY.md`.

**Historical baseline:** fork `main` at
`a657aa06636884404fc1ec08ae9462f244d10047` (15 November 2026),
before subsequent fixes and optional WLAN support. It is **not** a
claim that this old commit represents the present integration or
upstream architecture. Deco discovery (PR #25), client restoration
(PR #26), tracker discovery (PR #27), per-node client counts (PR #28),
non-blocking initial client refresh (PR #29), coordinator health
(PR #30), privacy-safe diagnostics (PR #31), numeric-string telemetry
(PR #33), independent status polling (PR #34), bounded client-list
concurrency (PR #35), restore-state error hardening (PR #36), and
read-only WLAN status (PR #41) have since merged into the fork.
The privacy-safe SSID opt-in contract introduced by PR #42 and
optional mobile WAN usage from PR #43 have both merged into `main`.
Their physical-firmware validation remains a separate limitation.

## 1. Integration boundary and data ownership

- Home Assistant integration domain: `tplink_deco`. The manifest declares
  `integration_type: hub` and `iot_class: local_polling`, with configuration
  through a config flow.
- The integration forwards these six platforms:
  `device_tracker`, `sensor`, `binary_sensor`, `switch`, `select`
  and `button`. The authoritative list is `PLATFORMS` in `const.py`;
  confirm it before changing this guide.
- With the scoped mobile data backport, each configuration entry stores
  four independent coordinators under `hass.data[DOMAIN][entry_id]`:
  **two required** for mesh/client data and **two optional** for read-only
  WiFi status and mobile WAN usage:
  - `COORDINATOR_DECOS_KEY` / `TplinkDecoUpdateCoordinator` discovers mesh
    nodes, identifies the master and obtains optional performance readings.
  - `COORDINATOR_CLIENTS_KEY` / `TplinkDecoClientUpdateCoordinator` polls
    client lists **per known Deco node**, retains known clients and determines
    connection state.
  - `COORDINATOR_WIRELESS_KEY` / `TplinkDecoWirelessUpdateCoordinator` polls
    Main, Guest and IoT network enabled flags independently; unsupported
    firmware does not prevent the required coordinator refreshes.
  - `COORDINATOR_MOBILE_KEY` / `TplinkDecoMobileDataUpdateCoordinator`
    polls read-only WAN consumption in KiB every five minutes **only**
    for a master recognized as a 4G/5G model. It cannot block setup or
    required coordinator refreshes.
- The client coordinator uses its paired Deco coordinator's device inventory
  and pause flag. It must not treat a peer configuration entry's data or API
  session as its own.
- The router's LuCI API is accessed locally using the existing authenticated,
  encrypted `TplinkDecoApi`. Do not replace the fork's per-node client polling
  with upstream global-list/other coordinator behavior without a separate
  explicitly scoped change.

## 2. Persistent identity and relationships

| Object                        | Identity contract                                                     | Source              |
| ----------------------------- | --------------------------------------------------------------------- | ------------------- |
| Deco device                   | Registry identifier `(DOMAIN, deco.mac)`                              | `device.py`         |
| Deco tracker                  | Stable MAC-based entity identity                                      | `device_tracker.py` |
| Client tracker                | Stable client MAC; optional display name/hostname does not replace it | `device_tracker.py` |
| Per-Deco Down/Up              | `<deco_mac>_down` / `<deco_mac>_up`                                   | `sensor.py`         |
| Network-wide Down/Up          | `<master_mac>_total_down` / `<master_mac>_total_up`                   | `sensor.py`         |
| Connected clients             | `<deco_mac>_client_count`                                             | `sensor.py`         |
| Deco online / Internet online | `<deco_mac>_online` / `<deco_mac>_internet_online`                    | `binary_sensor.py`  |
| Polling interval select       | `<entry_id>_polling_interval`                                         | `select.py`         |

- Register or resolve the master before linking a satellite. When
  `DeviceInfo` supports `via_device_id`, link a satellite to the **actual
  registry ID** for the master associated with this entry; on older
  supported Home Assistant versions use `via_device=(DOMAIN, master_mac)`.
  The master never links to itself. Missing master/context must not invent
  a parent relationship.
- Keep device identifiers separate from human-readable names. Names, MAC
  formatting, optional firmware attributes and Deco-master discovery can
  change independently of entity/device identity.
- **Polling switch:** [PR #22](https://github.com/HiDiHo01/ha-tplink-deco/pull/22)
  is merged. `switch.py` uses one scoped unique ID per config entry,
  `tplink_deco_polling_<entry_id>`. The legacy global ID
  `tplink_deco_polling` is migrated **in place** only for the owning
  config entry, preserving the user's existing Home Assistant entity ID.
  Downgrading to a release expecting the old shared ID is unsupported.

## 3. Mesh discovery, restoration and naming

- `TpLinkDecoData` contains `master_deco` and a MAC-keyed `decos` dictionary.
  The Deco coordinator reuses existing node objects when a node reappears.
  If a previously known node is absent from a valid device-list response,
  retain that object and mark it offline rather than silently deleting its
  tracker/device.
- Before the first entry refresh, `async_create_config_data` reconstructs
  previously known Deco/client objects from **device-tracker registry
  entries and restored state**. The router's connected-client response is
  not a complete historical client inventory. **Restoration behavior:**
  for a stored tracker whose `device_type` attribute is missing (for
  example, an unavailable entity), first inspect its linked device
  registry identity. If that device has the exact identifier
  `(tplink_deco, tracker.unique_id)`, restore it as a Deco even when
  absent from the initial router response. A client sharing the parent
  Deco's device has a **different MAC** and must not be reclassified.
  Restore the remaining unclassified trackers as provisional MAC-keyed
  clients. Exclude disabled trackers and entries without saved state.
  HA 2026.11 exposes `async_get_stored_state(entity_id)`; HA 2025.12
  uses `last_states`. After a successful first Deco refresh, discard
  provisional client records whose MAC is confirmed in `decos` before
  constructing the client coordinator. Preserve genuine offline clients
  and all registry entity IDs. Malformed stored records lacking a nested
  state or attribute mapping are skipped with privacy-safe warnings,
  allowing other offline clients to restore. Missing `device_type` in
  an otherwise valid mapping still uses the registry fallback; unknown
  discriminator values also require the exact Deco identifier check.
- `TpLinkDecoClient` tracks MAC, node association (`deco_mac`), `online`,
  `last_activity` and last-known throughput and connection metadata. A
  missing or incomplete poll must not erase these fields.
- Deco display name precedence: nonempty decoded custom nickname, then
  decoded/normalized firmware nickname, then MAC. Client display names
  support the existing configured prefix/postfix; the client tracker's
  `hostname` reflects that composed name. Name updates never change
  identities.
- Firmware can return Base64/UTF-8 text, plain text, legacy
  `<Error Decoding ...>` wrappers or missing/empty fields. Normalize
  names and preserve supported optional wireless/backhaul fields
  without requiring a specific firmware variant. **Optional-signal
  compatibility in this PR:** `signal_level` may be absent, explicitly
  `null`, or a mapping. Missing/`null` values both yield unavailable
  signal measurements while allowing valid Deco discovery and cached
  identities to continue; other non-mapping types remain invalid and
  must be rejected before changing coordinator state. The
  coordinator validates the whole inventory before mutating cached
  nodes, while `TpLinkDeco.update` checks the signal mapping at
  the start of a direct model update. This prevents partial changes
  to existing model fields for invalid `signal_level` values.
  It does not imply all unrelated firmware fields are handled
  transactionally. The pre-PR `main` baseline rejected explicit
  `null`.
- Discovery: new nodes dispatch `SIGNAL_DECO_ADDED` and new clients
  dispatch `SIGNAL_CLIENT_ADDED`. The complete new `TpLinkDecoData`
  snapshot is published to `coordinator.data` _before_ signaling, so
  synchronous `@callback` handlers see newly added MACs immediately.
  Tracker, binary-sensor and per-node sensor platforms avoid adding the
  same known MAC twice. Master-dependent **network-total** sensors
  continue to use the coordinator's normal **post-update listener**,
  which registers totals once per entry. Keep known offline nodes.
- **Client tracker discovery (merged in PR #27):** `SIGNAL_CLIENT_ADDED`
  can fire before the client coordinator's refreshed `data` is committed.
  Retain that dispatcher for compatibility, but also register a normal
  client-coordinator listener to discover clients after the new snapshot
  becomes visible. The shared MAC-keyed set prevents duplicate trackers;
  both subscriptions are removed during coordinator shutdown. This does not
  change the separate connected-client count sensors or offline grace period.

## 4. Client presence and measurement semantics

- The router's `client_list` currently contains connected clients; it is
  not authoritative for permanently removing historical trackers.
- A **successful empty** client list is different from a **failed** list
  request. Apply the existing `consider_home` grace-period behavior after
  valid polls; do not convert a truncated, timed-out or HTTP 5xx response
  into an empty result that marks clients offline.
- When a single node fails, update clients from successful peer nodes and
  preserve the former states and associations of clients belonging to the
  failed node. When **all** node client polls fail, retain the complete
  previous client dictionary, including clients lacking a known Deco
  association.
- **Merged in fork PR #53 (2026-11-17):** regular per-Deco
  client-list replies undergo whole-response preflight before cached
  clients are updated. Missing, blank, non-string or duplicate client
  MAC identifiers and non-string/non-null client names are rejected
  with a fixed, privacy-safe error. Invalid IP data handled by the
  existing `filter_invalid_ip` `ValueError` path is normalized to
  `None`, rather than rejecting an otherwise valid reply.
  Previously known clients and successful-poll readiness survive an
  invalid list; valid empty lists and partial timeout recovery retain
  their established behavior. Discovery DEBUG messages no longer
  interpolate client MACs. The implementation and focused regressions
  are on `main` (merge commit `35d1c0c`); physical firmware testing
  remains unverified.
- Down/Up throughput aggregation includes only clients with truthy
  `online` status. Per-Deco data rates additionally require the matching
  `deco_mac`; network-wide totals include online clients across nodes.
  Cached rates from offline or unknown-status clients must not contribute
  to live throughput totals.
- **Connected clients (merged in PR #28):** count only associated clients
  whose `online` value is truthy; previously restored disconnected clients
  remain available as trackers but do not inflate the connected-client total.
  Delay count-entity registration until the client coordinator has received
  a valid (including empty) list from that particular Deco. All-failed polls,
  paused polling and backoff do not establish a valid count. A valid peer
  cannot establish an unpolled Deco's count. Preserve the existing
  `<deco_mac>_client_count` unique ID, `consider_home` grace period and
  throughput/diagnostic entities. A grace-period client is still counted
  while `online` remains true.

## 5. Poll scheduling, retries and performance

- The existing **main scan interval** has choices 10, 30, 60 and 120
  seconds (default 30). It drives the client and performance refresh
  cadence and the existing polling-interval select.
- **Merged in [PR #34](https://github.com/HiDiHo01/ha-tplink-deco/pull/34) (upstream #616/#669/#670):** a separate
  `device_list_interval` determines how often the Deco coordinator
  fetches mesh status. Missing values inherit the main scan interval
  for backward compatibility; `0` requests inventory at startup only.
  Other accepted intervals are integers of at least 10 seconds. Cached
  node identities stay available and optional performance requests
  continue when a device-list request is skipped. A master-linked
  `Refresh Deco status` button forces immediate inventory discovery,
  including when the main polling switch is paused. Unsuccessful
  device-list requests retain their last-success timestamp for the
  next scheduled or manual retry. Invalid or duplicate router inventory
  entries are rejected before changing cached devices. A failed manual
  press shows a sanitized HA error and clears the forced request so
  paused polling stays paused. Authentication failures retain their
  distinct error type. Config/options validation remains separate from
  the serializable numeric form; no new timer or coordinator is added.
- The Deco coordinator's `paused` state gates its own refresh, and the
  client coordinator honors the same pause flag. The switch controls this
  flag; turning polling back on requests a refresh.
- The Deco coordinator requests the device list and optional master
  performance. Master CPU/memory values have raw readings and smoothed
  readings (currently 70% previous/30% new); missing measurement fields
  preserve the last known values. **Merged in [PR #33](https://github.com/HiDiHo01/ha-tplink-deco/pull/33):**
  normalize finite numeric firmware strings for client down/up rates
  and CPU/memory before arithmetic. Malformed/missing client rates
  become numeric zero so existing per-Deco and network throughput
  aggregation remains safe for online clients. Invalid optional
  CPU/memory fields preserve the previous raw and smoothed readings;
  valid zero is not treated as missing. Keep the existing units,
  identities and 70/30 smoothing. This does **not** add the separate
  encrypted outer session needed for some legacy S7 firmware.
  Optional performance failures caused by bounded transient-response
  retries or timeouts preserve previous CPU/memory samples without
  discarding a validated device-list update. Authentication and other
  unexpected API errors still fail the coordinator refresh.
- Truncated payloads and server disconnects have bounded retries using
  the configured `timeout_error_retries` count, independently of timeout
  and one-time re-login retry budgets. A temporary transport failure does
  not itself invalidate a known authenticated session.
- HTTP **5xx** on per-node client polling triggers **one global**
  `client_list` query using `device_mac=default` when the master is
  known. Successful global replies assign live clients to the real
  master's MAC because the global API does not provide trustworthy
  node associations. Satellite counts can temporarily be less precise.
  A failed global query leaves valid peer results and cached clients
  intact; authentication and non-5xx failures still propagate.
- The independent per-entry **30, 60, 120, 240, up to 300 second**
  non-blocking backoff limits repeated broken **per-node** requests.
  After a successful global fallback, one global query per regular
  refresh remains available throughout the per-node cooldown.
  Once all per-node responses succeed after expiry, their real node
  assignments return, query mode resets to `per_node` and backoff clears.
  Paused polling and device/inventory refreshes remain unaffected.
- Non-5xx HTTP or explicit auth-expiry responses do not silently enter the
  5xx backoff path. Backoff does not replace API-level retry limits.
- **Merged in fork PR #35 (upstream #556, partial):** the client
  coordinator permits at most two simultaneous per-node client-list
  requests per configuration entry. Each request disables extra
  timeout retries without changing other API defaults. A node timeout
  is incomplete, so successful peers still update while the failed
  node's cached clients survive. Health counts timeouts once per poll
  cycle, including partial success. Unexpected failures and cancellation
  cancel and await outstanding sibling requests and semaphore waiters.
  **Global fallback merged separately in fork PR #40**, preserving
  the existing per-node zero-timeout-retry override.

## 6. Router session and protocol behavior

- `TplinkDecoApi` holds the runtime host, token (`stok`), authentication
  cookie and sequence for the encrypted local LuCI session. Do not
  invalidate an otherwise valid session solely because a connection
  drops, a payload is truncated or client polling reports HTTP 5xx.
- HTTP **401** and **403** clear authentication, but differ in retry
  behavior: 401 is propagated as an HTTP error; 403 is converted to
  `ForbiddenException` and enters the existing bounded re-login flow.
  Authenticated API `error_code=-5002` (including supported decrypted
  error fields) also enters that re-login flow. An expired session gets
  **at most one** re-login attempt. Do not treat an initial-login error
  or a request to an unrelated endpoint as authenticated session expiry.
- Generic HTTP **403** errors are normalized to a fixed,
  privacy-safe `ForbiddenException` without retaining the original
  token-bearing HTTP error as cause/context; the standard one-relogin
  retry uses a refreshed LuCI URL and cookie. HTTP 401 keeps its
  existing propagated response-error type. Authentication failures
  are logged by controlled status only, not the original request URL
  or router message. Real firmware behavior remains unverified.
- Generic HTTP 4xx/5xx errors, connector failures, other transport
  exceptions and timeouts use fixed status/type labels for integration
  logs rather than interpolating upstream exception messages or
  call-site context that may contain private device identifiers.
  Their previously established error types and authentication/retry
  behavior remain unchanged; exceptions propagated by non-private
  endpoints are not themselves redacted by this logging change.
- Malformed device/client lists and router login metadata, rejected
  LuCI JSON responses and encrypted response decode failures are
  logged using fixed labels or exception types rather than raw
  firmware payloads or RSA/session parameter values. Numeric API
  codes remain available in rejection exceptions; untrusted
  string codes and decrypted login response dictionaries are
  not exposed. This does not change successful data retrieval,
  ordinary authentication retries or registered entities.
- Concurrent callers share a single router login attempt. Cancelling
  a waiter does not cancel that in-flight attempt; cancelling its
  owner notifies waiting callers, clears partial local authentication
  and permits a later fresh login. Owner failures are propagated
  without leaving pending shared futures; cancellation is not
  retried as ordinary authentication failure.
- A same-host HTTP **307 → HTTPS** redirect may update the **runtime**
  API origin, including its port, to preserve subsequent authenticated
  requests. A cross-host redirect must not rewrite the configured router
  endpoint or its persisted config-entry data.
- Device lists, per-node client lists, performance reads and Deco reboot
  use the existing encrypted authenticated API methods. Only a reboot
  service action should submit a router reboot; read-only discovery and
  diagnostics must not write router configuration.
- Logout is best effort on successful entry teardown, and local auth
  state is cleared afterwards. Home Assistant's shared aiohttp session
  belongs to Home Assistant and must not be closed by this integration.

## 7. Entity and service contracts

- `device_tracker` exposes both mesh nodes and clients using existing
  MAC-based identities. Network/mesh data such as BSSIDs, optional
  wireless backhaul values and connection metadata appear as read-only
  attributes when supplied by firmware. Client trackers keep their MAC
  as the stable entity `unique_id` regardless of the opt-out setting
  `link_client_devices`. Default `True` retains device matching by
  scanner MAC; `False` suppresses automatic MAC matching while exposing
  `mac` in the client's state attributes. Physical Deco MAC addresses
  and master/satellite device identities are unaffected. Existing
  cross-integration device matches are not automatically detached.
- `binary_sensor` retains per-node `Internet online` and `Deco online`
  diagnostic states, and also provides read-only Main/Guest/IoT WiFi
  enabled-state sensors **when supported by the router firmware**. Main
  WiFi is disabled by default in the entity registry; missing/unknown
  network states do not produce new entities. These wireless entities
  are linked to the active master Deco, independently of per-node status.
  Optional SSID state attributes appear **only** when the per-entry consent
  setting `expose_wifi_ssids` is explicitly `true`; that setting defaults
  to `false` on new and existing installations.
- `sensor` exposes Down/Up totals per node and across the network,
  per-node `Connected clients` diagnostics and optional diagnostic
  readings (IP address, BSSIDs, backhaul type/rate and CPU/memory).
  Diagnostic entities are created when their initial values are present
  and are disabled by default in the registry. No new diagnostics should
  implicitly delete existing entities.
- **Coordinator health diagnostics (merged in PR #30):** attach eight
  disabled-by-default read-only sensors to the master Deco: last successful
  update, API response time and last error for each existing Deco/client
  coordinator; client timeouts and query mode. Timestamps are UTC-aware,
  durations use milliseconds, error values contain only exception class
  names; query mode reflects the last valid `per_node` or `global`
  strategy. Stable identities use `<master_mac>_<metric_key>`.
  A paused, backoff-skipped or no-device cycle does not change health;
  completely failed client lists count as unsuccessful, even if client
  state is retained. PR #30 itself made no additional router calls and did
  not include the diagnostics download (added separately by PR #31). The health sensors stay readable when
  polling fails and are registered once when the master is available.
  **PR #30 review correction (merged):** HA 2025.12
  and 2026.11 suppress ordinary coordinator-listener callbacks on
  consecutive failed `async_refresh()` calls. New health sensors instead
  use a separate, push-only `CoordinatorHealth` notification channel,
  updated on each measured success, error or incomplete poll. Health
  callbacks unsubscribe on entity removal, never trigger unrelated
  entity refreshes and cannot turn a successful API poll into a failure.
  The merged regressions exercise actual `async_refresh()` transitions;
  both Home Assistant test matrices, pre-commit, HACS and Hassfest passed.
  Physical hardware validation remains unverified.
- **Privacy-safe downloadable diagnostics (merged in PR #31):** the
  Home Assistant `async_get_config_entry_diagnostics` hook exports
  cached Deco/client coordinator health and aggregate online/known
  counts. The snapshot is JSON-serializable and makes no router API calls.
  It excludes configuration data/options, credentials, cookies, tokens,
  MAC/IP/BSSID addresses, SSIDs, names, raw client/device listings and
  firmware payloads. Malformed error values are replaced with
  `UnknownError`. Missing coordinator data produces null/zero health
  readings. Each export is isolated to one configuration entry; device
  diagnostics remain unimplemented. Manual system-log export was merged in PR #44; it remains separate
  from Home Assistant diagnostics.
- `switch` controls polling. `select` chooses the main polling interval
  and persists the selected integer in the config entry before reload.
- The three existing per-entry services are `tplink_deco.reboot_deco`,
  `tplink_deco.pause_polling` and `tplink_deco.resume_polling`.
  PR #44 added a separate integration-wide, once-registered
  `tplink_deco.download_system_log` action, which resolves its loaded
  config entry at invocation. For `reboot_deco`, resolve each
  selected Home Assistant device registry
  entry to a nonempty `(DOMAIN, MAC)` identifier; reject an invalid
  selection **before** sending any reboot command. Device-registry
  records may carry additional unrelated identifiers.
- Do not silently enable upstream syslog forwarding or **unscoped
  wireless features** while maintaining existing entities. Manual
  system-log export merged in PR #44; compressed snapshots merged
  in PR #45. Read-only WLAN status merged in PR #41; optional SSID
  attributes merged in PR #42 and remain disabled unless per-entry
  boolean consent is explicitly `true`. Read-only mobile usage
  sensors merged in PR #43. Remaining unrelated work is tracked in
  [issue #2](https://github.com/HiDiHo01/ha-tplink-deco/issues/2).

## 8. Config flow, setup, reload and unload

- Config-flow version **7** supports first setup, reauthentication and
  options. The main scan interval is displayed with string selector
  options but persisted as a supported **integer**. Invalid intervals
  must be rejected before testing router credentials or updating
  the config entry.
- The English and Dutch setup/options labels use the actual Home
  Assistant scan-interval form field `interval_seconds`; the previously
  stale canonical `scan_interval` label has been corrected. Dutch
  translations also cover existing timeout, SSL, name-prefix/postfix,
  reauthentication and host-error labels while retaining legacy
  translated titles and validation messages. This affects only displayed
  form text, not persisted config-entry keys or migration behavior.
- **Merged in fork PR #55 (2026-11-17; `522d4d3`):** Slovak and
  Swedish setup/options translations cover the existing
  `device_list_interval`, polling-interval validation and
  reauthentication abort keys. Their canonical-key regression is on
  `main` alongside `en` and `nl`.
- **Merged in fork PR #56 (2026-11-18; `b2e4f98`):** French now
  includes 39 formerly missing canonical setup/options,
  authentication, error and abort keys while retaining its 16
  existing strings. The French parity regression is on `main`.
- **Proposed in fork PR #57 (not yet merged):** Norwegian Bokmål
  gains 39 missing canonical setup/options and error keys, preserving
  the **exact** 16 original text values. European Portuguese (`pt`)
  and Brazilian Portuguese (`pt-BR`) each gain 31 formerly missing
  canonical paths, including actual `options.step.init` fields,
  interval errors and reauthentication. The existing 31 text values
  per Portuguese locale and legacy `options.step.user` labels remain
  unchanged. The PR regression checks canonical key coverage for
  all eight shipped catalogs, actual `interval_seconds` fields,
  nonempty Portuguese translations and preserved regional labels.
  Native-language proofreading and physical hardware checks remain
  unverified. No runtime settings, config entry storage, existing
  entity identifiers or migrations change in this PR.
- Existing config-entry fields include host, username/password,
  connection timeout, bounded timeout retry count, TLS verification,
  `consider_home`, optional Deco/client name prefixes/postfixes and
  `link_client_devices` (defaults to `True`). Version 6 entries migrate
  to version 7 with this default through
  `hass.config_entries.async_update_entry`, without modifying the immutable
  `ConfigEntry.version` directly. The setting is independent per entry.
  Preserve existing field meanings and migration paths for older
  config-entry versions.
- Config-flow credential checks return existing translated `invalid_auth`,
  `invalid_host`, `timeout_connect` or `unknown` form errors for expected
  and unexpected ordinary failures. Router exception messages and secret-bearing
  URLs are not logged; a cancellation still propagates. Temporary coordinators
  must finish their shutdown before a successful credential check is accepted.
  Options changes are staged in a copy, saved only after verification,
  and adopted by the handler only after Home Assistant accepts the write.
  Failed verification or persistence cannot change the handler's in-memory
  settings; failed verification does not change the stored entry.
  Reauthentication still merges credentials into the existing settings
  without blanking optional names.
- Legacy MAC-only client device registrations may be removed manually
  when linking is disabled, but only when the device belongs exclusively
  to the requesting config entry and has no other integration identifiers.
  Do not permit physical Deco devices or shared/foreign devices to be
  removed by this cleanup hook.
- On setup, first **await** the Deco coordinator's device-list refresh so
  provisional client/Deco identities can be reconciled safely. Restore
  known objects and **await** forwarding all existing platforms before
  registering entry services and the configuration update listener.
  Do not finish entry setup while platform setup is still pending.
- **Initial client refresh (merged in PR #29):** after platform forwarding,
  schedule `clients_coordinator.async_refresh()` using the config entry's
  `async_create_background_task`. Do not await the optional client request
  during coordinator construction or use `async_request_refresh()` for this
  initial task: that method may generate a foreground debouncer task.
  Existing restored client trackers remain visible until client polling
  completes; later scheduled, manual and entity-driven updates remain
  unchanged. The first successful per-node poll still determines when its
  connected-client count sensor is created.
- Entry unload first asks Home Assistant to unload forwarded platforms.
  If any unload fails, keep the active entry, coordinators and session
  intact. After success, shut down scheduled coordinator updates,
  release the integration's dispatcher/coordinator listeners, attempt
  router logout and remove stored entry data.
- The pause/resume services are currently registered against the active
  entry's callbacks; service registration/removal across multiple loaded
  entries is not a proven isolated behavior. Any redesign here needs
  explicit multi-entry coverage rather than an assumed guarantee.

## 9. Integration-specific change checklist

Before merging a change that touches the areas above, confirm the relevant
invariants for the _modified subsystem_:

1. **Identity:** existing MAC-based trackers, device identifiers, entity
   unique IDs, satellite links and user-assigned entity IDs remain stable,
   unless a documented in-place migration has been tested.
2. **Presence:** previous clients survive failed polls; valid empty lists,
   offline grace periods, successful peer nodes and late master discovery
   remain distinguishable.
3. **Polls:** global pause/resume behavior, configured scan intervals,
   independent API retries, bounded 5xx backoff and CPU/memory caching
   are preserved as applicable.
4. **Surface:** the six existing platforms listed in `PLATFORMS` in
   `const.py`, fork-specific network totals, connected-client and
   diagnostic entities, and the three existing per-entry services
   continue to behave as described. The separately registered manual
   log action (merged PR #44) must not alter those service contracts.
5. **Lifecycle:** awaited platform forwarding and failure-safe unload
   preserve live state until cleanup can complete.
6. **Firmware:** optional fields and legacy naming formats remain optional
   and backward-compatible.
7. **Scope:** an upstream addition is not presumed present solely because
   upstream merged it; compare the actual fork behavior. Update this
   guide when a behavior/invariant genuinely changes, with references
   to the affected implementation and dedicated skill.

For how to implement, test, review or approve those changes, use
`AGENTS.md`, `AI_POLICY.md`, the applicable repository skills and
`CLAUDE.md` **if/when that file is added**. This guide deliberately does
not duplicate their general standards.

## Optional read-only WiFi status (upstream #627)

The third, entry-owned coordinator reads the local `admin/wireless?form=wlan`
endpoint independently from the mandatory Deco and client coordinators.
The optional mobile coordinator merged in PR #43 is the **separate fourth**
coordinator on `main`; it does not replace or modify WLAN polling.
Its first refresh runs only after platform forwarding finishes and therefore
does not delay entity setup. Supported Main, Guest and IoT networks are
discovered only when valid firmware `enable` values are returned; the Main
sensor is disabled by default. Sensor unique IDs are
`<master_mac>_wifi_<network>`, tied to the existing master device without
changing any previously registered IDs. Sensors tied to a former master
remain registered but become unavailable immediately when the Deco
coordinator publishes a different master. A listener on the Deco
coordinator refreshes availability even between wireless API polls.

An unsupported network is absent rather than incorrectly reported as OFF.
Existing wireless entities become unavailable if their network disappears
from a valid later response. Optional wireless failures cannot block Deco
or client polling, and repeated failures defer wireless requests by five
minutes. Existing pause and config-entry shutdown semantics apply. On unload,
the wireless coordinator receives Home Assistant's `async_shutdown()`;
only the existing fork-specific Deco/client coordinators receive their
custom `async_close()` calls.

The coordinator's `data` stores only boolean states. With the new, explicit
`expose_wifi_ssids` opt-in option (default `false`), it also stores a
**separate**, per-entry `ssids` map containing only recognized network and
band names. A snapshot is valid only for the owner master MAC **and**
observed master generation, captured before awaiting the WLAN request
and verified again before committing names after a successful parse.
The optional coordinator listens for Deco master transitions, invalidates
names immediately and rejects stale SSID snapshots returned by an
in-flight request, including A -> B -> A transitions before a successful
new poll. Boolean WiFi states retain their
original behavior; a master switch cannot reattribute previously stored
SSID names. The optional endpoint's consecutive-failure counter and
five-minute cooldown are scoped to the current master generation: changing
masters resets the old retry budget, while a failure from an in-flight
request started under the former master still yields a sanitized
`UpdateFailed`, but is not counted against the new master. Repeated
notifications for an unchanged master do not bypass backoff. Successful
polls reset the current retry budget; a failure preserves previously
published coordinator status and valid same-master SSID data.
Without consent, names are neither parsed into nor retained in
coordinator state. The existing Main, Guest and IoT WiFi binary sensors expose
a common `ssid` attribute for matching bands or individual `ssid_<band>`
attributes for differing names; missing or invalid names are omitted. The
attribute is also hidden if its previous master is no longer current.

SSID values are potentially sensitive Home Assistant state attributes, and
may be captured by Recorder/history, user dashboards, automations and
backups; disabling exposure does not erase previously stored history.
Never log or export SSIDs, passwords, PSKs, router tokens, or raw WLAN
responses through diagnostics. SSID exposure does not enable changing WiFi
configuration. Only bounded numeric firmware band keys may become SSID
attribute suffixes; malformed or excessively long keys are ignored.
Status and optional SSID names must parse successfully together **before**
cached SSID names are replaced or wireless retry counters are reset.
Unexpected SSID decoder failures follow the same sanitized, bounded
optional-wireless failure/backoff path while preserving the last known
states and names. The sanitized `UpdateFailed` is raised outside the
handler so private parser exceptions are not retained as `__context__`;
they cannot break the mandatory coordinators.
Real hardware compatibility remains unverified until independently tested.

The wireless API validates the outer encrypted-response envelope and inner
`result` mapping before reading network status. An authenticated `-5002`
response retains the existing single reauthentication retry; firmware
`timeout` is classified without additional timeout retries. HTTP errors,
malformed response data and decode failures are exposed to the optional
coordinator as sanitized failures. Raw error objects and payloads are never
included in wireless logs; configured session tokens, cookies and request
crypto material are not logged during transport/login. Unexpected wireless
API exceptions are contained as optional update failures, while Home
Assistant authentication errors and task cancellation remain distinct.

## Optional mobile WAN usage and error contract (merged PR #43)

The optional, per-entry mobile coordinator polls the encrypted, read-only
`admin/network?form=internet` endpoint every five minutes, only while
polling is active and a current master is recognized as a 4G/5G model.
Its first refresh is scheduled as an entry-owned background task **after**
platform forwarding. The result is an optional, translated per-master
KiB sensor with stable `<master_mac>_mobile_data_usage` unique ID;
a genuine zero is valid, while an absent or unsupported counter is not
published as zero. Master MAC/generation ownership rejects stale values
returned after master switches, including A -> B -> A transitions.
Mandatory Deco/client and optional WLAN polling are not blocked.

For mobile requests, HTTP 401/403 invalidates the stale session and
permits the existing **single** authenticated retry; other HTTP failures,
transport errors, malformed JSON and timeouts are sanitized at the API
boundary to avoid exposing LuCI token URLs or raw router responses.
At that API boundary, `raise ... from None` suppresses display of an
original exception context in the standard traceback but does **not**
remove the underlying `__context__` object. Ordinary mobile refresh
errors produce a fixed `UpdateFailed`. Login failures remain
`ConfigEntryAuthFailed` but are re-raised **outside** the exception
handler with a fixed message and neither `__cause__` nor `__context__`.
Cancellation propagates normally. Failed optional polling retains the
previous cached same-master reading, which remains unavailable to the
Home Assistant sensor while the coordinator reports a failed update.
The actual counter and raw payload must not appear in diagnostics.
Physical firmware and Recorder/history behavior remain unverified.
PR #43 is merged; this behavior is present on `main` but physical
firmware behavior remains unverified.

## Manual system-log export (upstream #650; merged PR #44)

The merged `tplink_deco.download_system_log` action is registered
once and chooses a currently loaded config entry at invocation.
When multiple Deco entries are loaded, a valid `config_entry_id` is
mandatory; unknown or unloaded entries fail before router access.
The three existing entry services and their lifecycle remain unchanged.

The action first builds a snapshot through authenticated encrypted
`admin/log_export?form=feedback_log`, then retrieves it through the
unencrypted `form=save_log` request. On merged `main` (PRs
#44/#45), plain text, gzip, tar and gzip-tar are supported;
network and expanded payloads are capped at 8 MiB. Unsupported,
invalid and oversized responses create no file. Session expiry
permits one shared re-login. The Home Assistant action converts
router authentication failures, timeouts, interrupted connections and
other API failures into fixed user-facing service errors without retaining
the original exception context; unexpected non-text results are rejected
before writing. File-system and encoding failures receive another fixed
error. The writer attempts to remove newly created partial files after
write/close failures, but cleanup is not guaranteed if unlinking fails
or a concurrent actor changes the path. Cancellation propagates.
Raw token URLs, cookies and log contents must never reach integration
logs or formatted exceptions.

The result is stored in a newly created file under
`<config>/tplink_deco_logs/` via the executor. The file name is an
ASCII `.log` basename, cannot overwrite an existing file and
receives private permissions where the platform supports them.
An existing symlinked export directory is rejected before writing.
This point-in-time check, final-file `O_NOFOLLOW` and path-based
cleanup have **not** been verified against concurrent parent-directory
replacement, Windows reparse points or Windows ACLs. These measures
must not be described as race-proof storage or guaranteed cleanup.
Only the explicit service response contains its path and line count.
Router logs may contain sensitive network data and must be stored,
shared and removed with care. The action does not populate any
diagnostic or Recorder entity, forward logs or add polling.

### Compressed snapshot decoding (upstream #673; merged PR #45)

PR #45 extends the manual action to accept gzip, tar and gzip-wrapped
tar snapshots, including compressed data mislabeled as `text/plain`.
Both compressed HTTP bytes and inflated data are capped at 8 MiB.
Tar decoding selects the exact `syslog.log` basename among regular
members or falls back to the first regular member; links, directories
and device entries are ignored and no paths are extracted to disk.
All parsing is performed off the event loop. Corrupted/oversized
archives, unexpected binary data and malformed UTF-8 fail with fixed,
privacy-safe errors. JSON error bodies retain the existing bounded
re-login/error contract. The file output remains plain UTF-8 text;
there are no new entities, polling or network-forwarding operations.

The compressed decoder is present on `main` after merge commit
`a1208e7a0258271df50f69b4b6a51cf39e6a9b1c`.
**Merged fork PR #46 (2026-11-17; merge commit `477dd11`)**
adds privacy-safe manual-export error handling: standalone firmware
`errorcode`/`error_code` JSON mislabeled as `text/plain` or
`application/octet-stream` is rejected before saving, while ordinary
JSON-formatted log lines are preserved. A complete first JSON record
with trailing log records is not a standalone firmware error, but
truncated standalone error envelopes are rejected. The manual download
uses zero additional timeout/transient retries, while retaining one
bounded authentication re-login; normal Deco API retry defaults remain
unchanged. Raw socket resets, interrupted reads and exceptional JSON
parser recursion yield fixed privacy-safe API errors without replaying
the manual export. These changes and their regressions are on `main`.
Physical firmware, concurrent filesystem races and Windows ACL
behavior remain unverified.
Legacy S7 sessions and syslog forwarding
(#666) remain unimplemented. Physical firmware/Windows ACL tests,
the parent-symlink race and best-effort cleanup remain unverified.
