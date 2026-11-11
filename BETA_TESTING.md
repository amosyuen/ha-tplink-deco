# v3.15.0-beta.3 Combined Test Plan

This prerelease combines the changes from beta.1 and beta.2 with the
connection-class deprecation fix, the Slovak translation update from #653,
and the opt-in syslog forwarder from #660. It is not a stable release.
Syslog forwarding is disabled by default. Existing configurations do not
need to enable it.

## Automated Checks

- Run pre-commit, including the new untracked Python files before committing.
- Run `python -m pytest --no-cov tests/` in the supported HA test environment.
- Require both CI test jobs (HA 2025.12/Python 3.13 and HA 2026.11/Python 3.14).
- Require HACS, Hassfest, pre-commit and `git diff --check` to pass.

Passing tests do not replace live testing on a Deco mesh.

## Home Assistant Checks

1. Back up Home Assistant and record the existing Deco entity IDs and settings.
2. Install this prerelease, restart Home Assistant and leave syslog disabled.
3. Check node status, connected clients, throughput, WiFi and mobile-data
   sensors where supported. Existing entities should retain their IDs.
4. Toggle polling off and on. Reload the integration and restart Home Assistant;
   verify the switch and polling still work. If multiple entries are available,
   verify their polling switches operate independently.
5. Run `tplink_deco.download_system_log` for the intended config entry. Verify
   the response contains a log, and check that other entries are not selected.
   Legacy encrypted firmware does not support this action.
6. Reload, disable and re-enable the integration. Check for task exceptions,
   requests using a logged-out session, and missing entities. Do not expect
   these operations to create new entities with different IDs.
7. Confirm that tplink_deco no longer logs the CONN_CLASS_CLOUD_POLL warning.
   Warnings from other integrations are outside this test.
8. If using Slovak, check the update interval labels in setup and options.

## Live Syslog Checks

Use a trusted local receiver: UDP and TCP syslog are not encrypted and can
contain client names, MAC addresses and IP addresses. UDP is best effort;
successful sending is not proof of delivery. TCP retries can duplicate lines
if a connection fails after partially delivering a batch.

1. Enable forwarding with the receiver host and port. Keep the default
   300-second interval initially and select a log level that produces entries.
2. Verify the first successful poll records the current log without sending
   old history. Generate a normal log event and wait for a subsequent poll.
3. Confirm new messages arrive with the expected source, severity and time.
   Verify unchanged logs are not repeatedly forwarded.
4. Repeat with both UDP and TCP, on the matching receiver port. Changing
   protocol reloads the entry; allow the forwarder to resume.
5. Stop the receiver temporarily and restore it. Check that Home Assistant
   stays responsive and forwarding recovers on a subsequent poll. UDP may
   not report a stopped receiver; do not expect guaranteed retry or delivery.
6. Pause polling and confirm no new syslog downloads start. An already-running
   request may finish. Resume and verify forwarding continues.
7. Restart Home Assistant while forwarding is enabled. Where the Deco retains
   the log and saved tail, new lines from the gap should be forwarded.
8. Disable forwarding, then reload and restart. Confirm no forwarding occurs
   and normal sensors and polling still work.
9. Throughout the test, monitor client updates and mesh stability. System-log
   downloads share the Deco API session and can delay other requests. Do not
   lower the interval while investigating a slow or unstable mesh.
10. On unsupported legacy encrypted firmware, expect one warning and no more
    forwarding attempts until the integration is reloaded.

## Report Results

Record the beta version, Home Assistant version, Deco models and firmware,
number of config entries, tested syslog protocols and duration. Include which
checks passed or failed and any new HA errors. Download diagnostics after a
failure; review diagnostics and logs before sharing them publicly.

Changes from #653 are by @misa1515. The #660 implementation is by @alunduil,
with parsing and tail-matching contributions from @gappleby via #607. Preserve
their attribution when committing and publishing the combined work.
