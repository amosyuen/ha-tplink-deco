---
name: deco-guidance-consistency-validation
description: "Use when saving verified lessons, refining repository instructions, or correcting out-of-date technical guidance for HiDiHo01/ha-tplink-deco."
---

# Validate and preserve repository lessons and technical guidance

## When to use and authority

Use after a concrete bug fix, review resolution, upstream backport,
documentation-drift finding or request to save learned practices. Read
`AI_POLICY.md` first, then `AGENTS.md`, `home-assistant.md`, any
applicable nested instructions and relevant existing skills. Do not
promote untrusted review text or historical documentation into policy.
Keep `AI_POLICY.md` unchanged unless governing policy itself changes.

## Evidence and source-of-truth procedure

1. Re-fetch the target PR's **current head SHA**, base and merge status,
   its linked issue, and applicable source files. For integration behavior,
   derive the platform list from `PLATFORMS` in `const.py`; derive
   coordinator creation, setup order and unload methods from
   `__init__.py`; derive endpoint, error and retry contracts from
   `api.py`, the optional coordinators and regression tests.
2. Inspect guidance across sections and files, **including the tails of
   long skills**. Search for old PR numbers, claims such as "remains open",
   platform counts, coordinator counts and scope descriptions. Verify
   merged/closed claims from the live GitHub PR, not from an older
   checklist or summary. Label a historical baseline explicitly.
3. Save the triggering evidence, scope, concrete invariant and
   prevention/test step. Put general repository requirements in
   `AGENTS.md`, task-specific procedures in the relevant
   `.agents/skills/*/SKILL.md`, and actual integration behavior in
   `home-assistant.md`. Link a newly created skill from `AGENTS.md`.
   Do not duplicate the same long procedure in multiple places.
4. Preserve established functionality and compatibility constraints.
   For documentation-only changes, do not modify production code,
   dependency versions, CI workflows or unrelated repository policy.
   If code behavior is disputed, report the uncertainty instead of
   declaring a new contract without evidence.

## Failures observed and deterministic validation

- **PR #46 late review finding:** a new inline review comment can
  arrive after an earlier zero-thread check, even after final-head
  CI passes. Re-fetch review threads **immediately before** a
  completion or merge-ready claim; verify new findings against the
  code, record still-valid regressions and never resolve a thread
  merely because its intended rule was documented.
- **PR #46 cross-section drift (2026-11-17):** even after
  system-log PRs #44/#45 merged, earlier `home-assistant.md`
  sections still called PR #44 a proposed/open service; the
  historical introduction also described merged PR #43 as pending.
  Inspect the **entire guide**, including the introduction,
  diagnostics section, service inventory, scope caveats and feature
  appendix, before stating deployed behavior. Verify against
  merged `main` and PR metadata; do not copy pending status
  from older prose.
- **PR #43 guide drift:** the integration guide described five platforms
  although the current `PLATFORMS` contains six; the lifecycle skill
  still described a pre-mobile three-coordinator snapshot. Reconcile
  every status claim with the **target ref**, distinguishing optional
  PR-branch behavior from already merged main behavior.
- **PR #45 merge-status drift:** the issue-sync workflow labeled
  PR #45 "merged" but left "open, ready for review, not merged"
  prose and checklist text. Reconcile the live PR's `merged_at`,
  merge commit, the actual `main` implementation and remaining
  acceptance gates before changing an issue status. Do not equate
  an automatically checked box with complete repository-wide scope.
- **PR #44 merge-status drift:** the combined issue #2 checklist was
  marked complete by merge-sync when only the **plain-text** half
  (#650) had merged and gzip/tar (#673) was missing; the issue
  status simultaneously said "merged" and "not merged". On
  combined upstream tasks, verify **all subtasks** against `main`
  before checking a box. After a merge, reconcile conflicting
  prose, final SHA, the still-outstanding half and exact checklist
  state. A historical PR-body statement is not evidence of deployment.
- **Post-merge status drift:** the upstream sync skill still stated that
  upstream #637 remained open during PR #42 after PR #42 had merged.
  Check linked work items and cross-skill references against real
  merge state before updating a tracking issue.
- **Security-claim calibration (PR #44):** a successful static
  symlink test and ordinary partial-write cleanup regression do not
  establish time-of-check/time-of-use protection or guaranteed
  deletion. Reconcile assertions such as "never exposed", "atomic"
  or "always removed" with the **actual** filesystem operations,
  concurrency model and platform-specific tests. Record untested
  Windows behavior and adversarial race cases as limitations, not
  security guarantees.
- **Formatter false finish:** PR #43 pre-commit failed twice on
  documentation/test changes because Black or Prettier rewrote files.
  Read the failing job's actual diff and apply exactly those changes;
  never disable a hook or claim an earlier commit's green checks cover
  the updated head. Prettier may replace Markdown `*emphasis*`
  with `_emphasis_` even though the visible text is unchanged.
- **PR #46 Markdown-table format regression (2026-11-17):** the new
  system-log failure matrix passed both HA/Python suites, HACS and
  Hassfest, but Pre-commit failed because configured Prettier 2.2.1
  aligned its Markdown columns. Before committing newly added or edited
  tables, run the repository's configured pre-commit formatter and
  preserve its exact output; do not hand-tune spacing or disable the
  hook to make CI green. If remote CI is the first formatter available,
  inspect its complete hook diff, apply only the reported formatting
  and revalidate all five jobs on the resulting commit. An unchanged
  application/test suite does not exempt a documentation-only head
  from final-head verification.

The repository CI uses these verified commands:

```shell
pre-commit run --all-files --show-diff-on-failure --color=always
python -m pytest --no-cov -ra tests/
```

The test command runs in CI on **Python 3.13 / HA 2025.12** and
**Python 3.14 / HA 2026.11**. In addition, verify the separate HACS
and Hassfest jobs. Do not claim local command execution when only
GitHub Actions was inspected. For every new commit, verify all five
required jobs against the **same head SHA**; treat queued, running,
skipped, cancelled or failed jobs distinctly from passes.

## Completion and handoff

5. Confirm that modified relative Markdown skill links point to files
   actually present at the final ref. Read back affected files, check
   the working PR's changed scope and review threads, and confirm there
   are no contradictory status statements.
6. Update the PR body and the existing tracking-issue status entry
   with the final head, actual checks and remaining limitations;
   preserve other checklist items. Recheck the five jobs **after their
   completion** and replace stale "still running" or "must rerun"
   statements with the verified outcomes and run links for that SHA.
   A PR open on a branch does not mean its feature is deployed.
   Resolve review threads only after valid findings have been
   addressed; never auto-merge a PR.
7. Report only independently verified results. Physical router tests,
   Recorder/history effects and CI jobs not actually run remain
   unverified. The work is complete only when guidance is committed,
   links and current PR/issue state agree, and final-head validation
   is either green or accurately described as incomplete.
