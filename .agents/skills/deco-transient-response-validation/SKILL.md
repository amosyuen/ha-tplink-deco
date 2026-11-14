---
name: deco-transient-response-validation
description: "Use when implementing or reviewing bounded Deco API retries for truncated responses, disconnects, client-state preservation, or optional performance polling, including upstream PR #590. Not for persistent HTTP 500 backoff or auth-expiry handling."
---

# Validate incomplete-response retries without losing Deco state

## Inspect current behavior

1. Read `AI_POLICY.md`, `AGENTS.md` and the
   [upstream-sync skill](../deco-upstream-sync/SKILL.md). Inspect the current
   API retry wrapper, HTTP request handler, both update coordinators,
   transport-authentication regressions and upstream PR #590.
2. Separate three failure classes: explicit authentication expiry (HTTP
   401/403 or known `-5002`), configured timeout retries, and retryable
   incomplete responses (`aiohttp.ClientPayloadError` and
   `aiohttp.ServerDisconnectedError`). A disconnect does **not** prove an
   existing session expired in this fork; do not copy upstream authentication
   invalidation from a different version.

## Implement safe recovery

3. Convert only incomplete-body/disconnected-server errors into a
   `TransientConnectionException` whose public message contains no raw
   response body, token, cookie, credentials or client MAC. Suppress the
   raw original exception context so automatic tracebacks cannot print
   sensitive response text; log only the exception class name.
   Keep connector failures and other HTTP/GraphQL/API errors separate.
4. Retry those failures through the existing API wrapper using the
   configured `timeout_error_retries` count, with a separate counter from
   timeout and relogin retries. Zero disables retries. Do not retry
   cancellation or add infinite loops.
5. For a failed per-Deco `client_list`, distinguish **no response** from a
   valid empty list. Preserve the last-known online/offline state,
   `last_activity` and `deco_mac` of clients whose Deco failed, while
   updating successful nodes and applying normal `consider_home` handling
   to clients absent from successful responses. Let unrelated API and
   authentication exceptions propagate.
6. For an optional failed performance request, retain existing CPU/memory
   readings while continuing a successful device-list update. Do not mark
   valid master/satellite devices offline merely because performance
   information was temporarily unavailable. Avoid changes to stable
   entity IDs, authentication setup, polling switches or configuration
   migration.

## Test and validate

7. Mock the actual aiohttp `ClientSession.post` request and response-body
   read separately; cover one successful retry, exhausted retries, zero
   retries, separate timeout budgets, existing sessions retained, explicit
   authentication errors, connector errors, and task cancellation.
8. Exercise the real coordinator update methods with a multi-node mesh:
   one failed node and one successful node, a genuinely empty success,
   all nodes failing, a client with old activity data, optional CPU/memory
   failure and propagation of other errors. Assert no raw upstream
   errors, credentials or identifiers appear in logs.
9. Update existing transport tests that assumed a disconnect always
   propagates immediately. Preserve their original authentication
   assertions and check `timeout_error_retries=0` separately.
10. Run both Python/Home Assistant matrix variants, pre-commit, HACS and
    Hassfest on the final PR head. Repair formatter changes without
    weakening CI. Distinguish real hardware testing from mocked tests.

## Handoff

11. Link the narrow port as `Part of #2`, never `Fixes #2`. As soon as
    the PR is opened, update issue #2 with the link, in-progress status,
    tested scope and limitations; refresh that record after material changes.
    Keep the corresponding checklist item unchecked until the PR is
    actually merged and its implementation verified on `main`. If closed
    without merging, record that result and leave the task open. HTTP 500
    exponential backoff and global client-list fallback remain separate
    upstream work.

Keep repository-wide rules in `AGENTS.md` and governing policy in
`AI_POLICY.md`.
