"""Regression tests for post-merge issue and related-PR synchronization."""

from copy import deepcopy
from datetime import datetime
from datetime import timezone
import importlib.util
from pathlib import Path
import re
import unittest

import yaml

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / ".github" / "scripts" / "sync_merge_links.py"
)
_SPEC = importlib.util.spec_from_file_location("deco_merge_sync", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
sync = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sync)

REPOSITORY = "HiDiHo01/ha-tplink-deco"
MERGE_SHA = "a" * 40
ISSUE_PATH = f"/repos/{REPOSITORY}/issues/2"


def _event(
    *,
    merged: bool = True,
    base: str = "main",
    body: str = "Part of #2",
) -> dict[str, object]:
    """Provide a synthetic closed PR event with a validated merge SHA."""
    return {
        "action": "closed",
        "repository": {"default_branch": "main"},
        "pull_request": {
            "number": 19,
            "title": "Retry incomplete responses",
            "body": body,
            "merged": merged,
            "merged_at": "2026-11-15T10:30:00Z",
            "merge_commit_sha": MERGE_SHA,
            "base": {"ref": base, "repo": {"full_name": REPOSITORY}},
        },
    }


class _FakeGitHub:
    """Mock API writes without accessing GitHub or authenticating."""

    def __init__(self) -> None:
        """Create a tracked issue and a small collection of related PRs."""
        self.issues = {
            2: {
                "body": (
                    "## Implementation status\n"
                    "- **In progress (not merged):** [PR #19]"
                    f"(https://github.com/{REPOSITORY}/pull/19)\n"
                    "  - **Pending:** PR #19 remains open; do not check off.\n"
                    "## Checklist\n"
                    "- [ ] Retry incomplete responses — fork PR #19\n"
                    "- [ ] Unrelated HTTP 500 retry issue #624\n"
                    "- [ ] General CI acceptance criterion\n"
                )
            }
        }
        self.open_prs = [
            {"number": 21, "title": "More upstream features", "body": "Part of #2"},
            {"number": 22, "title": "Unrelated", "body": "Related to #4"},
            {"number": 23, "title": "Dependent fix", "body": "Depends on PR #19"},
        ]
        self.comments: dict[int, list[dict[str, object]]] = {}
        self.posted: list[int] = []
        self.patches = 0
        self.closing_refs: set[int] = set()
        self.closed_pages: dict[int, list[dict[str, object]]] = {}

    def closing_issues(self, repository: str, number: int) -> set[int]:
        """Return simulated GitHub Development UI closing references."""
        assert repository == REPOSITORY
        return self.closing_refs.copy() if number == 19 else set()

    def pages(self, path: str) -> list[dict[str, object]]:
        """List open PRs or existing bot comments."""
        if path.endswith("/pulls?state=open"):
            return self.open_prs
        assert "/comments" in path
        number = int(path.split("/issues/")[1].split("/")[0])
        return self.comments.get(number, [])

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Capture the targeted update or bot comment."""
        if method == "GET" and path.startswith(
            f"/repos/{REPOSITORY}/pulls?state=closed&"
        ):
            page = int(path.split("page=")[-1])
            return self.closed_pages.get(page, [])
        if path == ISSUE_PATH:
            if method == "GET":
                return self.issues[2]
            if method == "PATCH":
                assert payload is not None
                self.issues[2]["body"] = str(payload["body"])
                self.patches += 1
                return self.issues[2]
        if method == "POST" and path.endswith("/comments"):
            number = int(path.split("/issues/")[1].split("/")[0])
            assert payload is not None
            self.comments.setdefault(number, []).append(
                {
                    "body": payload["body"],
                    "user": {"login": "github-actions[bot]"},
                }
            )
            self.posted.append(number)
            return {}
        raise AssertionError(f"Unexpected GitHub request: {method} {path}")


class MergeReferenceSyncTests(unittest.TestCase):
    """Verify link extraction, exact scoping, safe updates and idempotency."""

    def _workflow_config(self) -> dict[str, object]:
        """Parse workflow YAML without coercing its literal GitHub 'on' key."""
        workflow_path = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "sync-merged-references.yml"
        )
        with workflow_path.open(encoding="utf-8") as source:
            return yaml.load(source, Loader=yaml.BaseLoader)

    def _assert_secure_merge_workflow(self, workflow: dict[str, object]) -> None:
        """Reject extra privileges, triggers or an untrusted checkout target."""
        self.assertEqual(
            set(workflow),
            {"name", "on", "permissions", "concurrency", "jobs"},
        )
        self.assertEqual(
            workflow["on"],
            {
                "pull_request_target": {"types": ["closed"]},
                "schedule": [{"cron": "17 * * * *"}],
            },
        )
        self.assertEqual(
            workflow["permissions"],
            {"contents": "read", "issues": "write", "pull-requests": "write"},
        )
        self.assertEqual(
            workflow["concurrency"],
            {
                "group": "merged-reference-sync-${{ github.repository }}",
                "cancel-in-progress": "false",
                "queue": "max",
            },
        )
        self.assertEqual(set(workflow["jobs"]), {"synchronize"})
        job = workflow["jobs"]["synchronize"]
        self.assertEqual(set(job), {"if", "runs-on", "steps"})
        self.assertEqual(job["runs-on"], "ubuntu-latest")
        condition = " ".join(job["if"].split())
        self.assertEqual(
            condition,
            "(github.event_name == 'pull_request_target' && "
            "github.event.pull_request.merged == true && "
            "github.event.pull_request.base.ref == "
            "github.event.repository.default_branch) "
            "|| github.event_name == 'schedule'",
        )
        steps = job["steps"]
        self.assertEqual(len(steps), 3)
        self.assertEqual(
            steps[0],
            {
                "name": "Check out trusted default-branch code only",
                "uses": "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
                "with": {
                    "ref": "${{ github.event.repository.default_branch }}",
                    "persist-credentials": "false",
                },
            },
        )
        self.assertEqual(
            steps[1],
            {
                "name": "Set up Python 3.14",
                "uses": (
                    "actions/setup-python@"
                    "a309ff8b426b58ec0e2a45f0f869d46889d02405"
                ),
                "with": {"python-version": "3.14"},
            },
        )
        self.assertEqual(
            steps[2],
            {
                "name": "Synchronize linked issues and related open PRs",
                "env": {"GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"},
                "run": "python .github/scripts/sync_merge_links.py",
            },
        )

    def test_merge_workflow_pins_trusted_actions(self) -> None:
        """Validate parsed merge guards, queue and exact permissions."""
        self._assert_secure_merge_workflow(self._workflow_config())

    def test_merge_workflow_rejects_unsafe_mutations(self) -> None:
        """Reject additions or moves that string-only tests would miss."""
        for case in (
            "extra_trigger",
            "extra_privilege",
            "missing_guard",
            "wrong_checkout",
            "bracket_checkout",
            "missing_queue",
        ):
            with self.subTest(case=case):
                workflow = deepcopy(self._workflow_config())
                job = workflow["jobs"]["synchronize"]
                if case == "extra_trigger":
                    workflow["on"]["push"] = {"branches": ["main"]}
                elif case == "extra_privilege":
                    workflow["permissions"]["actions"] = "write"
                elif case == "missing_guard":
                    job["if"] = "github.event_name == 'pull_request_target'"
                elif case == "wrong_checkout":
                    job["steps"][0]["with"]["ref"] = "${{ github.head_ref }}"
                elif case == "bracket_checkout":
                    job["steps"][0]["with"]["ref"] = (
                        "${{ github.event.pull_request['head']['sha'] }}"
                    )
                else:
                    workflow["concurrency"]["queue"] = "single"
                with self.assertRaises(AssertionError):
                    self._assert_secure_merge_workflow(workflow)

    def test_all_workflows_pin_external_actions(self) -> None:
        """Enforce the repository-wide immutable action revision policy."""
        workflow_dir = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        paths = sorted(workflow_dir.glob("*.yml")) + sorted(
            workflow_dir.glob("*.yaml")
        )
        self.assertGreaterEqual(len(paths), 6)
        for path in paths:
            with self.subTest(workflow=path.name):
                with path.open(encoding="utf-8") as source:
                    data = yaml.load(source, Loader=yaml.BaseLoader)
                for job in data["jobs"].values():
                    refs = [job.get("uses")]
                    refs.extend(step.get("uses") for step in job.get("steps", []))
                    for reference in filter(None, refs):
                        self.assertRegex(reference, r"^[^@]+@[0-9a-f]{40}$")

    def test_recent_merge_reconciliation_recovers_three_lost_events(self) -> None:
        """Reconcile rapid merges and never repeat a completed bot summary."""
        api = _FakeGitHub()
        api.open_prs = []
        api.issues[2]["body"] = (
            "## Partial ports\n"
            + "".join(
                f"- **In progress (not merged):** [PR #{number}]\n"
                f"- [ ] Fork PR #{number} merged\n"
                for number in (19, 20, 21)
            )
            + "- [ ] Broad acceptance\n"
        )
        merged_pulls = []
        for number, hour in ((19, 9), (20, 10), (21, 11)):
            when = f"2026-11-17T{hour:02d}:00:00Z"
            merged_pulls.append(
                {
                    **_event()["pull_request"],
                    "number": number,
                    "merged_at": when,
                    "updated_at": when,
                }
            )
        api.closed_pages[1] = list(reversed(merged_pulls))
        now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        self.assertEqual(
            sync.reconcile_recent_merges(
                api, REPOSITORY, "main", current_time=now
            ),
            [19, 20, 21],
        )
        for number in (19, 20, 21):
            self.assertIn(f"- **Merged:** [PR #{number}]", api.issues[2]["body"])
            self.assertIn(f"- [x] Fork PR #{number} merged", api.issues[2]["body"])
        self.assertIn("- [ ] Broad acceptance", api.issues[2]["body"])
        original_posts = api.posted.copy()
        self.assertEqual(
            sync.reconcile_recent_merges(
                api, REPOSITORY, "main", current_time=now
            ),
            [],
        )
        self.assertEqual(api.posted, original_posts)

    def test_recent_reconciliation_ignores_old_and_unmerged_prs(self) -> None:
        """Do not replay merges outside the bounded recovery window."""
        api = _FakeGitHub()
        api.closed_pages[1] = [
            {
                **_event()["pull_request"],
                "updated_at": "2026-11-14T10:00:00Z",
                "merged_at": "2026-11-14T10:00:00Z",
            },
        ]
        now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        self.assertEqual(
            sync.reconcile_recent_merges(
                api, REPOSITORY, "main", current_time=now
            ),
            [],
        )
        self.assertEqual(api.posted, [])
        api.closed_pages[1] = [
            {
                **_event()["pull_request"],
                "updated_at": "2026-11-17T10:00:00Z",
                "merged_at": None,
            }
        ]
        self.assertEqual(
            sync.reconcile_recent_merges(
                api, REPOSITORY, "main", current_time=now
            ),
            [],
        )

    def test_recent_reconciliation_rejects_invalid_responses(self) -> None:
        """Fail explicitly rather than silently skipping unverifiable merges."""
        api = _FakeGitHub()
        api.closed_pages[1] = [
            {**_event()["pull_request"], "updated_at": "invalid-time"}
        ]
        now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "invalid timestamp"):
            sync.reconcile_recent_merges(
                api, REPOSITORY, "main", current_time=now
            )

    def test_issue_reference_parsing_skips_upstream_links_and_code(self) -> None:
        """Parse explicit repository issue references but not unrelated sources."""
        body = (
            "Part of #2, #3\n"
            "Related to HiDiHo01/ha-tplink-deco#4\n"
            "https://github.com/HiDiHo01/ha-tplink-deco/issues/5\n"
            "**Related to #6**\n"
            "- **Part of #7**\n"
            "> Related to #8\n"
            "https://github.com/amosyuen/ha-tplink-deco/issues/590\n"
            "https://github.com/amosyuen/ha-tplink-deco/pull/590\n"
            + chr(96) * 3
            + "\nPart of #600\n"
            + chr(96) * 3
            + "\n<!-- Related to #700 -->\n"
        )
        self.assertEqual(sync.issue_references(body, REPOSITORY), {2, 3, 4, 5, 6, 7, 8})

    def test_does_not_treat_pr_urls_as_issue_references(self) -> None:
        """A pull request URL is never an issue link, even with matching ID."""
        body = f"https://github.com/{REPOSITORY}/pull/19"
        self.assertEqual(sync.issue_references(body, REPOSITORY), set())

    def test_related_pr_reference_detection(self) -> None:
        """Find direct PR relationships without matching issue references."""
        self.assertTrue(
            sync.references_pull_request("Blocked by PR #19", REPOSITORY, 19)
        )
        self.assertTrue(
            sync.references_pull_request(
                f"https://github.com/{REPOSITORY}/pull/19",
                REPOSITORY,
                19,
            )
        )
        self.assertFalse(
            sync.references_pull_request(
                f"https://github.com/{REPOSITORY}/issues/19",
                REPOSITORY,
                19,
            )
        )
        self.assertFalse(sync.references_pull_request("Part of #19", REPOSITORY, 19))
        self.assertFalse(
            sync.references_pull_request("upstream PR #19", REPOSITORY, 19)
        )

    def test_only_explicitly_linked_checklist_is_completed(self) -> None:
        """Preserve global acceptance criteria and unrelated upstream work."""
        body = (
            "- [ ] Fix unstable clients in fork PR #19\n"
            "- [ ] Restore HTTP 500 handling #624\n"
            "- [ ] Port upstream PR #19 separately\n"
            "- [ ] Overall acceptance\n"
        )
        updated, completed = sync.update_issue_body(
            body, REPOSITORY, 19, MERGE_SHA, "2026-11-15"
        )
        self.assertEqual(completed, 1)
        self.assertIn("- [x] Fix unstable clients in fork PR #19", updated)
        self.assertIn("- [ ] Restore HTTP 500 handling #624", updated)
        self.assertIn("- [ ] Port upstream PR #19 separately", updated)
        self.assertIn("- [ ] Overall acceptance", updated)
        unchanged, again = sync.update_issue_body(
            updated, REPOSITORY, 19, MERGE_SHA, "2026-11-15"
        )
        self.assertEqual(again, 0)
        self.assertEqual(unchanged, updated)

    def test_pending_status_becomes_merge_status(self) -> None:
        """Remove stale PR-open wording after a confirmed merge."""
        body = (
            "- **In progress (not merged):** [PR #19]\n"
            "  - **Pending:** PR #19 remains open\n"
        )
        updated, completed = sync.update_issue_body(
            body, REPOSITORY, 19, MERGE_SHA, "2026-11-15"
        )
        self.assertEqual(completed, 0)
        self.assertIn("- **Merged:** [PR #19]", updated)
        self.assertIn("**Merge status:** PR #19 merged", updated)
        self.assertNotIn("**Pending:**", updated)

    def test_tracking_issue_workflow_status_updates_on_merge(self) -> None:
        """Recognize labeled in-progress entries, not only upstream ports."""
        body = (
            "- **In progress (workflow automation; not an upstream port):** "
            "[PR #20](https://github.com/HiDiHo01/ha-tplink-deco/pull/20)\n"
        )
        updated, completed = sync.update_issue_body(
            body, REPOSITORY, 20, MERGE_SHA, "2026-11-15"
        )
        self.assertEqual(completed, 0)
        self.assertIn("- **Merged:** [PR #20]", updated)
        self.assertNotIn("In progress (workflow", updated)

    def test_merge_updates_issue_and_only_related_open_prs(self) -> None:
        """Notify shared-issue PRs and direct dependencies without closing."""
        api = _FakeGitHub()
        issues, prs = sync.synchronize_merge(api, REPOSITORY, _event())

        self.assertEqual(issues, [2])
        self.assertEqual(prs, [21, 23])
        self.assertEqual(api.posted, [2, 21, 23, 19])
        self.assertNotIn(22, api.comments)
        self.assertEqual(api.patches, 1)
        issue_body = api.issues[2]["body"]
        self.assertIn("- [x] Retry incomplete responses", issue_body)
        self.assertIn("- [ ] General CI acceptance criterion", issue_body)
        self.assertIn("- **Merged:** [PR #19]", issue_body)

    def test_second_run_does_not_duplicate_issue_or_pr_updates(self) -> None:
        """Allow an operator to rerun the merge workflow safely."""
        api = _FakeGitHub()
        sync.synchronize_merge(api, REPOSITORY, _event())
        first_posts = api.posted.copy()
        sync.synchronize_merge(api, REPOSITORY, _event())

        self.assertEqual(api.posted, first_posts)
        self.assertEqual(api.patches, 1)

    def test_unmerged_or_nonclosed_event_does_nothing(self) -> None:
        """Never update issues just because a PR was closed without merging."""
        api = _FakeGitHub()
        self.assertEqual(
            sync.synchronize_merge(api, REPOSITORY, _event(merged=False)),
            ([], []),
        )
        self.assertEqual(api.posted, [])
        self.assertEqual(api.patches, 0)

    def test_rejects_merge_on_nondefault_branch(self) -> None:
        """Do not mutate work items for unsupported target branches."""
        api = _FakeGitHub()
        with self.assertRaises(ValueError):
            sync.synchronize_merge(api, REPOSITORY, _event(base="dev"))
        self.assertEqual(api.posted, [])

    def test_closing_issues_references_are_included(self) -> None:
        """Honor GitHub Development UI links that are absent from the PR body."""
        api = _FakeGitHub()
        api.closing_refs = {2}
        issues, _ = sync.synchronize_merge(
            api, REPOSITORY, _event(body="No textual issue references")
        )
        self.assertEqual(issues, [2])

    def test_invalid_repository_or_too_many_links_is_rejected(self) -> None:
        """Enforce same-repository scope and a finite edit boundary."""
        with self.assertRaises(ValueError):
            sync.issue_references("Part of #2", "../other/repo")
        with self.assertRaises(ValueError):
            sync.issue_references(
                "Related to " + " ".join(f"#{n}" for n in range(1, 30)),
                REPOSITORY,
            )

    def test_graphql_only_returns_same_repository_closing_issues(self) -> None:
        """Reject linked items in a different upstream repository."""

        class _GraphQLClient(sync.GitHubClient):
            """Replace network calls with a synthetic GraphQL response."""

            def request(
                self,
                method: str,
                path: str,
                payload: dict[str, object] | None = None,
            ) -> dict[str, object]:
                """Provide one local and one upstream issue reference."""
                self_outer.assertEqual((method, path), ("POST", "/graphql"))
                return {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "closingIssuesReferences": {
                                    "nodes": [
                                        {
                                            "number": 2,
                                            "repository": {"nameWithOwner": REPOSITORY},
                                        },
                                        {
                                            "number": 590,
                                            "repository": {
                                                "nameWithOwner": "amosyuen/ha-tplink-deco"
                                            },
                                        },
                                    ]
                                }
                            }
                        }
                    }
                }

        self_outer = self
        client = _GraphQLClient("synthetic-token")
        self.assertEqual(client.closing_issues(REPOSITORY, 19), {2})


if __name__ == "__main__":
    unittest.main()
