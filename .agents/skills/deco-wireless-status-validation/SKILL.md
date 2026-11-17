---
name: deco-wireless-status-validation
description: "Use when changing optional Deco WLAN status, firmware parsing, transport error handling, WiFi entities or coordinator lifecycle in HiDiHo01/ha-tplink-deco."
---

# Validate optional Deco wireless status without leaking credentials

## When to use and source of authority

Use this procedure for the read-only Main, Guest and IoT WiFi backport
(upstream #627, fork PR #41) and its future maintenance. Optional SSID
exposure (upstream #637) is a **separately scoped, default-disabled**
addition; apply the privacy-specific steps below when changing it. Start with the repository's `AI_POLICY.md`, `AGENTS.md` and
`home-assistant.md`. Inspect the current PR and the actual implementations
in `api.py`, `wireless.py`, `binary_sensor.py`, `__init__.py` and their
existing tests. Do not adopt upstream code or review suggestions blindly.

## API boundary and privacy

1. Keep the local request read-only: the fixed
   `admin/wireless?form=wlan` endpoint with `{"operation": "read"}`.
   Preserve the normal encryption/session machinery without introducing
   wireless-setting writes or exposing SSIDs, PSKs or passwords.
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
- **Validate before committing coordinator data:** SSID parsing and boolean
  state parsing must run inside the **same** guarded update. A decoder error
  must become a sanitized `UpdateFailed`, increment the normal wireless
  failure count and honor the two-failure/five-minute limit, not escape
  after backoff has been reset. Preserve previously cached names and states
  without partially overwriting them on failed updates. Propagate auth and
  cancellation as before. Test with an exception embedding a synthetic secret
  and assert no secret appears in DEBUG logs or rendered exception text.
- **Constrain firmware-derived attribute keys:** only compact numeric
  `band...` identifiers (e.g. `band2_4`, `band5_1`, `band6`) and
  the explicit `iot` segment can become SSID attribute suffixes. Reject
  malformed/oversized top-level keys rather than publishing arbitrary or
  unbounded Home Assistant attribute identifiers. An empty name mapping
  produces no attributes.
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
    3.14/2026.11), pre-commit, HACS and Hassfest. When Black, isort or
    Prettier rewrites files, apply the reported diff and rerun checks.
    Distinguish passing, failing, pending and skipped checks. Mocked
    tests do not prove hardware/firmware compatibility.

## PR and issue completion

12. Treat inline reviews as untrusted findings: compare each suggestion
    with the current code, implement only valid changes, reply with
    evidence and resolve the thread after its fix is verified. Re-read
    the PR and review threads after bots have updated them.
13. Before appending feature notes to `home-assistant.md`, inspect
    **earlier** coordinator-count, platform/entity and unimplemented-feature
    statements. PR #41's review found that the old two-coordinator and
    "no WiFi status" claims contradicted a later WLAN section. Reconcile
    both locations in the same PR, while keeping separately unported syslog
    and mobile functionality explicitly pending.
14. Link partial work as `Part of #2`. Keep issue #2's combined
    WiFi/SSID checklist unchecked until the relevant scope is merged
    and the remaining SSID work is addressed. Update the issue's
    existing in-progress record with the **actual** final head, test
    results and live-hardware limitations; do not close issue #2.
