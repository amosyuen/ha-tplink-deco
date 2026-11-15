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

**Baseline:** verified against fork `main` at
`d4c39b91558d1396b0a2d1f2d227fd82cf2955b3` (15 November 2026).
This describes the fork, **not** the current upstream architecture.
Deco discovery (PR #25), client restoration (PR #26), tracker discovery
(PR #27), per-node client counts (PR #28), non-blocking initial client
refresh (PR #29), coordinator health sensors (PR #30) and the
privacy-safe diagnostics download (PR #31) are merged.

## 1. Integration boundary and data ownership

- Home Assistant integration domain: `tplink_deco`. The manifest declares
  `integration_type: hub` and `iot_class: local_polling`, with configuration
  through a config flow.
- The integration exposes exactly these platforms at this baseline:
  `device_tracker`, `sensor`, `binary_sensor`, `switch` and `select`.
  Relevant sources: `const.py` and `manifest.json`.
- Each configuration entry stores its own pair of coordinators under
  `hass.data[DOMAIN][entry_id]`:
  - `COORDINATOR_DECOS_KEY` / `TplinkDecoUpdateCoordinator` discovers mesh
    nodes, identifies the master and obtains optional performance readings.
  - `COORDINATOR_CLIENTS_KEY` / `TplinkDecoClientUpdateCoordinator` polls
    client lists **per known Deco node**, retains known clients and determines
    connection state.
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
  and all registry entity IDs.
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
  without requiring a specific firmware variant. **Current limitation:**
  `TpLinkDeco.update` accepts an absent `signal_level` field but calls
  `.get` on an explicitly `null` value; such a response raises
  `AttributeError` and interrupts discovery. Handling this case
  requires a separate runtime fix and regression test.
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

- The current **main scan interval** has choices 10, 30, 60 and 120
  seconds (default 30). It drives the existing coordinators; the
  polling-interval select uses the same config-entry setting. Do not imply
  that the separate upstream `device_list` interval/startup-only mode has
  already been implemented.
- The Deco coordinator's `paused` state gates its own refresh, and the
  client coordinator honors the same pause flag. The switch controls this
  flag; turning polling back on requests a refresh.
- The Deco coordinator requests the device list and optional master
  performance. Master CPU/memory values have raw readings and smoothed
  readings (currently 70% previous/30% new); missing measurement fields
  preserve the last known values. **Proposed in [PR #33](https://github.com/HiDiHo01/ha-tplink-deco/pull/33):**
  normalize finite numeric firmware strings for client down/up rates
  and CPU/memory before arithmetic. Malformed/missing client rates
  become numeric zero so existing per-Deco and network throughput
  aggregation remains safe for online clients. Invalid optional
  CPU/memory fields preserve the previous raw and smoothed readings;
  valid zero is not treated as missing. Keep the existing units,
  identities and 70/30 smoothing. This does **not** add the separate
  encrypted outer session needed for some legacy S7 firmware. An optional performance request that
  exhausts **transient-response** retries raises
  `TransientConnectionException`, which the coordinator catches so
  the device-list update can proceed. **Current limitation:** an
  exhausted `TimeoutException` is not caught there and can fail the
  entire coordinator refresh; treating that timeout as optional would
  require a separate runtime change and regression test.
- Truncated payloads and server disconnects have bounded retries using
  the configured `timeout_error_retries` count, independently of timeout
  and one-time re-login retry budgets. A temporary transport failure does
  not itself invalidate a known authenticated session.
- HTTP **5xx** on per-node client polling uses a separate, per-entry,
  non-blocking exponential backoff of **30, 60, 120, 240 and at most 300
  seconds**. While active, skip client-list requests and keep the
  previous client state. Successful peer-node results from the failing
  cycle are still applied. Reset backoff only after all polled nodes
  respond successfully; a valid empty list counts as a successful result.
  This backoff does not stop unrelated Deco/device polling.
- Non-5xx HTTP or explicit auth-expiry responses do not silently enter the
  5xx backoff path. Backoff does not replace API-level retry limits.

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
- `binary_sensor` currently exposes per-node `Internet online` and
  `Deco online` diagnostic states. It does **not** yet expose upstream
  Main/Guest/IoT Wi-Fi network status sensors.
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
  names, and the query mode is `per_node` until global fallback is
  separately implemented. Stable identities use `<master_mac>_<metric_key>`.
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
  diagnostics and system-log export remain unimplemented.
- `switch` controls polling. `select` chooses the main polling interval
  and persists the selected integer in the config entry before reload.
- Registered services are `tplink_deco.reboot_deco`,
  `tplink_deco.pause_polling` and `tplink_deco.resume_polling`. For
  `reboot_deco`, resolve each selected Home Assistant device registry
  entry to a nonempty `(DOMAIN, MAC)` identifier; reject an invalid
  selection **before** sending any reboot command. Device-registry
  records may carry additional unrelated identifiers.
- Do not silently add upstream syslog forwarding, log-download actions,
  mobile-usage sensors or new wireless coordinators as side effects of
  maintaining the current entities. These are separate features tracked
  in [issue #2](https://github.com/HiDiHo01/ha-tplink-deco/issues/2).

## 8. Config flow, setup, reload and unload

- Config-flow version **7** supports first setup, reauthentication and
  options. The main scan interval is displayed with string selector
  options but persisted as a supported **integer**. Invalid intervals
  must be rejected before testing router credentials or updating
  the config entry.
- Existing config-entry fields include host, username/password,
  connection timeout, bounded timeout retry count, TLS verification,
  `consider_home`, optional Deco/client name prefixes/postfixes and
  `link_client_devices` (defaults to `True`). Version 6 entries migrate
  to version 7 with this default through
  `hass.config_entries.async_update_entry`, without modifying the immutable
  `ConfigEntry.version` directly. The setting is independent per entry.
  Preserve existing field meanings and migration paths for older
  config-entry versions.
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
4. **Surface:** the five existing platforms, fork-specific network totals,
   connected-client and diagnostic entities, and three registered services
   continue to behave as described.
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
