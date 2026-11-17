"""Regression tests for post-merge issue and related-PR synchronization."""

import importlib.util
from pathlib import Path
import re
import unittest

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

    def closing_issues(self, repository: str, number: int) -> set[int]:
        """Return simulated GitHub Development UI closing references."""
        assert repository == REPOSITORY
        assert number == 19
        return self.closing_refs.copy()

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

    def test_merge_workflow_pins_trusted_actions(self) -> None:
        """Pin action revisions and preserve safe merge-only execution."""
        workflow_path = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "sync-merged-references.yml"
        )
        workflow = workflow_path.read_text(encoding="utf-8")
        action_references = re.findall(
            r"^\s*uses:\s+([^\s#]+)", workflow, flags=re.MULTILINE
        )

        self.assertEqual(
            action_references,
            [
                "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
                "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
            ],
        )
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("github.event.pull_request.merged == true", workflow)
        self.assertIn(
            "github.event.pull_request.base.ref == "
            "github.event.repository.default_branch",
            workflow,
        )
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertNotIn("github.event.pull_request.head.", workflow)

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
