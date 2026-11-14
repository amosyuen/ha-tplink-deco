---
name: deco-service-registry-validation
description: "Use when implementing, reviewing, or testing TP-Link Deco Home Assistant services that resolve device-registry IDs, especially reboot_deco and batch device actions. Covers multi-identifier devices, invalid selections and async service regressions."
---

# Validate Deco device-registry service actions

## Before changing a service

1. Read the repository's `AI_POLICY.md`, `AGENTS.md` and relevant upstream
   synchronization guidance. Inspect the current branch, service schema,
   registered handler, device-registry lookups, and existing service tests.
2. Identify the stored identity contract: Deco devices use stable
   `(DOMAIN, MAC)` registry identifiers. Do not change entity unique IDs,
   device identifiers, configurations or the public service interface merely
   to fix identifier selection.

## Handle device selections safely

3. Assume a Home Assistant device can expose zero, one or multiple
   `identifiers` (including identifiers from other integrations). Find the
   nonempty MAC from an identifier whose domain is `tplink_deco`; do not
   assume there is exactly one identifier or dereference a missing match.
4. Resolve every requested device ID from the registry. A missing device,
   absent Deco-domain identifier, or empty MAC must produce a descriptive
   service error. Do not forward unrelated identifiers to the router.
5. Validate the **entire** selection before sending the asynchronous router
   command. Preserve the requested device order and avoid partial actions if
   a later selection is invalid. Leave the existing API/coordinator lifecycle
   and authorization checks intact.
6. Avoid sensitive logs: never record device names, raw registry records,
   credentials, session data or network responses just to diagnose a failed
   service selection.

## Verify real service behavior

7. Test identifier extraction and the **registered service callback**, not
   just a helper. Mock the Home Assistant registry and the async Deco API;
   no real Deco or user credentials are needed. Cover a single identifier,
   a valid Deco identifier among unrelated identifiers, empty/wrong-domain
   identifiers, unknown devices and multiple selected Deco devices.
8. Assert both the successful API argument list and the absence of any
   router API call on invalid selections. For batch changes, also cover a
   valid device followed by an invalid device to guard against partial
   execution.
9. Apply the repository's own Black, isort, flake8 and pre-commit settings.
   Validate the supported Python/Home Assistant test matrix and report
   pytest, HACS and Hassfest statuses accurately. A source review or
   unexecuted test cannot be reported as a passing integration test.

## Handoff

10. Link focused upstream ports to tracking issue #2 as `Part of #2`;
    leave unrelated issues and services unchanged. Record tests actually
    executed, remaining hardware limitations, and any newly verified
    reusable lesson in the appropriate repository instructions.

For general standards, follow `AGENTS.md`. For upstream comparisons, use
`.agents/skills/deco-upstream-sync/SKILL.md`. For Home Assistant forms
and the CI matrix, use `.agents/skills/deco-config-flow-validation/SKILL.md`.
