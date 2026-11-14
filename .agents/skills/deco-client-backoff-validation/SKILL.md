---
name: deco-client-backoff-validation
description: "Use when porting, reviewing, or debugging capped HTTP 5xx Deco client-list polling backoff (upstream #624) without changing authentication, client identity or unrelated polling."
---

# Validate HTTP 5xx client polling backoff

## Preconditions

1. Read `AI_POLICY.md`, `AGENTS.md` and
   [upstream synchronization](../deco-upstream-sync/SKILL.md).
   Inspect `custom_components/tplink_deco/api.py` and
   `coordinator.py`, existing transport and multi-node tests, plus
   [upstream PR #624](https://github.com/amosyuen/ha-tplink-deco/pull/624).
   Upstream has global-list fallback and health structures that are not
   yet present in this fork: port the _behavior_, not its architecture.
2. Preserve the fork's token/cookie and the existing separate
   reauthentication, timeout and truncated-response handling. An HTTP
   5xx client-list response is not proof that the session has expired;
   HTTP 401/403 and authenticated `-5002` retain their distinct handling.

## Safe implementation

3. Apply an independent per-config-entry capped delay: **30, 60, 120,
   240, 300, 300... seconds** after consecutive 5xx polling cycles.
   Use `time.monotonic()` for expiry; never block the Home Assistant
   event loop with `sleep()` or create an unbounded retry loop.
4. Skip all Deco client-list calls while the delay is active. Return
   the previous known clients unchanged, preserving online flags,
   `last_activity`, node associations and stable entity IDs. With a
   partial multi-node failure, keep results from successful nodes and
   previous clients assigned to failed nodes. If every node fails,
   return the whole previous inventory, including unassigned clients.
5. A _successful empty list_ is not a failed poll: retain the existing
   `consider_home` policy and reset the delay once **all** requested
   nodes return valid results. A transient or authentication failure
   must not count as a successful HTTP 5xx recovery.
6. Log only the numeric HTTP status and delay, never `ClientResponseError`
   text, `request_info`, URLs, cookies, client MACs or LuCI `stok`
   tokens. Do not alter user-configured scan intervals, sensors,
   config-entry data, unique IDs or other device classes. Expose the
   remaining delay through an internal coordinator property; adding
   separate health sensors remains outside the scope of upstream #624.

## Regression matrix

7. Test the actual API handler for HTTP 500 and auth retention with a
   secret-bearing error URL, and assert that raw secrets cannot appear
   in logs. Test HTTP 500/502/503, cap and expiry boundaries, skipped
   calls, recovery and restart at 30 seconds, successful empty lists,
   one failed node plus a healthy peer, all nodes failing, isolated
   config entries, non-5xx propagation and the separate truncated-body
   behavior. Mock the monotonic clock for deterministic tests.
8. Run both supported Home Assistant/Python matrix entries, pre-commit,
   HACS and Hassfest on the **final** PR head. If Black, isort or
   Prettier reformats files, commit its changes and verify again.
   No physical Deco router test is implied by mocked regressions.

## Tracking

9. Link the PR as `Part of #2` and update the in-progress status in
   issue #2 as soon as the PR is opened. Leave #624's tracking
   checklist item unchecked until a verified merge into `main`.
   Document remaining work (global client-list fallback, coordinator
   health sensors, real hardware validation). Save reusable new lessons
   here and repository-wide rules in `AGENTS.md`.
