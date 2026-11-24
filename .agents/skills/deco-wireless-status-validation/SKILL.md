---
name: deco-wireless-status-validation
description: "Validate Deco WLAN status and explicitly requested firmware-supported WiFi writes, including authentication, privacy, entity state, concurrency and lifecycle."
---

# Validate Deco wireless reads and controlled writes without leaking credentials

## When to use and source of authority

Use this procedure for existing read-only Main, Guest and IoT WiFi
status (upstream #627, merged fork PR #41), the separately scoped,
**default-disabled** SSID exposure option, and future explicitly
requested WiFi-setting writes. This skill **permits** narrowly scoped
writes after all safeguards below are implemented and verified; it
does not claim that write support is already present on `main`.
Start with `AI_POLICY.md`, `AGENTS.md` and `home-assistant.md`.
Inspect the current branch's `api.py`, `wireless.py`,
`binary_sensor.py`, `config_flow.py`, `__init__.py` and tests.
Do not adopt upstream code or review suggestions blindly. A feature
present on an open PR is not yet present on deployed `main`.

## API boundary and privacy

1. Preserve the existing **read** contract: use the fixed
   `admin/wireless?form=wlan` endpoint with `{"operation": "read"}`.
   **Write** operations on that same authenticated, encrypted endpoint
   are allowed only through an explicit Home Assistant user/service
   action, with `{"operation": "write", "params": ...}`, and only after
   validating the selected firmware capabilities and target fields.
   Never send a write during setup, background polling, discovery,
   diagnostics or failure recovery. Do not change unrelated WiFi
   configuration, or publish PSKs, passwords or raw WLAN payloads.
   SSID names may be published **only** as explicitly consented existing
   sensor attributes; keep that option disabled by default.
2. Validate the outer HTTP JSON mapping, its encrypted `data` string, the
   decrypted mapping and the `result` mapping **before** indexing or
   interpreting fields. Missing, malformed or unsupported fields are not
   evidence that WiFi is disabled. Only accepted `enable` flags on
   `band*/host`, `band*/guest` and `iot/host` can produce booleans.
   Multiple enabled bands combine to an enabled network.
3. Preserve the established **read** error contract: an expired session
   (`-5002`, including legacy `errorcode`) permits at most one
   re-login; an explicit firmware `timeout` is a timeout, without
   extra optional WLAN timeout retries. For **writes**, only retry
   if the router explicitly rejects authentication **before** applying
   a command and the API can prove that no write occurred. Never replay
   a write after timeout, disconnect, malformed acknowledgement or any
   other outcome that might already have changed the router. Propagate
   Home Assistant authentication failures and `asyncio.CancelledError`
   without treating them as ordinary optional-read backoff.
4. Sanitize **at the originating HTTP/decoder boundary**, not only in
   a coordinator catch block. Aiohttp errors may embed the LuCI token
   in `request_info.real_url`; error codes or firmware messages may
   contain attacker-controlled text. Do not log raw responses, private
   fields, cookie values, encryption keys/IVs, URLs or upstream exception
   strings; also inspect exception causes in surfaced tracebacks. Use
   fixed errors and safe exception class names where needed. Keep
   WLAN write changes isolated from other API forms and request paths.
5. Unexpected exceptions from the **optional read** must not break
   mandatory Deco or client coordinators. Surface a sanitized
   `UpdateFailed`, preserve their data, and defer optional read polls
   for five minutes after two consecutive failures. Do not bypass
   that bound with an additional retry loop. A successful read clears
   the cooldown; a pause retains cache. An invalid response is not
   successful empty data. For explicit writes, return a separate,
   sanitized action failure; never silently report success or weaken
   the read coordinator's retry policy.

## Coordinator and entity lifecycle

6. Create the wireless coordinator per config entry and begin its first
   update after awaited platform forwarding. It is independently
   scheduled and shut down with `async_shutdown()`. Only the existing
   Deco/client coordinators provide the fork-specific `async_close()`
   hook; calling it on the plain wireless `DataUpdateCoordinator`
   raises `AttributeError` and blocks logout and entry cleanup.
   Do not close Home Assistant's shared `aiohttp.ClientSession`.
7. Discover only supported network keys; do not create duplicate entities
   on refresh or dispatcher signals. Preserve MAC-based entity and device
   registry identifiers. A previously registered former-master wireless
   sensor remains in the registry but becomes **unavailable** when the
   current master MAC differs. Subscribe to Deco coordinator updates
   for immediate availability changes; unsubscribe via
   `async_on_remove` during entity removal. When the original master
   returns, its original entity identity may become available again.

## Controlled WiFi-setting writes (opt-in user actions)

- **Explicit scope and entity semantics:** Add Home Assistant controls only
  for a capability verified against the current API and target firmware.
  Use a stateful `switch` for enabling/disabling a network, not a
  stateless reboot-style `button`. Preserve the existing read-only
  WiFi `binary_sensor` and its unique ID as an independent status
  source; do not silently convert its entity domain or delete the
  registry entry. Register controls only for supported networks and
  keep each control scoped to its owning config entry/master device.
  Creation or setup must never enable or disable a network.
- **Firmware and target validation:** Before any write, require a
  successful, current WLAN read and an unambiguous, online, currently
  owned master. Check its MAC **and** generation before and after each
  await; reject A -> B -> A master handovers and stale data. Select only
  recognized firmware band keys actually returned by that router,
  validate supported write fields and booleans strictly, and reject
  missing, malformed or unsupported band/network data. Do not infer
  that a network is disabled from an absent or invalid flag.
- **Guest-network payload:** For a guest enable/disable action, use the
  authenticated encrypted `admin/wireless?form=wlan` **write**
  operation with the narrowest firmware-confirmed per-band
  `{"guest": {"enable": true|false}}` mapping for the selected
  bands. Only change requested `enable` flags. Never supply or
  overwrite existing SSIDs, passwords, encryption, schedules, VLANs,
  band settings or other options as a side effect. Do not send raw,
  user-supplied dictionaries or unconstrained firmware keys as write
  parameters. If the firmware requires additional settings or does
  not confirm that partial updates are safe, reject the action rather
  than guessing its required payload.
- **IoT-network payload (IoT switch branch):** For a verified
  `iot.host.enable` field, the narrowly scoped candidate for
  `admin/wireless?form=wlan` is
  `{"operation":"write","params":{"iot":{"host":{"enable":true|false}}}}`.
  This request shape is described by independent reverse-engineered
  wireless API documentation, not verified physical router tests. Check
  `iot.host` is a mapping and its existing enable flag is accepted by the
  parser before allowing a control. Never send `enable_2g`, `enable_5g`,
  SSIDs, passwords, security or other radio options. The IoT switch must
  have a distinct unique ID from `binary_sensor.*_wifi_iot`, and needs a
  successful fresh IoT status snapshot tied to its master generation.
  Guard ownership after asynchronous login and before issuing the POST.
  A mocked encrypted ACK is **not** firmware proof; keep the PR draft until
  real write/readback behavior is confirmed on supported models. Do not
  retry uncertain writes or report success without readback.
- **Preflight and concurrency:** Re-read supported network/band
  settings before writing; require the control's entry, selected
  master and capability to remain current. Serialize writes per
  config entry to prevent conflicting actions. Prevalidate all
  affected bands before the first command. Do not imply that a
  multi-band update is atomic; if the firmware cannot guarantee
  all-or-nothing behavior, surface partial/uncertain outcomes and
  reconcile by a fresh read instead of issuing blind rollback writes.
- **Acknowledgement and state:** Validate outer HTTP JSON, encrypted
  data, decrypted result and fixed numeric firmware status before
  reporting acceptance. Refresh WLAN state after a confirmed write,
  and report the observed router state; never optimistically set
  `switch.is_on` from the submitted command. If acknowledgement or
  readback is missing, report a controlled unknown/failure state
  rather than asserting success. Preserve unavailable states when
  WLAN data is invalid, stale or temporarily inaccessible.
- **Authorization, transport and privacy:** Reuse the entry-owned
  authenticated client, HTTPS/redirect protections and safe error
  handling. Only the explicitly requested action may issue the
  write; no background automation should run without the user's
  Home Assistant control/service invocation. Never expose SSIDs,
  passwords, keys, cookies, tokens, router URLs or raw responses in
  logs, exceptions, traces, diagnostics or newly created entities.
  Sanitize error text **and** `__cause__`/`__context__` at the API
  boundary, including failures on incomplete HTTP replies.
- **Write-specific regressions:** Test the exact operation, URL,
  form, encrypted payload, per-band `enable` flags, cookies and
  session/HTTPS context using **synthetic** data. Assert absence
  of unrelated wireless fields and of **any** write for unsupported
  bands, invalid types, missing master, cross-entry ownership,
  stale generations, disabled/unavailable controls, failed preflight
  or cancelled tasks. Test concurrent commands, multi-band partial
  failures, accepted writes followed by stale/failed readback,
  router rejections, token expiry and uncertainty after timeout;
  never allow automatic replay after an ambiguous write. Verify
  unchanged WiFi sensors, stable device/entity IDs and opt-in
  SSID privacy across all regression scenarios. Mocked tests are
  not proof of device/firmware write compatibility.

## Explicit SSID opt-in (upstream #637)

- The per-entry `expose_wifi_ssids` option defaults to `False`, including
  migrated/legacy entries. Accept only actual booleans; reject strings,
  numeric values and missing/invalid consent coercions before credential
  checking or persistence in setup/options flows.
- Parse only `ssid` fields in the already known `band*/host`,
  `band*/guest` and `iot/host` sections. Decode Base64 names with the
  existing firmware compatibility helper; ignore absent, empty or non-string
  values and all password, PSK and unknown-section fields. Support one
  `ssid` attribute for common names, otherwise deterministic per-band keys.
- Do not store parsed names in `coordinator.data`. Maintain a separate
  `coordinator.ssids` map **only** when consent is exactly `True`;
  keep it empty otherwise. On successful polls, replace it rather than
  merging stale names; omit unsupported networks and avoid exposing names
  on unavailable former-master entities. Never include names in diagnostics,
  DEBUG logs or raw responses.
- **P1: associate SSID snapshots with a master and generation (PR #42).**
  Capture the current master MAC and monotonically increasing **per-entry**
  generation immediately **before** awaiting the WLAN API, not after a
  successful read. Register a Deco coordinator listener before adding
  wireless sensors; increment the generation and clear SSIDs/ownership
  whenever the master changes. A -> B -> A is **not** equivalent to no
  change: an older A snapshot remains hidden until a new A request
  succeeds. After the awaited request and successful parsing, compare
  both identities before **committing** SSIDs; a stale success may retain
  the existing boolean WiFi-status return contract, but must not publish
  SSID attributes. Recheck ownership in the sensor attribute getter.
  Preserve stable MAC-based entity IDs, listener cleanup through entry
  unload, and shared-session ownership. Test A -> B, A -> B -> A,
  in-flight switches, opt-out, immediate callback publication and
  per-entry isolation.
- **Retry ownership during master changes:** a genuine master transition
  resets the optional WLAN failure counter and five-minute cooldown; a
  same-master notification leaves them untouched. When an in-flight request
  fails, observe the current master again. Count the failure only if its
  starting **MAC and generation** still match. A stale failure still
  returns a fixed, sanitized `UpdateFailed`, but cannot consume the new
  master's retry budget. This includes A -> B -> A while the original
  request awaits. Do not retry synchronously to defeat the cooldown;
  preserve Home Assistant authentication and task-cancellation handling.
  A paused coordinator returns cached boolean status without issuing a
  router request or resetting backoff.
- **Validate before committing coordinator data:** parse boolean states
  and optional names inside the **same** guarded update. A decoder error
  becomes sanitized `UpdateFailed`, counts toward the two-failure/
  five-minute limit **only for the unchanged starting generation**, and
  must not reset retry state as though the update succeeded. Preserve
  previously cached states and valid same-owner names without partially
  committing a failed result. A real master change clears old names
  regardless of the failed request. Raise fixed `UpdateFailed` **after**
  leaving `except`: `raise ... from None` _inside_ an exception handler
  still retains the private original error in `__context__`. Check
  `__cause__ is None`, `__context__ is None`, fixed message text and
  the absence of synthetic secrets from DEBUG logs. Authentication and
  cancellation must still propagate.
- **Constrain firmware-derived attribute keys:** allow only the explicit
  `iot` key or numeric band identifiers matching
  `band[0-9]+(?:_[0-9]+)*` (for example `band2_4`, `band5_1`,
  `band6`) with a 32-character maximum. Reject malformed or oversized
  keys before creating `ssid_<band>` attributes; never let arbitrary
  firmware paths become Home Assistant attribute names. Empty mappings
  produce no attributes.
- Test default-off and explicit-on for both flows, form JSON serialization,
  rejected non-boolean submissions, setup/option persistence, multi-entry
  isolation, decoding, per-band grouping, missing/invalid names and
  coordinator refresh clearing. Document that entity history and exports
  created while enabled can survive disabling the option. Recheck all
  language translations and both supported HA CI matrices.

## Required failure-outcome checks

For existing read-only behavior, use `tests/test_wireless.py` and
`tests/test_wifi_ssid_opt_in.py`. For a new write action, add focused
API/control regressions and include them in the full matrix. For each
read check, verify the API-call count, returned status or exception,
cached names, owner/generation, failure counter and cooldown—not
merely that an exception was raised. For write checks, additionally
verify the exact authorized payload, target/owner at dispatch and
the **absence of duplicate or unexpected writes**.

- **Successful current-master read:** parse booleans and opt-in names
  together, publish only matching-owner names, and clear the active
  retry budget. A subsequent valid response with no SSIDs removes old names.
- **Malformed payload or private decoder failure, unchanged master:**
  surface only fixed `UpdateFailed` text, preserve cached results,
  increment the failure counter exactly once, and defer calls for five
  minutes after the second failure.
- **Repeated same-master notification during cooldown:** retain the
  existing failure count and deadline; do not issue a new WLAN request.
- **Real master switch during cooldown:** clear old names, owner and
  retry budget; allow the new master's next request without inheriting
  the previous owner's deadline.
- **In-flight success after A -> B or A -> B -> A:** never publish names
  from the old request; require a fresh owner-matching poll before names
  become visible. Preserve the established boolean-status semantics.
- **In-flight failure after either switch:** return sanitized
  `UpdateFailed` without charging the current owner's retry counter.
  Verify a subsequent failure of the current master counts as attempt one.
- **Authentication or task cancellation:** propagate the original
  control-flow outcome; do not misclassify it as routine WLAN backoff.
- **Pause and independent config entries:** avoid optional status polls
  during pause, retain appropriate cached status, and do not modify another
  entry's SSID ownership or retry state.
- **Write preflight and post-write verification:** a write must fail closed
  if the current master, eligible bands or capability cannot be verified.
  Check exact targets, encrypted request, session and sanitized errors.
  Do not replay uncertain outcomes or claim success without confirmed
  acknowledgement and a fresh corresponding status read.

For deterministic asynchronous races, coordinate mocked router calls
with `asyncio.Event` rather than sleeps; patch `monotonic()` to test
cooldown boundaries. Use clearly synthetic secret-bearing exceptions and
assert they are absent from logs, messages and exception context. Do
not infer physical mesh compatibility from mocked tests.

## Tests and failure investigation

8. For read-only WLAN paths, in `tests/test_wireless.py`, cover
   recognized/unknown flags,
   malformed and missing outer/inner payloads, corrupted ciphertext,
   `-5002`, firmware timeout, HTTP 403/5xx, unexpected upstream errors,
   two-failure cooldown/recovery, paused polling and cancellation.
   Use synthetic secret-bearing data and assert absence from DEBUG
   logs **and** exposed exception text/causes as applicable.
9. **Mock at the correct boundary.** A test of
   `TplinkDecoApi._async_post` must execute that real method with a
   mocked aiohttp response; if a helper fixture replaces
   `api._async_post` with `AsyncMock`, restore the real bound method
   before testing HTTP status/JSON handling. Otherwise `pytest.raises`
   can fail because the tested path was never executed. Use a realistic
   response with `raise_for_status()`, `json()`, `headers` and a
   secret-bearing `request_info` as relevant.
   **Constructor-bypassing fixtures:** after adding coordinator state,
   inspect both `tests/test_wireless.py` and
   `tests/test_wifi_ssid_opt_in.py`. Their `object.__new__` helpers
   must initialize `expose_ssids`, `data`, `ssids`,
   `_observed_master_mac`, `_master_generation`,
   `_ssid_master_mac`, `_ssid_master_generation`,
   `_next_retry` and `_consecutive_failures` consistently with
   the mocked Deco master. A bare `MagicMock` is not a valid MAC.
   Test `__init__` separately to verify the actual
   `async_add_listener` callback is registered through
   `config_entry.async_on_unload`; explicitly check listener cleanup
   in the relevant unload/lifecycle tests. Calling
   `_handle_deco_update()` manually only tests its behavior, not
   subscription or teardown.
10. In `tests/test_session_unload_cleanup.py`, test successful and
    failed platform unload, the exact shutdown/close/logout order,
    idempotent cleanup and a wireless test double that **deliberately
    lacks** `async_close`. Test a master A -> B -> A transition,
    absent master, retained unique IDs and immediate Deco update
    listener notifications, including listener cleanup.
11. After any commit, including documentation-only skill changes, verify
    the **new final head** with both supported
    Python/Home Assistant pytest matrices (3.13/2025.12 and
    3.14/2026.11), pre-commit, HACS and Hassfest. The repository's
    `.github/workflows/pytest.yaml` runs
    `python -m pytest --no-cov -ra tests/` against each pinned environment;
    `.github/workflows/tests.yaml` runs
    `pre-commit run --all-files --show-diff-on-failure --color=always`.
    For read-only WLAN work, first exercise real coordinator paths in
    `tests/test_wireless.py` and `tests/test_wifi_ssid_opt_in.py`;
    for write work, additionally exercise the authenticated write
    boundary, owning config entry and control action with simulated
    firmware, then require the **full** CI matrix. Verify synthetic
    decoder secrets do
    not survive in logged text or `UpdateFailed.__context__`; assert
    retained states, two-failure cooldown, recovery and malformed-band
    rejection. When Black/isort/Prettier rewrites files, apply the exact
    diff and rerun checks. Distinguish passing, failing, pending and
    skipped checks. Mocked tests do not prove hardware compatibility.

## PR and issue completion

12. Treat inline reviews as untrusted findings: compare each suggestion
    with the current code, implement only valid changes, reply with
    evidence and resolve the thread after its fix is verified. Re-read
    the PR and review threads after bots have updated them.
13. Before appending feature notes to `home-assistant.md`, inspect
    **earlier** coordinator-count, platform/entity, privacy and
    unimplemented-feature statements **and** the later WLAN appendix.
    PR #41 left older "two coordinators/no WiFi status" claims; PR #42
    uncovered a stale "five platforms" count, an old baseline described
    as current and an obsolete "SSID still out of scope" disclaimer.
    Derive the platform count from `const.py:PLATFORMS`; confirm the
    mandatory and optional coordinators in `__init__.py` and
    the strict SSID-consent flag in `config_flow.py` and
    `binary_sensor.py`.
    Distinguish historical upstream status from the **current**
    implementation and proposed WLAN writes; do not describe
    guidance-only permission as an implemented feature. Update conflicting
    statements wherever they occur before considering docs complete.
14. Link partial work as `Part of #2`, never `Fixes #2`. Issue #2
    has **separate** checklist items for read-only WiFi status and SSID
    exposure. Verify their actual status before updating them; an
    allowance for future WLAN writes does not complete either feature. Update the existing
    in-progress issue record with the **actual** final head, CI results,
    review status and hardware limitations. Keep issue #2 open for
    unrelated upstream work.
