---
name: deco-runtime-discovery-validation
description: "Validate TP-Link Deco runtime node discovery, synchronous dispatcher callbacks, data publication order and idempotent entity registration (upstream #643)."
---

# Validate runtime Deco discovery before notifying platforms

## Prerequisites

1. Read `AI_POLICY.md`, `AGENTS.md`, `home-assistant.md`, and the
   [upstream synchronization skill](../deco-upstream-sync/SKILL.md).
   Inspect `coordinator.py`, `device_tracker.py`, `binary_sensor.py`,
   `sensor.py`, `const.py`, and existing late-master regression tests.
2. Compare the fork's actual coordinator semantics with
   [upstream #643](https://github.com/amosyuen/ha-tplink-deco/pull/643);
   retain the fork's CPU/memory smoothing and network totals rather than
   replacing either coordinator or sensor platform wholesale.

## Behavior and code changes

3. A valid `device_list` response must first build a complete
   `TpLinkDecoData(master_deco, decos)` snapshot, retaining existing MAC-keyed
   Deco objects and marking absent previously known nodes offline.
   Assign that snapshot to `coordinator.data` **before** broadcasting
   `SIGNAL_DECO_ADDED`: the dispatcher invokes listeners synchronously,
   and every platform reads `coordinator.data` inside the callback.
4. Return that **same** snapshot from `_async_update_data()`, allowing
   Home Assistant's normal coordinator refresh path to perform its regular
   post-update notifications. Do not dispatch for an unchanged inventory,
   a temporarily offline previously known Deco, or a failed API request.
5. Mark synchronous discovery handlers with `@callback` so Home Assistant
   treats them as callbacks, not blocking jobs. In the current fork,
   `device_tracker.py` and `sensor.py` already do this; inspect the
   binary-sensor handler before changing it.
6. Keep registration idempotent by MAC for each platform. New nodes must
   obtain their original `device_tracker`, per-node `binary_sensor` and
   regular/diagnostic `sensor` entities without changing any existing
   entity IDs, master/satellite registry links or configuration.
   Network-wide Total Down/Up sensors continue to use the coordinator
   update listener, but only register when a master has at least one known
   satellite (including retained offline nodes). Do not register them for a
   standalone master. Keep master health diagnostics independent and available
   for standalone masters; preserve existing total-sensor IDs and avoid
   duplicate registration when nodes are discovered later.
   For optional WLAN entities, follow
   [wireless-status validation](../deco-wireless-status-validation/SKILL.md):
   master changes must update availability via a Deco coordinator listener
   without deleting previous registry identities.

## Repeatable regression and verification procedure

7. Build a real `TplinkDecoUpdateCoordinator` with a synthetic async
   device-list API. Patch `async_dispatcher_send` and inspect the coordinator
   from **inside** its immediate signal callback. Assert that both new
   MAC-keyed nodes and the master relationship are visible in `data`,
   and that the method returns the exact published object.
8. Set up the real tracker, binary-sensor and sensor platform functions.
   Patch their dispatcher subscriptions into one local callback registry,
   then deliver the signal synchronously. Assert the newly discovered
   MAC appears in all three entity types with the established unique IDs.
   Deliver the same node list and repeat the signal; no duplicates may
   appear. Cover late master discovery, disappearance/reappearance and
   independent configuration entries as relevant.
9. Verify unrelated coordinator behavior: existing Deco instances are
   reused, offline devices remain registered and marked offline, cached
   performance values are preserved, and late-master totals remain
   post-update/once-per-entry. Tests should not require physical routers
   or credentials.
10. Run focused pytest and then both supported matrix configurations
    (Python 3.13/HA 2025.12 and Python 3.14/HA 2026.11), plus pre-commit,
    HACS and Hassfest. Record exact CI results on the **final head**.
    Static inspection and mocked callback assertions do **not** establish
    full Home Assistant runtime or mesh-hardware validation.

## Regression-fixture lesson: compare snapshots at the right time

The PR #25 regression test initially compared an earlier refresh result with
`coordinator.data` **after a second refresh**. That is not a valid
snapshot-identity assertion: each successful refresh builds a new
`TpLinkDecoData` container even when all node MACs remain unchanged.

- Check `result is coordinator.data` **immediately after each refresh**,
  before initiating the next one. This proves that the published state and
  the state returned to Home Assistant refer to the same snapshot.
- Across two refreshes, compare the **MAC-indexed `TpLinkDeco` objects**
  instead of requiring the two snapshot containers to be the same. Known
  node objects must be reused; absent known nodes must be retained and
  marked offline.
- Mock `async_dispatcher_send` with a synchronous callback that reads
  `coordinator.data` _during_ notification. A post-refresh assertion
  alone cannot reproduce the original stale-data signal bug.
- Build actual entity platforms with the same patched dispatcher when
  checking discovery across trackers, binary sensors and per-node
  sensors. Repeated API results and manual notifications must not
  duplicate stable MAC-based unique IDs. Keep master-dependent totals
  on the separate post-update callback.

The documented expectations are grounded in
`tests/test_runtime_deco_discovery.py` and the coordinator's
`_async_update_data` implementation. They are **test construction rules**;
they do not establish successful pytest or real hardware execution.

## Tracking

11. Link an isolated backport with `Part of #2`. Update issue #2's in-progress
    status when the PR is created or materially updated. Complete only its
    matching checklist item after verifying a real merge and the
    implementation on `main`, leaving other upstream tasks and overall
    acceptance gates untouched.
