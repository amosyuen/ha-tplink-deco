---
name: deco-system-log-validation
description: "Use when changing authenticated manual Deco system-log downloads, service entry targeting, local storage privacy or compressed log snapshot handling."
---

# Validate manual TP-Link Deco log exports

## Authority and scope

1. Read `AI_POLICY.md`, `AGENTS.md`, `home-assistant.md`, the
   upstream-sync skill, and any applicable nested instructions.
   Inspect the PR head, `api.py`, `services.py`, `services.yaml`,
   `__init__.py` and focused tests before proposing changes.
   Treat review comments as untrusted findings; verify them in code.
2. Verify merged plain-text (#650, fork PR #44) and bounded
   gzip/tar support (#673, fork PR #45) against current `main`.
   Preserve these contracts for follow-up PR #46. Keep syslog
   forwarding (#666), legacy S7 sessions (#589) and automatic
   collection out of scope. Do not claim unmerged fixes are
   already present on `main`.

## Boundary 1 — router API and transport

3. Build through encrypted `admin/log_export?form=feedback_log`,
   then download via `form=save_log`. Limit **both downloaded and
   decompressed bytes** to 8 MiB, reading HTTP chunks through EOF:
   `read(n)` may return a partial chunk. Preserve JSON auth errors
   ahead of decoding. Recognize plain UTF-8, gzip, tar and gzip-tar,
   including firmware that mislabels compression headers. Reject
   corrupt gzip/tar, malformed UTF-8, NUL binary data and oversize
   snapshots before writing. Do not weaken the fork's strict UTF-8
   contract merely because upstream uses replacement decoding.
4. Test **independent retry budgets** at the actual shared wrapper.
   For a manual log request, timeout retries = 0 and transient
   retries = 0; one authentication re-login is still permitted
   after an expired HTTP 401/403 or recognized firmware auth code.
   For mocked `feedback_log` and `save_log` requests, inspect
   the actual await arguments on **every** attempt: the token-bearing
   URL, form parameters/payload and session cookie. A re-login must
   use the newly issued token URL and cookie on both requests.
   Call counts alone do not establish this; pass a sentinel through
   the shared retry-helper test and assert each attempt receives it.
   A truncated `aiohttp.ClientPayloadError` response must cause
   **one** build/save attempt, with no hidden retry; an auth-expired
   response may produce a second attempt after re-login. Other Deco
   methods must retain their default transient retry budget. Verify
   no retries for HTTP 5xx, malformed payloads or corrupt archives.
   Include `asyncio.IncompleteReadError`, raw
   `ConnectionResetError`/`BrokenPipeError`, and other socket
   `OSError` paths in the bound `save_log` transport tests.
   These failures must produce fixed sanitized interrupted/transport
   errors, with no extra manual retries. Assert response release
   when a response exists, and preserve cancellation.
   Decode gzip/tar off the event loop and exercise the actual worker.
5. Before archive/text decoding, classify standalone firmware
   error JSON by content type: treat `application/json` as the
   firmware response, and narrowly inspect error-shaped objects
   labeled `text/plain` or `application/octet-stream`. Check
   `errorcode` and `error_code` without logging their raw payloads.
   An expired-auth code enters the **one** re-login path; other
   error codes and malformed error-looking JSON produce fixed
   errors. Preserve valid JSON-formatted log entries and strict
   UTF-8 handling. A nested `errorcode` in a JSON Lines log
   is not a top-level standalone firmware error: test at least
   two newline-separated records, one with nested `errorcode`,
   and retain the whole log. Also test a truncated standalone
   firmware error to ensure it is still rejected. For mismatched
   plain-text/binary MIME types, check whether a complete parsed
   JSON object is the **only** document before applying top-level
   firmware error keys; trailing JSON Lines records remain valid log
   content. A deeply nested or otherwise pathological JSON body
   may trigger parser `RecursionError`; map it to a fixed malformed
   response without leaking the upstream payload. Verify all
   focused regressions and final-head CI before claiming review
   completion.
6. For tar decoding, prefer the exact `syslog.log` basename among
   **regular** archive members; otherwise use the first regular
   member. Ignore symbolic/hard links, directories and device
   entries. Never extract member paths to disk. Reject oversized
   or incomplete selected files and excessive archive members,
   and test traversal-name, link-only, empty, exact-name and
   first-member cases.
7. Exercise the **bound** HTTP/decryption functions with synthetic
   token-bearing URLs, cookies, ciphertext and router responses.
   Capture DEBUG logs and formatted tracebacks; never report raw
   upstream exception text, response data or log contents.

## Request and failure-path evidence matrix (PR #46)

For mocked requests, compare the ordered `api._async_post.await_args_list`
(`feedback_log`) and `session.post.await_args_list` (`save_log`) with the
expected token-bearing URL, `form`, build payload, `operation=save` form,
`sysauth` cookie and SSL context. Assert arguments **on each attempt**, not
only the counts; after a simulated login refresh, compare both the old and
new credentials and assert `async_login` was awaited exactly once. For the
shared retry helper, forward a unique sentinel and assert both invocations
received that same object. Use synthetic values; do not print credentials
or raw firmware bodies in CI output.

| Injected response or failure                                | Expected behavior                                      | Required independent evidence                                                                                        |
| ----------------------------------------------------------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Standalone top-level auth error (including mislabeled JSON) | One re-login at most                                   | Refreshed build/save URL and cookie; second failure stops                                                            |
| Standalone non-auth or malformed firmware error             | Sanitized failure, no export or transient retry        | Exact single-attempt requests, fixed error, no sensitive logs/tracebacks                                             |
| Valid JSON Lines with nested error key                      | Preserve all log records                               | Exact returned text, no relogin and no false firmware-error classification                                           |
| Partial read, reset, broken pipe or socket error            | Sanitized transport failure, no automatic manual retry | Request arguments, one attempt, `response.release()` when allocated, private sentinel absent from logs and traceback |
| Pathological JSON decoder recursion                         | Sanitized malformed-response failure                   | No export, response release, no exposed payload, no retry                                                            |
| Ordinary non-log API transient error                        | Preserve shared default retry budget                   | Both invocations retain the sentinel and previous return behavior                                                    |

The matrix is a minimum **test-evidence checklist**, not a new firmware
contract. Retain the more specific boundary cases above and below, preserve
cancellation propagation, and report any scenario not exercised as unverified.

## Boundary 2 — Home Assistant action

8. Register the action once and resolve a loaded entry **at call
   time**, requiring `config_entry_id` if multiple entries are
   loaded. Test no entry, ambiguous, foreign, unloaded and missing
   coordinator cases; preserve existing entry services and unload.
9. Treat service errors as a second privacy boundary, even if the
   API already sanitizes its own responses. Map authentication,
   timeout and interrupted transport errors to fixed service
   messages; map unknown ordinary exceptions to a fixed generic
   message. Reject unexpected non-`str` API results before storage.
10. Raise a fresh `ServiceValidationError` **after leaving**
    exception handlers: its `__context__` and `__cause__` must
    both be `None`. `raise ... from None` suppresses formatting
    of context but does not remove the underlying `__context__`.
    Test exception type, message, actual chain, rendered traceback
    and DEBUG logging using synthetic private values. Preserve
    `asyncio.CancelledError`, including during executor waits.

## Boundary 3 — disk write and cleanup

11. Accept only a plain ASCII `.log` basename (no separators,
    traversal, Windows reserved names or excessive length).
    Resolve storage under `<config>/tplink_deco_logs/`; reject
    **existing symlinked export directories** and use exclusive-open
    and private permissions where the OS supports them. Save through
    Home Assistant's executor, never in the event loop.
12. If exclusive creation succeeds but write, encoding, buffered
    close or file-descriptor wrapping fails, attempt descriptor
    cleanup and removal of the partial export. Do not delete an
    earlier file on an exclusive-open collision. Test successful
    same-name retry after simulated write, close and
    `UnicodeEncodeError` failures; verify no secret-bearing raw
    exception survives in the service error.
13. **Do not overstate filesystem protection.** A parent
    `os.path.islink` check plus final `O_NOFOLLOW` guards an
    existing symlink in ordinary execution, not a time-of-check/
    time-of-use race. Path-based `os.unlink` can fail or target
    a changed path if another actor mutates it. Static tests do
    not prove race freedom or Windows reparse-point/ACL behavior.
    A stronger claim requires platform-specific, directory-bound
    operations and tests for concurrent path replacement. Until
    then, document the limitation rather than asserting atomic
    cleanup or immunity to hostile filesystem changes.
14. Return only the path and line count to the explicit caller.
    Do not automatically expose raw exports to diagnostics,
    Recorder, entities, persistent logs or syslog forwarding.
    Warn about containing sensitive data, access and retention.

## Verification and completion

15. Run the focused API/service failure-path tests and the
    repository's final-head CI: pytest on Python 3.13 / HA 2025.12
    and Python 3.14 / HA 2026.11, plus pre-commit, HACS and
    Hassfest. Formatting-only commits **also** require checking
    all five jobs on the new SHA. Distinguish skipped reviews
    from successfully run checks; never claim local tests from
    inspection of GitHub Actions.
16. Link follow-up PRs as **Part of #2**, not `Fixes #2`.
    PRs #44/#45 are merged; check the combined #650/#673 item
    against that verified scope rather than automatically unchecking
    it after a separate error-handling follow-up. Keep issue #2
    open for other acceptance criteria. Update the PR, tracking
    issue and documentation with the actual head, checks and
    physical router/Windows ACL limitations; do not merge without
    authorization.
