# TP-Link Deco

[![GitHub Release](https://img.shields.io/github/v/release/amosyuen/ha-tplink-deco?style=for-the-badge)](https://github.com/amosyuen/ha-tplink-deco/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/amosyuen/ha-tplink-deco?style=for-the-badge)](https://github.com/amosyuen/ha-tplink-deco/commits/main)
[![License](https://img.shields.io/github/license/amosyuen/ha-tplink-deco?style=for-the-badge)](LICENSE)

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=for-the-badge)](https://github.com/pre-commit/pre-commit)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge)](https://github.com/psf/black)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz)

[![Maintained](https://img.shields.io/badge/maintained-yes-brightgreen?style=for-the-badge)]()
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.4%2B-blue?style=for-the-badge)](https://www.home-assistant.io/)

---

## 🚀 Overview

This integration provides local polling control and diagnostics for TP-Link Deco systems within Home Assistant.

---

## ✨ Features

### Diagnostics

- CPU usage (raw + smoothed)
- Memory usage (raw + smoothed)
- Backhaul and network diagnostics

**Deco diagnostic and coordinator-health sensors are disabled by default.**
In Home Assistant, open **Settings → Devices & services → TP-Link Deco →
Devices**, select a Deco, show disabled entities, and enable the
diagnostics you want.

Per-Deco diagnostics are created only when the firmware has supplied a
nonempty value for that field, even if that first happens on a later refresh.
Unsupported fields are not exposed as placeholder sensors. Network-wide
throughput totals require a known master Deco, while the per-Deco
**Connected clients** sensor requires a successful client-list poll for that
node.

### Optional mobile WAN data usage (upstream #631)

On supported Deco 4G/5G router models, a **Mobile data usage** sensor
reports the router's read-only `mobile_cpe.data_usage` counter in KiB,
with a five-minute refresh. The integration creates this sensor only
after the firmware returns a valid counter (including zero). Firmware
without the capability keeps all existing entities without an empty
mobile sensor. The first check runs in the background after platforms load.

The mobile sensor is associated with the master Deco and has a stable
MAC-based identity. If the master changes, previous usage becomes
unavailable until the new master's successful refresh, including during
in-flight requests. Normal Deco and client polling is independent of
mobile endpoint failures. The value can be sensitive usage information
in Home Assistant Recorder/history and external exports; integration
diagnostics expose only anonymous support and health status, not the
counter, tokens or router response. Live 4G/5G hardware compatibility
is not yet verified.

### Optional read-only WiFi status (upstream #627)

For firmware exposing the local `wlan` endpoint, the integration provides
read-only Main, Guest and IoT WiFi binary sensors. Only networks confirmed by
the firmware are created; Main WiFi is disabled by default. If the master
Deco changes, the former master's WiFi sensors become unavailable
without losing their Home Assistant entity identities. The sensors use
the regular polling interval, link to the master Deco, and start without
delaying existing Deco and client discovery.

If WiFi status cannot be read, existing Deco and client entities continue
normally. After repeated wireless failures, retries are deferred by up to
five minutes. Authentication expiration preserves a single re-login retry,
while malformed response data and HTTP errors are reported without revealing
session information or private WiFi settings. The integration does not change
wireless settings or expose WiFi passwords, PSKs or raw wireless data.

**WiFi network names (SSIDs) are hidden by default.** To show them, explicitly
enable **Show WiFi network names on the WiFi status sensors** in the integration
options. The selected entry's existing Main, Guest and IoT WiFi binary sensors
then provide an `ssid` attribute if all bands share a name, or
`ssid_band2_4`, `ssid_band5_1` and similar attributes when bands differ.
Unsupported or missing names are omitted. No additional entities are created.

**Privacy:** SSIDs can reveal personal or location-related information to
users and automations with access to entity states, history and exports.
Only enable this if that visibility is acceptable. Disabling the option
removes names from new coordinator state after reload; existing external
history, notifications and backups are not erased. Router passwords, PSKs,
tokens and raw WLAN responses are never exposed through these attributes.

### Optional client device linking

**Link client trackers to devices by MAC address** is enabled by default,
preserving Home Assistant's existing automatic device matching. To prevent
client trackers from joining devices exposed by other integrations, disable
the option in the Deco integration options.

When disabled, each client tracker keeps its existing entity ID and MAC-based
unique ID, while its MAC is available as a state attribute instead of the
scanner's automatic matching field. Physical Deco trackers are unaffected.
Previously linked Home Assistant devices are **not** automatically unlinked;
legacy client-only device entries belonging exclusively to this Deco
configuration entry may be removed manually. Shared or Deco devices remain
protected. The setting can be changed per Deco integration entry.

### CPU / Memory sensors

Two types of sensors are available:

- **Raw** → direct values from the Deco (real-time, can fluctuate)
- **Smoothed** → averaged values over time (stable, ideal for dashboards)

**Use raw for:**

- debugging
- real-time monitoring

**Use smoothed for:**

- dashboards
- automations
- trend analysis

---

### Polling Control

#### Runtime control

- Pause / resume polling:

  - `tplink_deco.pause_polling`
  - `tplink_deco.resume_polling`

- Switch entity:
  - `switch.deco_polling`

> **Compatibility note:** When the polling switch is migrated to a
> per-configuration-entry unique ID, its Home Assistant entity ID is retained
> on upgrade. **Downgrading to a version that still uses the legacy global
> `tplink_deco_polling` unique ID is not supported after this migration.**
> An older version can register a second switch instead of reusing the
> migrated entity, disrupting existing automations. Keep an entity-registry
> backup before upgrading and use the new integration version thereafter.

---

#### Polling interval control

Adjustable polling interval:

- 10 sec
- 30 sec (default)
- 60 sec
- 120 sec

Configurable:

- during setup
- via Home Assistant UI (select entity)

---

#### Benefits

- Reduces API load
- Prevents session conflicts
- Improves stability
- Better control over performance

---

## 📝 Changelog

### Unreleased — upstream sync (issue #2)

- Recover client tracking on firmware where a per-node query returns
  HTTP 5xx by trying one global client-list query. Live clients from
  that response are temporarily assigned to the master because the
  global response does not identify individual Deco nodes. Keep global
  polling available during the capped per-node backoff, and restore
  actual node associations after per-node requests recover. Failed
  global queries retain cached clients and healthy peer results.

- Limit simultaneous per-Deco client-list requests to two per mesh and
  avoid repeated timeouts for each node. A timeout on one node keeps its
  last-known client state while successful peers continue updating.
  The global fallback above is a separate subsequent addition.

- Add an independent Deco status polling interval. Choose 0 to fetch
  the mesh inventory only at startup, or an interval of at least ten
  seconds. Client and CPU/memory polling continue at the existing main
  interval. A new **Refresh Deco status** button refreshes inventory
  manually, including while automatic status polling is disabled.
  Older configurations keep their previous polling behavior.

- Tolerate numeric strings returned by older Deco firmware for
  client download/upload rates and master CPU/memory fractions.
  Invalid client rates contribute zero to live network/per-Deco
  throughput totals; malformed optional CPU/memory values preserve
  the last valid reading. Legacy S7 encrypted-session authentication
  is not included in this compatibility update.

- Add a privacy-safe Home Assistant config-entry diagnostics download with
  coordinator last-success timestamps, response times, failure/timeout
  counters, sanitized error types, and aggregate Deco/client counts.
  It never includes passwords, tokens, MAC/IP addresses, client names,
  SSIDs or raw API payloads, and performs no additional router requests.

- Add eight opt-in coordinator health diagnostics on the master Deco:
  successful update timestamps, API response times, last error types,
  client timeout count and current per-node query mode. They do not
  trigger extra Deco API requests or expose raw responses, credentials
  or device/client lists.

- Run the first optional client-list refresh as a config-entry-owned
  background task after Home Assistant platforms are initialized, instead
  of delaying entry setup on client polling. The initial Deco inventory
  still loads first to preserve restored-device identity and all existing
  client, sensor, polling and service behavior.

- Defer connected-client count sensors until their Deco has returned a valid
  client list; keep unavailable peers from displaying premature zero counts.
  Count only clients reported as online (including the existing
  `consider_home` grace period), without changing sensor unique IDs or
  historical client trackers.

- Register newly discovered client trackers after the client coordinator
  commits its refreshed state. This avoids missing a client when the early
  discovery signal observes stale data; existing MAC-based IDs, per-entry
  isolation, opt-out device linking and polling behavior are unchanged.

- Restore previously known client trackers even when Home Assistant saved
  their state as unavailable without a `device_type` attribute. Support
  both legacy and registry-aware Home Assistant restore-state APIs,
  ignore disabled entries, identify offline Deco nodes from matching
  device-registry identifiers, and reconcile remaining provisional clients
  with Decos confirmed by the initial refresh. Existing MAC-based entity
  IDs, known client history and per-entry separation are preserved.

- Discover the full existing set of Deco device trackers, binary sensors
  and per-node throughput/diagnostic sensors when an additional Deco
  node appears while Home Assistant is running. Commit the refreshed
  inventory before notifying entity platforms, avoiding missing entities
  until a later refresh. Existing MAC identities, offline nodes, master
  relationships, network totals and polling controls remain unchanged.

- Add optional MAC-based device linking for client trackers (default on),
  preserving existing tracker unique IDs and physical Deco device identities.
  Disabling the option prevents future automatic matching while allowing
  safe manual cleanup of old client-only device entries. Existing
  cross-integration device links are not changed automatically.

- Scope polling-switch unique IDs to each Home Assistant configuration
  entry to prevent collisions when multiple Deco networks are added.
  Existing switches migrate in place to retain their current entity ID
  (such as `switch.deco_polling`), customizations and automations;
  the visible switch name, master-device link and pause/resume behavior
  remain unchanged. Other switches and entities are unaffected.

- Reduce repeated Deco client-list HTTP 5xx errors using a non-blocking
  exponential polling delay (30, 60, 120, 240, then at most 300 seconds).
  Keep known clients and the authenticated session through temporary
  server failures while still accepting successful replies from other
  Deco nodes; reset the delay after full recovery. Existing scan intervals,
  authentication-expiry rules and entity IDs stay unchanged.

- Retry truncated Deco responses and unexpected server disconnects up to the configured timeout-retry count without clearing a valid login. If one node's client list remains unavailable, retain its previously known clients while updating successful nodes. Keep cached CPU and memory readings when optional performance polling fails. HTTP errors and authentication expiry still surface normally.

- Link satellite Decos to their master using `via_device_id` in Home Assistant 2026.8+, with a legacy `via_device` fallback on older supported releases. Keep existing MAC-based device identifiers and entity unique IDs.

- Recover from Deco API error code `-5002` on authenticated LuCI requests by clearing the expired session and using the existing one-time re-login retry, including for reboot commands. Keep login errors and generic HTTP failures distinct.

- After Home Assistant successfully unloads Deco platforms, cancel coordinator refreshes, unsubscribe callbacks and release the router admin session. A failed platform unload leaves the running integration and session intact.

- Detect router HTTP 307 redirects to HTTPS on the same host and switch subsequent API requests to the redirected HTTPS endpoint and port. This avoids session-cookie loss on redirects with newer aiohttp while leaving cross-host redirects untouched.

- Keep an existing Deco session after temporary disconnections or connection failures; a later successful poll reuses it without logging in again. Actual HTTP 401/403 responses still clear expired authentication.

- Add the Home Assistant Marketplace router category and fork-specific install/support links; document Marketplace (2026.11+), legacy HACS and manual installation without duplicate instructions.

- Await Home Assistant platform initialization during config-entry setup so setup cannot complete before platforms are ready and forwarding failures are reported.

- Defer network-wide Total Down/Up sensors until the master Deco is available, then register them once without changing their existing MAC-based unique IDs. Satellite sensors remain available when no master is detected.

- Expose optional wireless-backhaul BSSIDs (`backhaul_bssid_band2_4` and `backhaul_bssid_band5`) as read-only Deco tracker attributes, separately from the existing access-point BSSIDs. Absent firmware fields remain `None`; no device or entity identifiers change.

- Expose readable client names (including configured prefixes and postfixes) as tracker hostnames, so Home Assistant can name client devices instead of showing only their MAC addresses. Existing MAC identity and user-defined names are preserved.

- Fix `reboot_deco` when a device has multiple registry identifiers; reject missing Deco MACs cleanly without calling the router.

- Exclude offline clients' last-reported rates from network-wide and per-Deco upload/download sensors.

- Remove the deprecated config-flow connection class; keep `local_polling` metadata in the manifest.

- Preserve plain-text and UTF-8 encoded Deco/client names, including names from legacy firmware.
- Fall back to the firmware nickname or MAC address when custom Deco nicknames are missing.
- Fix config/options polling interval selection: 10, 30, 60, or 120 seconds.
- Store the selected interval as an integer for compatibility with existing polling controls.
- Avoid logging client names from decode failures; existing MAC-based identifiers remain unchanged.

### v3.7.4

- Added CPU usage sensors (raw and smoothed)
- Added memory usage sensors (raw and smoothed)
- Added configurable polling interval (10 / 30 / 60 / 120 seconds)
- Added select entity for runtime polling control

---

### v3.7.3

- Fix for Home Assistant 2026.4 compatibility
- Added diagnostic entities (backhaul speed, max speed)
- Added polling control services and switch
- Improved API stability

---

## 🔧 Services

- `tplink_deco.pause_polling`
- `tplink_deco.resume_polling`
- `tplink_deco.reboot_deco`
- `tplink_deco.download_system_log` (manual; merged in PR #44)

---

## 🔌 Entities

### Polling

- `switch.deco_polling`
- `select.polling_interval`

### Diagnostics

- CPU usage (raw + smoothed)
- Memory usage (raw + smoothed)

---

# TP-Link Deco

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![pre-commit][pre-commit-shield]][pre-commit]
[![Black][black-shield]][black]

[![hacs][hacsbadge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[![Community Forum][forum-shield]][forum]

## Functionality

This integration is a local polling integration that logs into the admin web UI for TP-Link Deco routers. Currently the only feature implemented is device trackers for active devices.

### Device Trackers

Device trackers are added for both decos and clients. The device tracker state marks whether the device is connected to the deco. If a device is not present, the previous values for attributes are saved except for `down_kilobytes_per_s` and `up_kilobytes_per_s`.

#### Common Attributes

| Attribute       | Example Values (comma separated) |
| --------------- | -------------------------------- |
| mac             | 1A-B2-C3-4D-56-EF                |
| ip_address      | 192.168.0.100                    |
| device_type     | client, deco                     |
| connection_type | wired, band5, band2_4            |

#### Client Attributes

| Attribute            | Example Values (comma separated) |
| -------------------- | -------------------------------- |
| interface            | main, guest                      |
| down_kilobytes_per_s | 10.25                            |
| up_kilobytes_per_s   | 11.75                            |
| deco_device          | living_room                      |
| deco_mac             | 1A-B2-C3-4D-56-EF                |

#### Deco Attributes

| Attribute       | Example Values (comma separated) |
| --------------- | -------------------------------- |
| hw_version      | 2.0                              |
| sw_version      | 1.5.1 Build 20210204 Rel. 50164  |
| device_model    | x60                              |
| internet_online | false, true                      |
| master          | false, true                      |
| bssid_band2_4   | A1:B2:C3:D4:E5:F6                |
| bssid_band5     | A1:B2:C3:D4:E5:F6                |
| signal_band2_4  | 3                                |
| signal_band2_4  | 4                                |
| deco_device     | living_room                      |
| deco_mac        | 1A-B2-C3-4D-56-EF                |

Note: `deco_device` and `deco_mac` will only be set for non-master decos.

### Devices

A device is created for each deco. Each device contains the device_tracker entities for itself and any clients connected to it. Non-master deco devices will indicate that they are connected via the master deco device.

### Services

#### Reboot Deco Service

Reboots the specified decos. Example yaml:

```yaml
service: tplink_deco.reboot_deco
target:
  device_id:
    - ef41562be18e5e3057e232ffb26de9bb
    - d7f96b1f312d83f195b35ecdfbb3b02b
```

#### Download system log (upstream #650; merged PR #44)

The optional `tplink_deco.download_system_log` action downloads a snapshot
only when explicitly called. It writes a **new**, plain-text UTF-8 file
to `<config>/tplink_deco_logs/` and returns its path and line count.
An existing file is never overwritten. Snapshots are limited to **8 MiB**.

```yaml
action: tplink_deco.download_system_log
data:
  config_entry_id: YOUR_DECO_CONFIG_ENTRY_ID
  filename: deco-example.log
  log_level: WARNING
response_variable: log_export
```

The entry ID is optional only when exactly one Deco entry is loaded.
The filename may be omitted for a timestamped default; custom names
must be simple ASCII `.log` basenames. The allowed severity values
are `ALERT`, `CRITICAL`, `ERROR`, `WARNING`, `NOTICE`, `INFO`,
`DEBUG` and `ALL` (default).

**Privacy:** Deco system logs can contain device names, addresses,
other network details and secrets. The action does not include raw
logs in Home Assistant diagnostics or integration logs, but the saved
file retains the sensitive original text. Restrict access to the
output directory, do not share or sync its contents, and delete
exports when they are no longer needed. File access permissions
depend on the underlying operating system and filesystem. Existing
symbolic links at the export directory are rejected, but concurrent
filesystem changes and Windows reparse-point/ACL handling have
**not** been independently verified; do not place the Home Assistant
configuration directory under untrusted write access. A failed
write triggers best-effort removal of a partial export, which may
still need manual cleanup if the filesystem prevents deletion.

The manual plain-text action merged in PR #44 and gzip/tar support
merged in PR #45. These provide transparent gzip, tar and
gzip-wrapped tar snapshot decoding (upstream #673), even where the
firmware labels a compressed
response `text/plain`. Archives are processed in memory and never
extracted to arbitrary paths. The exact regular `syslog.log` member
is preferred, otherwise the first regular member; links are ignored.
Both the downloaded bytes and expanded data have an 8 MiB limit,
and archive decoding runs outside Home Assistant's event loop.
Invalid archives, oversized expansion and invalid UTF-8 are rejected
without writing an export. The action still writes only a plain-text
`.log` file. Unlike upstream's replacement-byte strategy, the fork
retains strict UTF-8 validation to avoid silent loss of log data.

Follow-up PR #46 adds detection of router authentication/error JSON
mislabeled as text/plain or binary; such errors are never written as
log content. After PR #46 merges, incomplete manual log downloads return a
fixed connection failure without an extra transient retry, while
ordinary Deco API retry defaults remain unchanged. Expired router
authentication still permits one re-login/retry; a timeout or
truncated response does not. The PR #46 fix is **not yet on
`main`**.

Legacy S7 sessions and syslog forwarding (#666) remain separate.
Physical router behavior and Windows filesystem permission behavior
have not been independently verified.

{% if not installed %}

<!-- ha-marketplace:exclude-start -->

## Installation

### Marketplace (Home Assistant 2026.11 and newer)

Open **Settings > Marketplace > Add from link** and enter the fork's repository URL:
`https://github.com/HiDiHo01/ha-tplink-deco`.

### HACS (Home Assistant 2026.10 and earlier)

In **HACS > Integrations**, add `https://github.com/HiDiHo01/ha-tplink-deco`
as a custom repository of type **Integration**, then install it.

The repository button works in both older HACS and the new Marketplace:

[![Open this TP-Link Deco fork in HACS or Home Assistant Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HiDiHo01&repository=ha-tplink-deco&category=integration)

### Manual

1. Using the tool of choice open the directory (folder) for your [HA configuration](https://www.home-assistant.io/docs/configuration/) (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `tplink_deco`.
4. Download _all_ the files from the `custom_components/tplink_deco/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant

### Local regression tests

Install test dependencies in an isolated Python 3.14 environment. See
[the local test setup](CONTRIBUTING.md#local-regression-tests-python-314)
for Windows PowerShell commands and the Home Assistant version requirement.

<!-- ha-marketplace:exclude-end -->

{% endif %}

## Configuration (Important! Please Read)

Config is done in the HA integrations UI.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tplink_deco)

### Host

The IP address of the main deco which you visit in the browser to see the web admin page. Example: `http://192.168.0.1`. Some decos use https, so if you have trouble connection, try using `https` e.g. `https://192.168.0.1`.

### Login Credentials

The login credentials **MUST** be the deco **owner** credentials and the username should be left as **admin**. Manager credentials will **NOT** work.

Also whenever the owner logs in, all other sessions for the owner will be logged out. So if you log in with the owner credentials in the mobile app, it will cause the integration to be logged out, sometimes resulting in 403 errors. Since the integration has built in retry on auth errors, the integration will re-login, but that will logout your mobile app login session.

Recommend that you create a separate manager account with full permissions to manage the router manually in the mobile app and use the owner credentials only for this integration. If you need to use the owner account to do some manual management, recommend disabling this integration temporarily. Steps to create a manager account:

1. Log out of the deco app
2. Sign up for a new account with a different email address
3. Log out of the deco app
4. Login to original admin account
5. Go to the "More" section and look for "Managers"
6. Add the email address of the new account
7. Log out of the app
8. Login using the new manager account you've just created

### Timeout Secounds

How many seconds to wait until request times out. You can increase this if you get a lot of timeout errors from your router.

Note: The router also has its own timeout so increasing this may not help.

### Timeout Error Retry Count

How many times to retry timeout errors for one request. You can increase this if you get a lot of timeout errors from your router.

### Verify SSL Certificate

Turn off this config option if your browser gives you a warning that the SSL certificate is self-signed when you visit the router host IP in your browser.

### Client Name Prefix

Prefix to prepend to client name. Example: Value of "Client" for "Laptop" client will result in "Client Laptop".

### Client Name Postfix

Postfix to append to client name. Example: Value of "Client" for "Laptop" client will result in "Laptop Client".

### Deco Name Prefix

Prefix to prepend to deco name. Example: Value of "Deco" for "Living Room" deco will result in "Deco Living Room".

### Deco Name Postfix

Postfix to append to deco name. Example: Value of "Deco" for "Living Room" deco will result in "Living Room Deco".

### Disable new entities

If you prefer new entities to be disabled by default:

1. In the Home Assistant (HA) UI go to "Configuration"
2. Click "Integrations"
3. Click the three dots in the bottom right corner fo the TP-Link Deco integration
4. Click "System options"
5. Disable "Enable newly added entities"

## Notify on new entities

You can get notified by new entities by listening to the `entity_registry_updated` event. Here's an example automation:

```yaml
- alias: Notify New Wifi Device
  mode: parallel
  max: 100
  trigger:
    - platform: event
      event_type: entity_registry_updated
      event_data:
        action: create
  variables:
    id: "{{ trigger.event.data.entity_id }}"
  condition:
    - condition: template
      value_template: "{{ id.split('.')[0] == 'device_tracker' }}"
    - condition: template
      value_template: "{{ id in integration_entities('tplink_deco') }}"
  action:
    - alias: Wait a little while to make sure the entity has updated with new state
      wait_template: "{{ states(id) not in ['unknown', 'unavailable'] }}"
      timeout:
        minutes: 1
    - service: notify.mobile_app_phone
      data:
        title: "{{ state_attr(id, 'friendly_name') or id }} connected to WiFi"
        message: >-
          {{ id }} connected to
          {{ state_attr(id, 'interface') }}
          {{
            state_attr(id, 'connection_type')
              | regex_replace('band', '')
              | regex_replace('_', '.')
              | regex_replace('$', 'G')
          }}
          through
          {{ state_attr(id, 'deco_device') }}
        data:
          group: wifi-new-device
          clickAction: "entityId:{{ id }}"
```

Resulting notification looks like:

```yaml
title: "Amos Phone connected to WiFi"
message: "device_tracker.amos_phone_wifi connected to main 5G through Guest Room"
```

## Tested Devices

- Deco M4
- Deco M5
- Deco M9 Plus
- Deco P7
- Deco P9
- Deco PX50
- Deco S4
- Deco X20
- Deco X50
- Deco X60
- Deco X68
- Deco X73-DSL(1.0)
- Deco XE75
- Deco X90
- Mercusys Halo H70X
- Mercusys Halo H80X

## Not Working Devices

- Deco S7 (1.3.0 Build 20220609 Rel. 64814)

## Known Issues

### Timeout Error

Some routers give a lot of timeout errors like `Timeout fetching tplink_deco`, which cause the devices to be unavailable. This is a problem with the router. Potential mitigations:

- Rebooting the router
- Increasing [timeout seconds](#timeout-seconds) in integration config
- Increasing [timeout error retry count](#timeout-error-retry-count) in integration config

### Extra Devices

You may see extra devices show up under the Tp-Link deco integration as per https://github.com/amosyuen/ha-tplink-deco/issues/73. This is expected because the entities use macs for their unique ID. If there is another integration that exposes the same device using their mac, Home Assistant will combine the info from devices that have the same unique ID. This is working as intended since they represent the same device.

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](https://github.com/amosyuen/ha-tplink-deco/blob/main/CONTRIBUTING.md)

## Credits

This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.

Code template was mainly taken from [@Ludeeus](https://github.com/ludeeus)'s [integration_blueprint][integration_blueprint] template

---

[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[black]: https://github.com/psf/black
[black-shield]: https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge
[buymecoffee]: https://paypal.me/amosyuen
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/amosyuen/ha-tplink-deco.svg?style=for-the-badge
[commits]: https://github.com/amosyuen/ha-tplink-deco/commits/main
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge
[exampleimg]: example.png
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/amosyuen/ha-tplink-deco.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40amosyuen-blue.svg?style=for-the-badge
[pre-commit]: https://github.com/pre-commit/pre-commit
[pre-commit-shield]: https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/amosyuen/ha-tplink-deco.svg?style=for-the-badge
[releases]: https://github.com/amosyuen/ha-tplink-deco/releases
[user_profile]: https://github.com/amosyuen
