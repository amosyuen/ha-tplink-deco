"""Safely synchronize linked issues and related PRs after a GitHub merge.

Run only trusted default-branch code. Issue, PR, and event bodies are data.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
import json
import logging
import os
import re
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

_LOGGER = logging.getLogger(__name__)
_MAX_PAGES = 10
_MAX_ISSUES = 25
_MAX_RELATED_PRS = 100
_BOT_LOGIN = "github-actions[bot]"
_API_ROOT = "https://api.github.com"


def _repository_parts(repository: str) -> tuple[str, str]:
    """Validate and split a same-repository API resource path."""
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise ValueError("GITHUB_REPOSITORY must be owner/repository")
    return repository.split("/", 1)


def _without_code(text: str) -> str:
    """Remove Markdown code fences and HTML comments before link detection."""
    fence = chr(96) * 3
    result = re.sub(re.escape(fence) + r".*?" + re.escape(fence), "", text, flags=re.S)
    return re.sub(r"<!--.*?-->", "", result, flags=re.S)


def issue_references(text: str, repository: str) -> set[int]:
    """Extract only explicit issue links belonging to this repository."""
    owner, name = _repository_parts(repository)
    source = _without_code(text)
    scoped = re.escape(f"{owner}/{name}")
    found = {
        int(value)
        for value in re.findall(
            rf"https://github\.com/{scoped}/issues/(\d+)\b",
            source,
            flags=re.I,
        )
    }
    found.update(
        int(value)
        for value in re.findall(rf"(?<![\w/]){scoped}#(\d+)\b", source, flags=re.I)
    )
    directive = re.compile(
        r"^\s*(?:[-*]\s+)?(?:part\s+of|related\s+to|"
        r"refs?|references?|fix(?:es|ed)?|clos(?:e|es|ed)|"
        r"resolv(?:e|es|ed)|tracks?)\s*:?\s+(.+)$",
        flags=re.I,
    )
    for line in source.splitlines():
        # PR descriptions frequently format these directives in bold or
        # as Markdown list items; formatting is not part of the reference.
        normalized = re.sub(r"^\s*(?:[-*]\s+|>\s+)*", "", line)
        match = directive.match(normalized.lstrip("*_"))
        if match:
            found.update(
                int(value)
                for value in re.findall(r"(?<![\w/])#(\d+)\b", match.group(1))
            )
    found.discard(0)
    if len(found) > _MAX_ISSUES:
        raise ValueError("Too many linked issues; refusing broad updates")
    return found


def references_pull_request(text: str, repository: str, number: int) -> bool:
    """Recognize direct references to a merged PR, not a similarly numbered issue."""
    owner, name = _repository_parts(repository)
    scoped = re.escape(f"{owner}/{name}")
    return bool(
        re.search(
            rf"https://github\.com/{scoped}/pull/{number}\b"
            rf"|(?<!upstream )\b(?:PR|pull request)\s*#{number}\b",
            _without_code(text),
            flags=re.I,
        )
    )


def update_issue_body(
    body: str, repository: str, pr_number: int, merge_sha: str, merged_date: str
) -> tuple[str, int]:
    """Complete explicit PR-linked checklist items and revise in-progress markers."""
    owner, name = _repository_parts(repository)
    scoped = re.escape(f"{owner}/{name}")
    pr_link = re.compile(
        rf"(?<!upstream )\bPR\s*#{pr_number}\b" rf"|https://github\.com/{scoped}/pull/{pr_number}\b",
        flags=re.I,
    )
    output: list[str] = []
    completed = 0
    for line in body.splitlines(keepends=True):
        if not pr_link.search(line):
            output.append(line)
            continue
        if re.match(r"^\s*-\s*\[ \]\s+", line):
            line = re.sub(r"^(\s*-\s*)\[ \]", r"\1[x]", line, count=1)
            completed += 1
        elif re.search(r"\*\*In progress(?:\s*\([^)]*\))?:\*\*", line):
            line = re.sub(
                r"\*\*In progress(?:\s*\([^)]*\))?:\*\*",
                "**Merged:**",
                line,
                count=1,
            )
        elif re.search(r"^\s*-\s*\*\*Pending:\*\*", line):
            indentation = re.match(r"^\s*", line).group(0)
            line = (
                f"{indentation}- **Merge status:** PR #{pr_number} merged "
                f"on {merged_date} (commit {merge_sha[:12]}); "
                "other tasks remain open." + ("\n" if line.endswith("\n") else "")
            )
        output.append(line)
    return "".join(output), completed


class GitHubClient:
    """Send scoped GitHub requests without logging API payloads or secrets."""

    def __init__(self, token: str) -> None:
        """Require a workflow token for repository writes."""
        if not token:
            raise ValueError("GITHUB_TOKEN must not be empty")
        self._token = token

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        """Call GitHub REST or GraphQL with a timeout and redacted HTTP errors."""
        request = Request(
            f"{_API_ROOT}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "deco-merge-sync",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(
                f"GitHub API {method} failed with HTTP {error.code}"
            ) from None

    def pages(self, path: str) -> list[dict[str, Any]]:
        """Read bounded pagination; fail rather than silently omit relationships."""
        result: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        for page_number in range(1, _MAX_PAGES + 1):
            page = self.request(
                "GET", f"{path}{separator}per_page=100&page={page_number}"
            )
            if not isinstance(page, list):
                raise ValueError("GitHub collection response must be a list")
            result.extend(page)
            if len(page) < 100:
                return result
        raise RuntimeError("GitHub pagination exceeded safe scan limit")

    def closing_issues(self, repository: str, pr_number: int) -> set[int]:
        """Also resolve GitHub Development UI closing-issue links via GraphQL."""
        owner, name = _repository_parts(repository)
        result = self.request(
            "POST",
            "/graphql",
            {
                "query": (
                    "query($owner:String!,$name:String!,$number:Int!){"
                    "repository(owner:$owner,name:$name){"
                    "pullRequest(number:$number){"
                    "closingIssuesReferences(first:100){"
                    "nodes{number repository{nameWithOwner}}}}}}"
                ),
                "variables": {"owner": owner, "name": name, "number": pr_number},
            },
        )
        if result.get("errors"):
            raise RuntimeError("GitHub linked-issue lookup failed")
        repo_data = (result.get("data") or {}).get("repository") or {}
        pr_data = repo_data.get("pullRequest") or {}
        nodes = (pr_data.get("closingIssuesReferences") or {}).get("nodes") or []
        return {
            node["number"]
            for node in nodes
            if node.get("repository", {}).get("nameWithOwner", "").lower()
            == repository.lower()
            and type(node.get("number")) is int
            and node["number"] > 0
        }


def _comment_once(
    client: GitHubClient, repository: str, number: int, marker: str, body: str
) -> None:
    """Prevent duplicate bot comments when the workflow is re-run."""
    comments = client.pages(f"/repos/{repository}/issues/{number}/comments")
    if any(
        comment.get("user", {}).get("login") == _BOT_LOGIN
        and marker in (comment.get("body") or "")
        for comment in comments
    ):
        return
    client.request(
        "POST",
        f"/repos/{repository}/issues/{number}/comments",
        {"body": f"{marker}\n{body}"},
    )


def synchronize_merge(
    client: GitHubClient, repository: str, event: dict[str, Any]
) -> tuple[list[int], list[int]]:
    """Sync same-repository issues, related open PRs and the merged PR summary."""
    _repository_parts(repository)
    pr = event.get("pull_request") or {}
    if event.get("action") != "closed" or pr.get("merged") is not True:
        return [], []
    base = pr.get("base") or {}
    if (base.get("repo") or {}).get("full_name") != repository or base.get("ref") != (
        event.get("repository") or {}
    ).get("default_branch"):
        raise ValueError("Merge must target this repository default branch")

    number = pr.get("number")
    merge_sha = pr.get("merge_commit_sha")
    merged_at = pr.get("merged_at")
    if (
        type(number) is not int
        or number < 1
        or not isinstance(merge_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", merge_sha) is None
        or not isinstance(merged_at, str)
    ):
        raise ValueError("Merged PR has an invalid number, SHA or timestamp")
    merged_date = (
        datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .date()
        .isoformat()
    )
    pr_url = f"https://github.com/{repository}/pull/{number}"
    issue_numbers = issue_references(
        f"{pr.get('title') or ''}\n{pr.get('body') or ''}", repository
    )
    issue_numbers.update(client.closing_issues(repository, number))
    if len(issue_numbers) > _MAX_ISSUES:
        raise ValueError("Too many linked issues; refusing broad updates")

    updated_issues: list[int] = []
    for issue_number in sorted(issue_numbers):
        path = f"/repos/{repository}/issues/{issue_number}"
        issue = client.request("GET", path)
        if "pull_request" in issue:
            continue
        old_body = issue.get("body") or ""
        new_body, count = update_issue_body(
            old_body, repository, number, merge_sha, merged_date
        )
        if old_body != new_body:
            client.request("PATCH", path, {"body": new_body})
        marker = f"<!-- deco-merge-sync:pr-{number}:issue-{issue_number} -->"
        _comment_once(
            client,
            repository,
            issue_number,
            marker,
            f"**Merged:** [PR #{number}]({pr_url}) on {merged_date} "
            f"(commit {merge_sha[:12]}). "
            f"{count} explicitly linked checklist item(s) completed; "
            "unrelated work remains open. This workflow does not close issues.",
        )
        updated_issues.append(issue_number)

    updated_prs: list[int] = []
    open_prs = client.pages(f"/repos/{repository}/pulls?state=open")
    for related in open_prs:
        related_number = related.get("number")
        if type(related_number) is not int or related_number == number:
            continue
        related_body = f"{related.get('title') or ''}\n{related.get('body') or ''}"
        shared = issue_references(related_body, repository) & issue_numbers
        if not shared and not references_pull_request(related_body, repository, number):
            continue
        if len(updated_prs) >= _MAX_RELATED_PRS:
            raise RuntimeError("Too many related PRs; refusing broad notices")
        links = ", ".join(
            f"[#{issue}](https://github.com/{repository}/issues/{issue})"
            for issue in sorted(shared)
        )
        shared_note = f"Shared issues: {links}. " if shared else ""
        marker = f"<!-- deco-merge-sync:pr-{number}:related-pr-{related_number} -->"
        _comment_once(
            client,
            repository,
            related_number,
            marker,
            f"**Related merge:** [PR #{number}]({pr_url}) merged on "
            f"{merged_date} (commit {merge_sha[:12]}). {shared_note}"
            "Review this PR against the current default branch if relevant. "
            "No PR branches are rebased, merged or closed by this workflow.",
        )
        updated_prs.append(related_number)

    marker = f"<!-- deco-merge-sync:summary-pr-{number} -->"
    issue_ids = ", ".join(f"#{value}" for value in updated_issues) or "none"
    pr_ids = ", ".join(f"#{value}" for value in updated_prs) or "none"
    _comment_once(
        client,
        repository,
        number,
        marker,
        f"**Merge sync completed.** Linked issues: {issue_ids}. "
        f"Related open PRs notified: {pr_ids}. "
        "Only checklist items explicitly linking to this merged PR were "
        "checked. No issues or PRs were automatically closed.",
    )
    _LOGGER.info(
        "Merged PR #%d: %d linked issues, %d related PRs",
        number,
        len(updated_issues),
        len(updated_prs),
    )
    return updated_issues, updated_prs


def main() -> None:
    """Read the trusted event file and synchronize referenced work items."""
    logging.basicConfig(level=logging.INFO)
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as event_file:
        event = json.load(event_file)
    synchronize_merge(
        GitHubClient(os.environ["GITHUB_TOKEN"]),
        os.environ["GITHUB_REPOSITORY"],
        event,
    )


if __name__ == "__main__":
    main()
