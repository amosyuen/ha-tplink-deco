---
name: github-merge-sync
description: "Use when reviewing, changing, validating or troubleshooting automatic synchronization of linked issues and related pull requests after a merge in HiDiHo01/ha-tplink-deco."
---

# Synchronize linked issues and related PRs on merge

1. Read the repository `AI_POLICY.md`, `AGENTS.md` and existing upstream-sync
   skill. Inspect `.github/workflows/sync-merged-references.yml`,
   `.github/scripts/sync_merge_links.py`, the GitHub merge event schema and
   `tests/test_merge_reference_sync.py` before changing automation.
2. Trigger only on `pull_request_target: closed` with `merged == true` and
   target branch equal to the default branch. Run only the **trusted default
   branch** version of the script; do not check out a PR head or run commands
   derived from PR bodies in a workflow that has a write-capable token.
   Explicitly scope `GITHUB_TOKEN` to contents read, issues write and pull
   requests write; do not expose the token in logs.
3. Resolve references only within the current repository. Recognize explicit
   issue directives (for example, `Part of #2`, `Related to #2`, `Refs #2`),
   same-repository issue URLs and GitHub Development closing links. Do not
   mutate upstream repositories or infer links solely from a shared word or
   label.
4. On a confirmed merge, update an existing linked issue status entry and
   check **only** checklist lines that explicitly mention the merged PR
   number or URL. Leave unrelated checklist lines, broad acceptance
   criteria and the parent issue state unchanged. An issue referred to by
   a PR is not necessarily complete in its entirety.
5. Notify only genuinely related **open** PRs: those sharing a directly
   linked issue or explicitly referencing the merged PR. Post a concise
   informational comment; never rebase, auto-merge or close other PRs.
6. Use stable, bot-owned HTML comment markers to avoid duplicate issue/PR
   comments on reruns. Serialize the merge workflow and use `queue: max`
   to retain up to 100 pending runs rather than replacing the previous
   pending merge. Schedule bounded 48-hour reconciliation of confirmed
   default-branch merges, skipping only those with a completed bot-owned
   summary. Apply strict pagination and linked-item limits; fail
   explicitly when reconciliation cannot verify the full window.
   Do not infer unlimited durability from the bounded queue and scan.
7. Treat the merge event, PR text, issue bodies and GraphQL results as
   untrusted **data**. Validate the repository, PR number, merge SHA and
   default branch; sanitize logging; use parameterized API requests and
   never interpolate issue/PR content into shell commands.
8. Test issue parsing (including ignored upstream links, Markdown code and
   comments), explicit task matching, status transitions, incomplete or
   unrelated PRs, duplicate reruns, missing merge metadata, cross-repo
   GraphQL links and scoped related-PR notices. Run tests in the existing
   Python/Home Assistant matrix plus pre-commit, HACS and Hassfest.

## Pinned action revisions (PR #37 merge failure)

**Observed failure:** The PR #37 post-merge sync job could not initialize
because the repository requires `uses:` actions pinned to full-length
commit SHAs. The rejected workflow referenced `actions/checkout@v6`
and `actions/setup-python@v6.2.0`. This failure is separate from the
PR's successful Python/HA and linting checks.

1. Inspect the failed **merge-triggered job log**, the current
   `.github/workflows/sync-merged-references.yml` and the working
   `.github/workflows/tests.yaml` and `pytest.yaml` references.
2. Resolve exact release-tag commit SHAs using official GitHub Actions
   repository refs. For the verified releases: `actions/checkout@v6`
   resolves to `d23441a48e516b6c34aea4fa41551a30e30af803`, and
   `actions/setup-python@v6.2.0` resolves to
   `a309ff8b426b58ec0e2a45f0f869d46889d02405`. Include version
   comments for readability; do not replace the pins with movable tags.
3. Keep `pull_request_target: closed`, the confirmed merge and
   default-branch conditions, the trusted default-branch checkout,
   `persist-credentials: false`, and minimal contents/read plus
   issues/pull-requests/write permissions unchanged. Never checkout
   untrusted PR head code using a write-capable token.
4. Add an offline regression test that reads the actual workflow and
   verifies its pinned action references and safety-critical guards.
   Retain the existing mock synchronization tests; changing the workflow
   must not change the linked-issue semantics or mark issue #2 complete.
5. Run the existing Python 3.13 / HA 2025.12 and Python 3.14 /
   HA 2026.11 regression matrices, pre-commit, HACS and Hassfest on
   the final head. Successful PR CI establishes static correctness,
   **not** the functioning of a merge-triggered event. After a reviewed
   merge to `main`, inspect a new real merge-triggered run; failed
   past events are not automatically replayed.

## Review hardening: lost events, action scope and structural tests

- **Concurrency review:** `cancel-in-progress: false` without
  `queue: max` is not lossless: newer pending runs replace older
  pending runs. GitHub's 100-pending-run maximum is still bounded.
  Scheduled recovery must inspect recent merged PRs on the trusted
  default branch, verify merge metadata, and use the existing bot
  summary marker to skip completed work. Reconciliation is limited
  to 48 hours; report window or pagination gaps instead of implying
  unbounded durability. Preserve the same serialization group for
  scheduled and event-triggered runs.
- **Repository-wide action policy:** inspect all six workflows, not
  just merge synchronization. Verify the action refs using official
  GitHub tag objects, dereferencing annotated tags to their commits.
  Prior to this PR, `labeler.yml` used `actions/checkout@v6` and
  `crazy-max/ghaction-github-labeler@v5.3.0`,
  `dependabot-auto-merge.yml` used `dependabot/fetch-metadata@v2.5.0`,
  and `release-drafter.yml` used
  `release-drafter/release-drafter@v7.2.1`.
  All are pinned on this PR branch. Protect every workflow `uses`
  entry with the shared regression test.
- **Structural security tests:** parse workflow YAML with a safe,
  non-coercing loader so the `on` key stays literal. Assert the exact
  trigger, permission mapping, merge/default-branch condition, trusted
  checkout ref, disabled persisted credentials, pinned actions and
  scheduled recovery. Negative tests must reject additional triggers
  or rights, moved guards and bracket-notation PR-head checkouts.
  Tests cannot establish actual deployment; verify a new real
  scheduled and merge-triggered run after merging.

## Failure classification and recovery verification

1. **Whole-scan failure before mutation.** Enumerate the bounded
   48-hour window and validate every eligible merge's same-repository
   default-branch target, positive PR number, full merge SHA,
   timezone-aware timestamps and optional text-field types. Reject
   invalid responses, missing pagination coverage and malformed
   later records before issuing any issue or PR writes. Duplicate
   list entries are processed at most once.
2. **Per-candidate failure after preflight.** Process confirmed merges
   in merge-time order. Catch an individual PR's processing failure
   only after preflight, log its public number without upstream error
   details, and continue to subsequent candidates. Leave the failed
   candidate without a completion marker; finish with a nonzero
   aggregate failure status. No individual failure should starve a
   later valid merge.
3. **Partial-write and retry contract.** GitHub updates are not
   transactional across issues, comments and related PRs. A timeout
   may occur after a write succeeds; never blindly replay POST/PATCH.
   On the next serialized scheduled run, use bot-owned markers and
   current issue state to complete missing updates without duplicating
   successful ones. Do not claim the entire batch succeeded if one
   candidate remains incomplete.
4. **Privacy and diagnostics.** HTTP errors, connection failures,
   timeouts and invalid JSON must yield fixed sanitized messages,
   without response bodies, request URLs, secrets or exception-chain
   text. Logs may identify only public PR numbers and aggregate
   counts. Test with synthetic sensitive values; do not write raw
   GitHub API data into issues or review comments.
5. **Deterministic regression matrix.** Test corrupt *later* metadata
   blocking all writes; a PR-specific failure followed by a valid PR;
   a second scheduled pass that retries only incomplete work; a
   duplicate PR result; invalid or naive timestamps; and redacted
   HTTP/network/JSON failures. Keep the workflow YAML-structure
   assertions (trusted default-branch checkout, minimum permissions,
   exact triggers, concurrency and SHA-pinned actions).
6. **Final-head and deployment checks.** Verify both Python/HA
   matrices, pre-commit, HACS and Hassfest on the same final commit.
   A skipped review check is not a successful review. After an
   approved merge, inspect a real merged-PR run and a real hourly
   scheduled run, verify bot-owned completion markers, and record
   any failed candidates. Queue capacity (100), pagination and
   the 48-hour recovery window are finite; anything older requires
   explicit operator review rather than automatic unbounded replay.

## Deployment and limitations

- This workflow only becomes active when merged onto the repository default
  branch. Running tests on a PR cannot prove that the hosted merge event has
  executed; inspect the first **actual merge-triggered run** and its issues
  and PR comments after deploying it.
- Link the workflow PR to issue #2 as **related** without closing that
  upstream-tracking issue. Record its in-progress status before merge, but
  do not add it to an unrelated upstream checklist.
- The job records a GitHub-confirmed merge, not a hardware/runtime test.
  Human review remains responsible for checking the merged change's actual
  behavior, and for any further checklist work without an explicit PR link.
- Scheduled reconciliation may revisit confirmed merges from the last
  48 hours, including missed events near deployment. It skips merges
  with a completed bot-owned summary and never scans older history
  automatically. Older gaps require explicit operator review. The
  workflow never updates external repositories or infers relationships
  without explicit references.
