---
name: deco-client-device-linking
description: "Validate optional MAC-based device linking for TP-Link Deco client trackers, config-entry migration and safe removal of legacy client-only device records (upstream #605)."
---

# Client tracker MAC device-linking opt-out

## Prerequisites

1. Read `AI_POLICY.md`, `AGENTS.md`, `home-assistant.md` and
   [the upstream-sync skill](../deco-upstream-sync/SKILL.md). Inspect
   `config_flow.py`, `__init__.py`, `device_tracker.py`, the existing
   registry and tracker tests, and
   [upstream #605](https://github.com/amosyuen/ha-tplink-deco/pull/605).
2. Confirm the current config-flow version and the existing client tracker
   MAC/unique-ID behavior before porting code. Older upstream flow versions
   and the upstream's broad device-removal policy must not replace newer
   fork-specific behavior.

## Implementation invariants

3. Define `link_client_devices` as a **boolean** option defaulting to
   `True`; expose it in both setup and options schemas, and retain the
   current value when editing other options. On version 6→7 migration,
   populate the default without overwriting an explicitly saved `False`.
   **Home Assistant's `ConfigEntry.version` is immutable**: stage the
   version in a local variable, then call
   `hass.config_entries.async_update_entry(entry, data=..., version=...)`
   once. Never set `entry.version` directly. For regression coverage,
   construct a real `ConfigEntry`; a `SimpleNamespace` mock cannot
   detect invalid attribute mutations.
4. The **client entity unique ID stays the original MAC** whether linking
   is enabled or not. `ScannerEntity.mac_address` exposes the MAC only
   when enabled; when disabled, expose it as a client **state attribute**
   instead. Preserve hostname, connectivity, coordinator, associations
   and client restore behavior. The physical Deco tracker MAC property
   is always unaffected.
5. The opt-out prevents **future automatic scanner MAC matches**; it
   does not retroactively detach devices from other integrations. Do not
   promise automatic entity/device cleanup or reassign registry entities.
6. Before allowing manual removal through
   `async_remove_config_entry_device`, verify **all**: the option is
   disabled for that entry, the device is owned by exactly that config
   entry, it has no identifiers from Deco or another integration, and it
   has a real MAC connection. Reject shared, foreign, identified or
   non-MAC devices. Never remove a physical Deco device through this
   pathway. The callback grants Home Assistant permission; it does not
   itself delete registry entries.
7. Update `strings.json`, available translations, README and
   `home-assistant.md` for the user-visible toggle and its limitations.
   Do not imply that changing the option changes established `entity_id`
   or `unique_id`, or that disabling it erases the MAC from history.

## Verified migration review procedure (PR #24)

The P1 review found that updating `config_entry.version` directly
prevents real Home Assistant entries from loading. The previous
`SimpleNamespace` regression could not detect this because it allowed
the invalid write. Use this procedure for a future config-entry version
upgrade:

1. **Inspect supported Core APIs.** Check `ConfigEntry.__setattr__` and
   `ConfigEntries.async_update_entry` for both supported Home Assistant
   releases. Do not copy an older upstream migration that mutates the
   version directly.
2. **Stage without mutation.** Read `version = config_entry.version`
   and `new = dict(config_entry.data)`. Apply each historical migration
   in sequence to these **local** values, and use `setdefault` for
   newly introduced options that must preserve an existing `False`.
3. **Commit through the manager.** Call
   `hass.config_entries.async_update_entry` **once**, passing the staged
   `config_entry`, `data=new` and `version=version` together. Do not
   assign protected attributes on `ConfigEntry` or mutate its `data`
   mapping in place.
4. **Test the failure mechanism.** Build a real `ConfigEntry` using
   the required constructor fields from the installed HA version.
   Exercise version 5 and version 6 inputs with the new setting absent,
   `False`, and `True`. Assert no direct version mutation, a single
   manager update, version 7 as an argument, preserved unrelated values
   and the legacy v5 host migration. A `MagicMock` for the manager
   validates **arguments**, not the manager's actual persistence.
5. **Check surrounding regressions.** Update any stale
   `TplinkDecoFlowHandler.VERSION` expectation, then exercise
   setup/options forms, safe device-removal permissions and both
   supported HA versions. Do not report the review as runtime-tested
   until real pytest and CI jobs succeed on the **final PR head**.

## Regression matrix

8. Test default-enabled, explicit opt-out, re-enable and a missing legacy
   option; stable MAC-based unique IDs; client MAC state attribute only
   when opted out; physical Deco trackers unaffected; multiple
   config-entry independence; and owner-only legacy-device removal.
9. Test version migration for v5/v6, stored `False` retention,
   setup/options form JSON serialization and saved booleans. Update
   existing flow-version assertions rather than simply adding isolated
   tests. Check every locale's setup and options label.
10. Run the final-head Python 3.13/HA 2025.12 and Python 3.14/HA 2026.11
    regression matrix, pre-commit, HACS and Hassfest. Mark a check passed
    only with a completed successful run. No live device test is implied
    by mocked device-registry behavior.

## Tracking

11. Link the narrow backport as `Part of #2`, not `Fixes #2`.
    Update issue #2 when opening and materially updating the PR. Leave
    the checkbox open until the implementation is merged and verified on
    `main`; keep unrelated upstream features and acceptance gates open.
