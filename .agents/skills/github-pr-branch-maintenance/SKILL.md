---
name: github-pr-branch-maintenance
description: "Safely diagnose GitHub PR merge/rebase status, update branch history with lease protection when authorized, and verify final-head CI and issue tracking."
---

# Maintain GitHub PR branches without losing changes

## When to use

Use for a PR that reports **merge conflicts**, `rebaseable=false`,
stale base commits, or an explicit request to rebase/squash its head.
This is separate from [post-merge reference synchronization](../github-merge-sync/SKILL.md).
**PR #36 (15 November 2026) is the verified example:** GitHub reported
`rebaseable=false`, `mergeable=true`, `mergeable_state=clean`
and zero commits behind `main`. A successful lease-guarded history
rewrite later made it `rebaseable=true` without changing its file tree.

## Prerequisites and diagnosis

1. Read the repository `AI_POLICY.md` and `AGENTS.md` before changing
   anything. Check the current PR body and reviews, its source/target
   repositories, actual branch names and latest head/base commit SHAs.
2. Read GitHub's current `mergeable`, `mergeable_state`, and
   `rebaseable` independently. Compare `main...head` for merge base,
   ahead/behind counts and changed paths. A `clean` mergeable PR is
   **not** a merge conflict just because `rebaseable=false`; a
   temporary `unstable` state can reflect pending checks.
3. If the current branch is already up to date and mergeable, leave it
   untouched unless a branch rewrite was explicitly requested. Explain
   whether rewriting history would be necessary to obtain the desired
   outcome. Never run a force push merely to refresh the UI.

## Safe branch update

4. Record the _observed_ head SHA as the lease and the base SHA to
   build on. Re-read both immediately before writing; abort if either
   changed. Inspect relevant repository instructions and diffs.
5. Prefer a normal rebase that retains individual commits. Squashing
   several commits into a single-parent commit rewrites their history:
   use it only with an explicitly authorized scope. When preserving the
   exact final file content, compare the old and new tree SHAs or full
   diffs; avoid losing fork-specific files or unrelated modifications.
   If the base introduces conflicting changes, resolve those conflicts
   deliberately and test the result instead of discarding a side.
6. Use a lease-protected update: with Git, `--force-with-lease`;
   with a GitHub ref API, require `expected_sha` equal to the observed
   old head and use force only for a genuinely non-fast-forward update.
   Never retry a rejected lease blindly; fetch the new head and
   reconcile first. Do not use an unconditional force push.

### Verified GitHub-only linearization (PR #57, 2026-11-18)

- **Diagnosis first:** PR #57 had `mergeable=true`,
  `mergeable_state=clean`, `rebaseable=false` and zero commits
  behind `main`. Its history contained a merge-from-main commit,
  not an unresolved file conflict. Only an explicit user-authorized
  force-rebase justified rewriting this otherwise mergeable branch.
- **Reconstruct deliberately:** list the original commits, their
  parent SHAs and actual changed paths before writing objects. With
  GitHub's Git data APIs, build each replacement tree from the preceding
  tree and the intended file blob SHAs; create single-parent commits in
  content-change order on the verified latest `main`. Omit an obsolete
  merge commit only after confirming the needed changes are already in
  the base or preserved by the replay. Never assume every commit changes
  exactly one file without inspecting it.
- **Prove tree equivalence before the ref update:** PR #57 replaced an
  18-commit history with 17 linear content commits. Both final Git tree
  SHAs were exactly `8da031565776eca38d64a55cdbbef4724cb6d8a7`.
  Compare the full intended changed-path set and require zero commits
  behind `main`; abort on a tree mismatch or any unexpected path.
  Re-fetch branch/base SHAs immediately before using `update_ref`
  with `force=true` **and** `expected_sha` matching the old head.
- **Revalidate the rewritten SHA:** GitHub's initial
  `mergeable_state=unstable` reflected running CI, not a merge
  conflict. All five required jobs passed on the new SHA before a
  merge-ready claim. During the last status check PR #57 became
  `merged=true` (merge commit `cf90deaa`); verify the real merge
  commit and `main` tree, then update the tracked issue from
  *open* to *merged* without checking unrelated acceptance criteria.
  Never claim a merge was performed by the assistant when the
  external repository state changed during verification.

## Verification and handoff

7. Fetch the PR again and check its current head, target base, compare
   status, changed files, `mergeable`, `rebaseable` and review threads.
   Do not claim an unsuccessful rebase was completed or confuse a
   successful branch update with a successful merge.
8. Inspect **final-head** required checks: Python 3.13/HA 2025.12,
   Python 3.14/HA 2026.11, pre-commit, HACS and Hassfest. Separate
   passed, failed, pending, skipped and unavailable checks. After _any_
   new commit, prior green runs no longer establish final-head CI.
   Inspect the exact formatting/tool log before making a minimal fix
   and repeat the checks on the resulting SHA.
9. Re-read the PR body, approvals and related issue after automated
   reviewers have run. A force update can invalidate approvals, and
   bots may reintroduce stale commit or scope claims. Update only
   outdated facts and include the current commit plus actually
   completed CI runs. Leave open work and issue #2 unchecked unless
   the appropriate PR was actually merged and verified.

## Completion criteria

The expected file changes are preserved; the branch update has succeeded;
GitHub's fresh status matches the requested outcome; no unaddressed
review threads remain; all required checks **on the final head** have
passed or are reported accurately as incomplete; and the PR and linked
issue reflect the verified scope. A successful API response alone does
not satisfy these criteria.
