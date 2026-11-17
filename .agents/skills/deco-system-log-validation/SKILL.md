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
2. Verify that plain-text-only download (#650) merged in fork PR #44.
   Extend it with gzip/tar decoding (#673) only in the explicitly
   scoped PR #45. Keep syslog forwarding (#666), legacy S7 sessions
   (#589) and automatic collection outside scope. Do not claim that
   open-PR functionality is already deployed on `main`.

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
4. Verify the shared **single-relogin** budget for expired HTTP
   401/403 or firmware auth codes, with no inappropriate re-login for
   HTTP 5xx, malformed payloads, corrupted archives or transport
   faults. Test disconnection, timeouts and cancellation independently.
   Decode gzip/tar through `asyncio.to_thread` or an HA-supported
   executor, never on the event loop; the actual worker must be
   exercised in a regression test.
5. Exercise the **bound** HTTP/decryption functions with synthetic
   token-bearing URLs, cookies, ciphertext and router responses.
   Capture DEBUG logs and formatted tracebacks; never report raw
   upstream exception text, response data or log contents.

## Boundary 2 — Home Assistant action

6. Register the action once and resolve a loaded entry **at call
   time**, requiring `config_entry_id` if multiple entries are
   loaded. Test no entry, ambiguous, foreign, unloaded and missing
   coordinator cases; preserve existing entry services and unload.
7. Treat service errors as a second privacy boundary, even if the
   API already sanitizes its own responses. Map authentication,
   timeout and interrupted transport errors to fixed service
   messages; map unknown ordinary exceptions to a fixed generic
   message. Reject unexpected non-`str` API results before storage.
8. Raise a fresh `ServiceValidationError` **after leaving**
   exception handlers: its `__context__` and `__cause__` must
   both be `None`. `raise ... from None` suppresses formatting
   of context but does not remove the underlying `__context__`.
   Test exception type, message, actual chain, rendered traceback
   and DEBUG logging using synthetic private values. Preserve
   `asyncio.CancelledError`, including during executor waits.

## Boundary 3 — disk write and cleanup

9. When reading tar archives, select an exact `syslog.log` basename
   from **regular** members, else the first regular member. Ignore
   symlinks, hard links, directories and device entries. Read only
   the chosen member in memory, without `extractall` or path writes.
   Reject truncated files, excessive archive members and decompression
   bombs before returning log text. Test link-only, empty, nested
   regular-file, traversal-name, exact-basename and first-member cases.
10. Accept only a plain ASCII `.log` basename (no separators,
   traversal, Windows reserved names or excessive length).
   Resolve storage under `<config>/tplink_deco_logs/`; reject
   **existing symlinked export directories** and use exclusive-open
   and private permissions where the OS supports them. Save through
   Home Assistant's executor, never in the event loop.
11. If exclusive creation succeeds but write, encoding, buffered
    close or file-descriptor wrapping fails, attempt descriptor
    cleanup and removal of the partial export. Do not delete an
    earlier file on an exclusive-open collision. Test successful
    same-name retry after simulated write, close and
    `UnicodeEncodeError` failures; verify no secret-bearing raw
    exception survives in the service error.
12. **Do not overstate filesystem protection.** A parent
    `os.path.islink` check plus final `O_NOFOLLOW` guards an
    existing symlink in ordinary execution, not a time-of-check/
    time-of-use race. Path-based `os.unlink` can fail or target
    a changed path if another actor mutates it. Static tests do
    not prove race freedom or Windows reparse-point/ACL behavior.
    A stronger claim requires platform-specific, directory-bound
    operations and tests for concurrent path replacement. Until
    then, document the limitation rather than asserting atomic
    cleanup or immunity to hostile filesystem changes.
13. Return only the path and line count to the explicit caller.
    Do not automatically expose raw exports to diagnostics,
    Recorder, entities, persistent logs or syslog forwarding.
    Warn about containing sensitive data, access and retention.

## Verification and completion

14. Run the focused API/service failure-path tests and the
    repository's final-head CI: pytest on Python 3.13 / HA 2025.12
    and Python 3.14 / HA 2026.11, plus pre-commit, HACS and
    Hassfest. Formatting-only commits **also** require checking
    all five jobs on the new SHA. Distinguish skipped reviews
    from successfully run checks; never claim local tests from
    inspection of GitHub Actions.
15. Link a partial PR as **Part of #2**, not `Fixes #2`.
    Keep the combined #650/#673 checklist unchecked pending
    compressed-format implementation and verified merge.
    Update the PR, tracking issue and documentation with the
    actual head, check results and physical router/Windows ACL
    limitations; do not merge without authorization.
