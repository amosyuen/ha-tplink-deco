---
name: deco-upstream-sync
description: "Use when comparing, backporting, reviewing, or implementing changes from amosyuen/ha-tplink-deco into HiDiHo01/ha-tplink-deco, especially tracking issue #2, compatibility fixes, device naming and PR regressions. Do not use for unrelated repositories."
---

# Safely port TP-Link Deco upstream changes

1. Read the current repository `AGENTS.md`, any applicable `AI_POLICY.md`, and nested instructions before editing. Inspect current `main`, the target issue, the upstream change, and related fork PRs. Do not assume a missing upstream commit means missing behavior.
2. Choose one independently testable part of [tracking issue #2](https://github.com/HiDiHo01/ha-tplink-deco/issues/2). Create a branch from the latest fork `main`; avoid a bulk upstream merge.
3. Compare the **behavior**, not just the diff. Keep the fork's `sensor.py`, CPU/memory and backhaul diagnostics, connected-client entities, configurable polling, switch/select entities, pause/resume services, and existing configuration flows.
4. Preserve MAC-based device identifiers, entity unique IDs, master/satellite links, config-entry data and automations. If a migration is necessary, add regression tests for existing installations.
5. Account for firmware variability: Base64 UTF-8 and plain-text names, legacy `<Error Decoding ...>` wrappers, absent/empty nicknames, multiple mesh nodes, and optional API fields. Normalize a candidate name **before** checking whether it is empty. Fall back from custom nickname to firmware nickname to MAC.
6. Protect privacy: never log complete raw device/client lists, passwords, tokens or other sensitive firmware payloads. Test log redaction at the API-response-handler level, not solely at a decoding helper.
7. Add focused tests for the change and run the available checks. For test setup and HA form regressions, use the related `deco-config-flow-validation` skill. Report test limitations explicitly; do not say tests passed merely because they are present.
8. Open or update a **small PR** linked as `Part of #2`, not `Fixes #2`. Address valid review findings and resolve threads only after the corresponding change is committed or an explanation is supplied. Update issue #2's checklist only after the relevant scope has been merged; leave unported items open.

## Sensor and throughput backports (PR #6)

- Read the fork's sensor/coordinator behavior before applying an upstream
  change; the fork has extra diagnostics and different entity definitions.
- For throughput, filter using the existing client `online` state **before**
  summing cached rates. Network totals span all nodes; per-Deco totals also
  filter by the client's `deco_mac`. Do not change client-count sensors,
  tracker presence or `consider_home` semantics as a side effect.
- Verify both directions, stale offline rates, unknown status, multiple
  Decos, empty inventories, reconnects and stable sensor unique IDs.
- Add targeted runtime regression tests and distinguish successful tests
  from unexecuted Home Assistant-dependent checks. See `AGENTS.md` for
  the repository-wide constraints.

## Device-registry service backports (PR #8)

- Inspect the registered service callback and registry lookup, not just a
  standalone identifier helper. Home Assistant devices can carry multiple
  identifiers from different integrations; identify the Deco MAC by the
  `tplink_deco` domain rather than requiring a singleton identifier set.
- For a batch service such as `reboot_deco`, resolve and validate every
  selected device before making the router API call. Missing devices, absent
  Deco identifiers and empty MACs must produce a clear error and must not
  trigger a partial action. Do not change stable MAC-based entity/device IDs.
- Test both the helper and the real registered service callback with mocked
  registry devices and a mocked async reboot API. Include extra identifiers,
  multiple selected Decos, wrong-domain/missing identifiers, empty MACs and
  unknown devices; assert that failures never invoke the router.
- Apply the repository's configured isort/Black/pre-commit output rather than
  assuming generic import ordering. Confirm the full Python/HA test matrix,
  HACS and Hassfest results before claiming completion.

## Handoff checklist

- State exactly which upstream change was ported and which behaviors remain out of scope.
- Confirm no existing fork-specific entities or services were removed.
- Identify the tests actually executed, pending CI, and any blocked checks.
- Check current merge conflicts and unresolved review threads before reporting completion.
- Evaluate verified lessons from the change/review; update `AGENTS.md` or the relevant skill on this branch when reusable, otherwise state that no guidance update was needed.

`AGENTS.md` remains the source of repository-wide policy and quality requirements.
