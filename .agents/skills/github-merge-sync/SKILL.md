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
   comments on reruns. Serialize the merge workflow to avoid conflicting
   edits to a shared tracking issue. Apply strict pagination and
   linked-item limits; fail explicitly instead of silently skipping
   excessive or unverified references.
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
- The workflow does not retroactively process merges that happened before
  it was installed, update arbitrary external repositories, or infer
  relationships from GitHub discussions without explicit references.
