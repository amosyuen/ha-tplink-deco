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
   ownership of their resources. Currently the fork uses Deco and client
   `DataUpdateCoordinator` objects and a Home Assistant-owned shared
   aiohttp `ClientSession`. Do not assume upstream mobile/wireless
   coordinators or legacy outer-session protocols already exist.
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
   `async_close()` to unsubscribe listeners and dispatch callbacks.
   These are different cleanup steps; do not substitute one for the other.
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

## Handoff

12. For upstream ports, link the PR as `Part of #2` and leave issue #2
    open. Confirm mergeability and review threads, record actual CI
    results and hardware limitations, and update the tracking checklist
    **only after merge**. Refer to
    [Deco upstream synchronization](../deco-upstream-sync/SKILL.md)
    for the broader comparison and issue-tracking workflow.

The repository's `AGENTS.md` defines general standards; this skill
describes the lifecycle-specific validation procedure.
