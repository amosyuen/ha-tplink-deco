---
name: deco-wireless-status-validation
description: "Use when changing optional Deco WLAN status, firmware parsing, transport error handling, WiFi entities or coordinator lifecycle in HiDiHo01/ha-tplink-deco."
---

# Validate optional Deco wireless status without leaking credentials

## When to use and source of authority

Use this procedure for read-only Main, Guest and IoT WiFi status
(upstream #627, merged fork PR #41) and the separately scoped,
**default-disabled** SSID option (upstream #637, open fork PR #42).
Start with `AI_POLICY.md`, `AGENTS.md` and `home-assistant.md`.
Inspect the current branch's `api.py`, `wireless.py`,
`binary_sensor.py`, `config_flow.py`, `__init__.py` and tests.
Do not adopt upstream code or review suggestions blindly. A feature
present on an open PR is not yet present on deployed `main`.

## API boundary and privacy

1. Keep the local request read-only: the fixed
   `admin/wireless?form=wlan` endpoint with `{"operation": "read"}`.
   Preserve encryption/session handling without introducing WiFi-setting
   writes. Never expose PSKs, passwords or raw WLAN payloads. SSID names
   may be published **only** as explicitly consented existing sensor
   attributes; keep the option disabled by default.
2. Validate the outer HTTP JSON mapping, its encrypted `data` string, the
   decrypted mapping and the `result` mapping **before** indexing or
   interpreting fields. Missing, malformed or unsupported fields are not
   evidence that WiFi is disabled. Only accepted `enable` flags on
   `band*/host`, `band*/guest` and `iot/host` can produce booleans.
   Multiple enabled bands combine to an enabled network.
3. Preserve the established API error contract: an expired session
   (`-5002`, including the legacy `errorcode` form) permits at most
   one re-login; explicit firmware `timeout` is a timeout, without
   extra optional WLAN timeout retries. Propagate Home Assistant
   authentication failures and `asyncio.CancelledError` without
   recording them as routine optional-endpoint failures.
4. Sanitize **at the originating HTTP/decoder boundary**, not only in
   a coordinator catch block. Aiohttp errors may embed the LuCI token
   in `request_info.real_url`; error codes or firmware messages may
   contain attacker-controlled text. Do not log raw responses, private
   fields, cookie values, encryption keys/IVs, URLs or upstream exception
   strings; also inspect exception causes in surfaced tracebacks. Use
   fixed errors and safe exception class names where needed. Avoid
   changing other API forms while repairing the WLAN path.
5. Unexpected exceptions from this **optional** request must not break
   the mandatory Deco or client coordinators. Surface a sanitized
   `UpdateFailed`, preserve their data, and defer further optional
   requests for five minutes after two consecutive failed polls. Do not
   bypass this bound with an additional retry loop. A successful read
   clears the cooldown; a pause retains cache. An invalid response
   must not count as successful empty data.

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
  Record the owner MAC **and** a monotonic per-entry generation when a
  successful WLAN refresh begins. Register a Deco coordinator listener
  before adding wireless sensors; increment the generation and clear
  SSIDs/ownership whenever the master changes. A -> B -> A is **not**
  equivalent to no change: an older A snapshot must remain hidden until
  a fresh A request completes. Recheck the MAC and generation when the
  asynchronous request returns; do not publish SSIDs for a stale response.
  Before returning sensor attributes, revalidate ownership against the
  current master and generation. Keep boolean enabled-state behavior and
  stable MAC-based entity IDs unchanged. Register the coordinator listener
  for config-entry unload cleanup without closing shared sessions.
  Test A -> B, A -> B -> A (both with and without an intervening poll),
  an in-flight master switch, opt-out, callback publication, listener
  lifecycle and recovery on the new owner's successful poll.
- **Validate before committing coordinator data:** SSID parsing and boolean
  state parsing must run inside the **same** guarded update. A decoder error
  must become a sanitized `UpdateFailed`, increment the normal wireless
  failure count and honor the two-failure/five-minute limit, not escape
  after backoff has been reset. Preserve previously cached names and states
  without partially overwriting them on failed updates. Propagate auth and
  cancellation as before. Test with an exception embedding a synthetic secret
  and assert no secret appears in DEBUG logs or exception data. Raise the
  fixed `UpdateFailed` **after** leaving the `except` block: `from None`
  hides a traceback context but still retains the original private exception
  in `__context__`. Assert both `__cause__` and `__context__` are `None`.
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

## Tests and failure investigation

8. In `tests/test_wireless.py`, cover recognized/unknown flags,
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
10. In `tests/test_session_unload_cleanup.py`, test successful and
    failed platform unload, the exact shutdown/close/logout order,
    idempotent cleanup and a wireless test double that **deliberately
    lacks** `async_close`. Test a master A -> B -> A transition,
    absent master, retained unique IDs and immediate Deco update
    listener notifications, including listener cleanup.
11. After any commit, verify the **new final head** with both supported
    Python/Home Assistant pytest matrices (3.13/2025.12 and
    3.14/2026.11), pre-commit, HACS and Hassfest. The repository's
    `.github/workflows/pytest.yaml` runs
    `python -m pytest --no-cov -ra tests/` against each pinned environment;
    `.github/workflows/tests.yaml` runs
    `pre-commit run --all-files --show-diff-on-failure --color=always`.
    For focused WLAN work, first exercise the real coordinator paths in
    `tests/test_wireless.py` and `tests/test_wifi_ssid_opt_in.py`, then
    require the **full** CI matrix. Verify synthetic decoder secrets do
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
    Derive the six platforms from `const.py:PLATFORMS`; confirm the two
    mandatory plus optional WLAN coordinators in `__init__.py` and
    the strict consent flag in `config_flow.py` and `binary_sensor.py`.
    Distinguish merged #627 status from **unmerged** #637 SSID work and
    preserve separate syslog/mobile pending scope. Update conflicting
    statements wherever they occur before considering docs complete.
14. Link partial work as `Part of #2`, never `Fixes #2`. Issue #2
    has **separate** checklist items: read-only WiFi status (#627) was
    checked after PR #41 merged; SSID exposure (#637) stays unchecked
    until PR #42 is actually merged and verified. Update the existing
    in-progress issue record with the **actual** final head, CI results,
    review status and hardware limitations. Keep issue #2 open for
    unrelated upstream work.
