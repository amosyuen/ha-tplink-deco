---
name: deco-client-restore-validation
description: "Safely restore unavailable TP-Link Deco client trackers across Home Assistant 2025.12 and 2026.11, reconciling provisional client records after a successful device refresh (upstream #619)."
---

# Restore unavailable Deco client trackers without identity loss

## Prerequisites

1. Read `AI_POLICY.md`, `AGENTS.md`, `home-assistant.md` and the
   [upstream-sync skill](../deco-upstream-sync/SKILL.md).
   Inspect `async_create_config_data` and
   `async_create_and_refresh_coordinators` in `__init__.py`,
   `TplinkDecoData`, `TpLinkDecoClient` and the existing client-state
   retention tests before modifying startup restoration.
2. Check [upstream #619](https://github.com/amosyuen/ha-tplink-deco/pull/619)
   against the **fork's current source**, not just its historical diff.
   Preserve client-retention semantics, safe coordinator lifecycle, per-entry
   ownership and already merged runtime discovery behavior.

## Version-specific storage contract

3. In Home Assistant 2025.12, restored states are available through
   `restore_state.async_get(hass).last_states`, indexed by `entity_id`.
   Home Assistant 2026.11 has registry-aware restored-state storage and
   `async_get_stored_state(entity_id)`. Use capability detection:
   call the lookup method when it exists, otherwise use
   `last_states.get`. This lookup is **synchronous** in both supported
   versions; do not await it.
4. Iterate only entities from
   `entity_registry.async_entries_for_config_entry` of the requested
   config entry. Skip entries outside `device_tracker`, entries
   disabled in the entity registry and entries without a saved state.
   Do not rebuild entities from unrelated configuration entries.

## Restore and reconcile safely

5. A previously unavailable client tracker may have saved attributes
   without `device_type`. Preserve its MAC-based `unique_id` and
   `original_name`, and seed a provisional `TpLinkDecoClient` rather
   than silently dropping it. Explicitly classified `DEVICE_TYPE_DECO`
   entries remain `TpLinkDeco`; ordinary classified clients retain
   their usual handling. Do not alter the entity registry or reassign
   entity IDs as part of restoration.
6. After **successful** first Deco device-list refresh, and **before**
   creating the client coordinator, reconcile the provisional client
   dictionary against `deco_coordinator.data.decos`. Remove only MACs
   confirmed as Deco nodes, retaining all remaining offline clients and
   their original objects. Reconciliation must be idempotent.
   A failed first refresh must not discard provisional client state.
7. Do not change the meaning of a successful empty client response,
   per-node HTTP 5xx backoff, `consider_home`, CPU/memory readings,
   session authentication or the existing polling services.

## Regression matrix and completion criteria

8. Use synthetic entity registry records and stored states to test
   **both** supported storage API shapes. Cover states missing
   `device_type` (including `unavailable`), recognized Deco/client
   types, disabled/non-tracker records, missing saved states, and two
   independent config entries.
9. Simulate the **real integration setup order** with mocked API and
   coordinator methods: confirm the first Deco refresh completes before
   client coordinator construction, and verify that provisional clients
   matching confirmed Deco MACs are removed while genuine clients remain.
   On a failed Deco refresh, verify no reconciliation or client coordinator
   initialization occurs.
10. Run targeted pytest and both Python 3.13/HA 2025.12 and Python
    3.14/HA 2026.11 CI suites on the final PR head. Run the repository
    pre-commit, HACS and Hassfest checks. Static review and committed
    tests are **not** equivalent to executed tests. Do not claim
    live firmware validation without it.

## Issue tracking

11. Use `Part of #2` for the isolated upstream backport and update
    tracking issue #2 when the PR is opened or materially updated.
    Leave its matching checkbox unchecked until a verified merge;
    preserve the unrelated startup client-count fixes (#567/#569/#597)
    and the overall acceptance criteria as pending unless independently
    implemented and confirmed.
