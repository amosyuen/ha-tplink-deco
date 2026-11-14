---
name: deco-device-registry-parent-links
description: "Use when changing, reviewing, or testing TP-Link Deco master/satellite parent relationships in Home Assistant device_info, including via_device to via_device_id migrations, compatibility tests, and PR #18 regressions. Do not use for reboot service device selection."
---

# Validate Deco device-registry parent relationships

This skill covers **entity device-info relationships**, not device IDs passed
to actions such as `reboot_deco`. For service input validation, use
[deco-service-registry-validation](../deco-service-registry-validation/SKILL.md).

## Inspect the existing contract

1. Read `AI_POLICY.md`, `AGENTS.md` and
   [deco-upstream-sync](../deco-upstream-sync/SKILL.md) before changing code.
   Inspect `custom_components/tplink_deco/device.py`, the master-first
   discovery path in `device_tracker.py`, every `create_device_info`
   caller and the existing tests.
2. Compare behavior against the upstream change being ported (for example,
   [upstream #579](https://github.com/amosyuen/ha-tplink-deco/pull/579)).
   Identify all supported Home Assistant releases and their actual
   `DeviceInfo` fields. Do not equate a tuple identifier with a registry ID.
3. Inventory existing assertions that depend on the old field, including
   unrelated regression tests such as `tests/test_deco_nickname.py`.
   This is mandatory: PR #18 initially failed on HA 2026.11 because an
   **existing nickname test** still accessed `device_info["via_device"]`
   after the implementation switched to the modern field.

## Implement without losing device identity

4. Keep `(DOMAIN, deco.mac)` as the device identifier, preserve entity
   unique IDs, saved configurations, client associations and fork-specific
   diagnostics. Register or retrieve the **master** before linking a
   satellite. Resolve its actual Home Assistant registry ID through the
   same config entry, and set `via_device_id` on versions supporting it.
5. Use API capability detection (currently
   `"via_device_id" in DeviceInfo.__annotations__`) rather than hard-coded
   version comparisons. On older supported versions, retain the
   `"via_device": (DOMAIN, master.mac)` compatibility path. Do not import
   deprecated `ATTR_VIA_DEVICE` on modern Home Assistant.
6. Thread the Deco coordinator through *all* device-info users: Deco and
   client trackers, regular/diagnostic/throughput sensors, binary sensors,
   polling select and polling switch. Client-related entities need the
   **Deco coordinator** for their parent relationship, not merely the
   client coordinator. Do not link the master to itself or invent a parent
   when a master, Deco or coordinator is unavailable.

## Prove compatibility with tests

7. Test both simulated legacy and modern `DeviceInfo` behavior and exercise
   the *real installed* `DeviceInfo` on both supported CI matrix versions.
   Verify master and satellite identity, missing context, name fallbacks,
   per-config-entry registry lookup, actual entity `device_info` output,
   and unchanged unique IDs. Use deterministic fake registry IDs without
   connecting to real Deco hardware.
8. Search the **whole tests directory** for old field lookups and
   assumptions; update affected assertions to be version-aware while
   preserving the original behavior under test. Do not disable or delete
   a failing nickname/device-identity test just to make a new API pass.
   The full suite must pass: new targeted tests alone are insufficient.
9. Run the complete regression matrix (Python 3.13 / Home Assistant 2025.12,
   Python 3.14 / Home Assistant 2026.11) and the pre-commit, HACS and
   Hassfest workflows. When Black/isort rewrites `sensor.py` or tests,
   commit only those formatting changes and rerun CI on the **latest
   PR-head SHA**. Keep CI gates unchanged.

## PR handoff

10. Record actual run links and distinguish passes, failures, skipped jobs
    and physical-hardware limitations. Check mergeability and unresolved
    reviews. Link upstream work as **Part of #2**, never `Fixes #2`, and
    update the tracking issue's completed checklist only **after merge**.

Repository-wide standards remain in `AGENTS.md`; governing policy remains
in `AI_POLICY.md`.
