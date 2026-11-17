---
name: deco-system-log-validation
description: "Use when changing authenticated manual Deco system-log downloads, service entry targeting, local storage privacy or compressed log snapshot handling."
---

# Validate manual TP-Link Deco log exports

## Sources and scope

1. Read `AI_POLICY.md`, `AGENTS.md`, `home-assistant.md` and
   the upstream-sync skill. Inspect the actual `api.py`, `services.py`,
   `services.yaml`, `__init__.py` and tests before editing.
2. Keep explicit plain-text log download (upstream #650) distinct
   from compressed gzip/tar decoding (#673), always-on syslog
   forwarding (#666) and S7 legacy authentication (#589).
   Never present a partial port as full checklist parity.

## Transport and privacy

3. Validate the encrypted `admin/log_export?form=feedback_log`
   build response and the unencrypted `save_log` response, including
   incorrect content-type, non-dict payloads, truncated bodies,
   HTTP 401/403/5xx, firmware session expiration and cancellation.
4. Exercise **real bound** HTTP/decrypt methods with synthetic LuCI
   tokens, cookies and log secrets. Render exception tracebacks and
   capture DEBUG logs; secret payloads and URL tokens must be absent.
   Authentication refresh is bounded to one attempt. Do not retry
   malformed data or clear auth on generic transport errors.
5. Limit the downloaded bytes to 8 MiB before decoding. Plain-text
   UTF-8 is supported in this scope; gzip/tar requires a separate
   bounded, archive-safe decoder and tests before claiming #673.

## Service ownership and disk safety

6. Register the action once at integration setup, target a loaded
   entry by ID, and require `config_entry_id` when multiple entries
   are loaded. Test omitted, foreign, unloaded and removed entries,
   plus preservation of existing reboot/pause/resume handlers.
7. Reject directory separators, traversal, Windows reserved names,
   malformed or excessive filenames and non-`.log` extensions.
   Use an executor and exclusive-open file creation in the
   `tplink_deco_logs` configuration subdirectory; never overwrite
   an existing export. Avoid logging paths or raw system-log content.
8. Return path and line count only to the explicit caller; document
   the privacy sensitivity and retention responsibility of saved logs.
   Verify that diagnostics, entities and polling are unaffected.

## Completion

9. Run focused tests for service routing, log levels, bounded
   download, expired auth retry, malformed formats, cancellation,
   file collisions and privacy. Run the two required Python/HA
   pytest jobs (3.13/2025.12 and 3.14/2026.11) plus pre-commit,
   HACS and Hassfest on the **same final commit**.
10. Mark this PR `Part of #2`. Keep the combined #650/#673 issue
    checklist unchecked until gzip/tar parity is added and validated.
    Report all skipped, pending and failed checks accurately, with
    no claims of live router or Windows filesystem validation.
