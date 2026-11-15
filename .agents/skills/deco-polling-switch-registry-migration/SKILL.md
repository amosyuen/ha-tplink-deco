---
name: deco-polling-switch-registry-migration
description: "Use when changing or reviewing the Deco polling switch's unique ID or Home Assistant entity-registry migration for multiple config entries (upstream #655)."
---

# Preserve polling-switch entities while isolating Deco config entries

## Prerequisites

1. Read `AI_POLICY.md`, `AGENTS.md`, and the
   [upstream synchronization skill](../deco-upstream-sync/SKILL.md).
   Inspect `switch.py`, the existing device-registry regression tests,
   and [upstream #655](https://github.com/amosyuen/ha-tplink-deco/pull/655).
2. Confirm whether the fork still uses the shared legacy unique ID
   `tplink_deco_polling`; do not infer a migration need from an upstream
   commit that may already have been ported.

## Migration rules

3. Scope new switch **unique IDs** to `config_entry.entry_id`, not MAC,
   master discovery order or entity name. Keep the established
   `tplink_deco_polling` prefix and the visible `Polling` name and icon.
4. Migrate the old switch **before** `async_add_entities`. Find the
   legacy entity through `entity_registry.async_get_entity_id` using the
   switch platform and this integration's domain. Read the actual
   `config_entry_id` from the registry entry and migrate only when it
   matches the config entry being set up. Never take a switch belonging
   to another Deco installation.
5. Call `async_update_entity(..., new_unique_id=...)` on the **existing**
   registry entity. This preserves the user's `entity_id`, customized
   name, enabled/disabled state, history and automations. Do not
   remove/recreate the entity, change its domain, or modify device
   identifiers or other platform unique IDs.
6. If no legacy entity exists, its registry record was removed, or the
   new unique ID is already registered, perform no migration. Preserve
   idempotency on subsequent reloads and defend against collisions.
   A default single-entry setup must continue to work normally.
   **Downgrades to a version that expects the old global unique ID are
   unsupported after migration**: that version can create a duplicate
   switch, potentially breaking automations. State this in the README
   before releasing the migration and recommend an entity-registry backup;
   do not promise automatic backward migration or safe downgrade.
7. Keep pause/resume and immediate-refresh behavior unchanged; keep
   master device linking, existing polling interval selectors,
   services and startup lifecycle intact.

## Validation and tracking

8. Test two independent config entries, both setup orders, existing
   owner-only migration, no legacy entry, missing registry record,
   conflicting scoped IDs, reloading after migration, untouched switch
   behavior, and setup ordering (migration must happen before adding
   the new entity). Update pre-existing tests that assert the old
   global unique ID; retain their other compatibility checks.
9. Run the full Python 3.13 / Home Assistant 2025.12 and Python 3.14 /
   Home Assistant 2026.11 matrix, plus pre-commit, HACS and Hassfest on
   the **final** PR head. Never claim a live device-registry migration
   was tested when only mocks were used.
10. Link the narrow change to issue #2 with `Part of #2`, not
    `Fixes #2`. Record the in-progress PR status immediately; only
    complete the matching checklist item after verifying a real merge
    and its implementation on `main`.

Store repository-wide rules in `AGENTS.md` and do not change the
governing `AI_POLICY.md` for routine implementation details.
