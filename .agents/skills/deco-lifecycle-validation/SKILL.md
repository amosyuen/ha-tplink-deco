---
name: deco-lifecycle-validation
description: "Use when changing Home Assistant entry setup/unload, coordinator shutdown, dispatcher listeners, or Deco API logout in HiDiHo01/ha-tplink-deco. Validate safe teardown and session ownership without altering entity IDs or unrelated upstream components."
---

# Validate TP-Link Deco setup, unload and session lifecycle

## Inspect before changes

1. Read repository `AI_POLICY.md` and `AGENTS.md`, then inspect the
   current `custom_components/tplink_deco/__init__.py`, `coordinator.py`,
   `api.py`, existing lifecycle tests, and any relevant upstream PR.
2. Identify the coordinators **actually created by this fork** and the
   ownership of their resources. With PR #41, the fork has required Deco
   and client coordinators plus a separate **optional WLAN**
   `DataUpdateCoordinator`; the aiohttp `ClientSession` is owned by
   Home Assistant. Do not assume upstream mobile coordinators or legacy
   outer-session protocols exist. Verify each coordinator's supported
   cleanup methods independently; do not infer them from a shared base
   class.
3. Review `async_setup_entry` as well as `async_unload_entry`. Await
   `async_forward_entry_setups` before completing setup, and do not
   register services/listeners after a failed platform setup.

## Safe unload contract

4. Attempt to unload every forwarded Home Assistant platform **before**
   stopping any coordinator or releasing custom callbacks. If a platform
   unload fails or raises, preserve the stored entry data, polling
   coordinators, dispatcher listeners and existing router authentication.
5. After every platform unload succeeds, await
   `DataUpdateCoordinator.async_shutdown()` for each existing coordinator
   to cancel scheduled refreshes. Then await its fork-specific
   `async_close()` **only for coordinator classes that implement the
   fork-specific hook** (currently Deco/client coordinators). A plain
   Home Assistant `DataUpdateCoordinator`, including the optional WLAN
   coordinator introduced in PR #41, provides `async_shutdown()` but not
   that custom `async_close()` method. Calling it prevents logout and
   removal of entry data. These are different cleanup steps; do not
   substitute one for the other. Include a test fixture with a wireless
   coordinator that deliberately has no `async_close` attribute.
   Also verify that an optional WLAN failure cannot prevent required
   coordinators from refreshing or a successfully unloaded entry from
   logging out, removing services and releasing its stored runtime.
6. Only after coordinator cleanup, attempt the router's best-effort logout.
   Skip the request if there is no complete session, and always clear
   local token/cookie/sequence data on completion or failure.
7. Log only safe exception **types** during logout failure; never log raw
   router exceptions, tokens, cookies, credentials, or request URLs
   containing a LuCI session token. Propagate `asyncio.CancelledError`
   while still clearing the local session. Do not close the shared
   Home Assistant HTTP session.
8. Remove the entry's runtime state only after a successful teardown.
   Do not modify service schemas, MAC-based entity IDs, device registry
   relationships or other configuration entries as a cleanup side effect.

## Deterministic regression checks

9. Test real entry setup/unload functions with mocked Home Assistant
   platform calls and coordinators: success ordering, false/raising
   platform unload, repeated/absent-entry unload, missing coordinators,
   and preservation of another config entry.
10. Verify the API logout path with synthetic credentials: posted
    endpoint/payload, missing or partial auth, rejected/failed logout,
    local state cleared, cancellation propagated, and no sensitive text
    in captured logs. Do not use real Deco devices or credentials.
11. Validate on the repository's supported test matrix:
    Python 3.13 / Home Assistant 2025.12 and Python 3.14 /
    Home Assistant 2026.11, plus pre-commit, HACS and Hassfest.
    Apply formatter corrections on the branch and re-check the new
    commit rather than relying on CI from a superseded head.

## Related optional feature validation

The WLAN-specific HTTP boundary, authentication, timeout, cache,
redaction and master-availability regression procedures live in
[Deco wireless-status validation](../deco-wireless-status-validation/SKILL.md).
This lifecycle skill owns the cross-platform unload order and shared
session contract; do not duplicate the full WLAN test matrix here.

## Handoff

12. For upstream ports, link the PR as `Part of #2` and leave issue #2
    open. Confirm mergeability and review threads, record actual CI
    results and hardware limitations, and update the tracking checklist
    **only after merge**. Refer to
    [Deco upstream synchronization](../deco-upstream-sync/SKILL.md)
    for the broader comparison and issue-tracking workflow.

The repository's `AGENTS.md` defines general standards; this skill
describes the lifecycle-specific validation procedure.
