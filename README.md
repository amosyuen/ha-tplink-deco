# TP-Link Deco

[![GitHub Release](https://img.shields.io/github/v/release/amosyuen/ha-tplink-deco?style=for-the-badge)](https://github.com/amosyuen/ha-tplink-deco/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/amosyuen/ha-tplink-deco?style=for-the-badge)](https://github.com/amosyuen/ha-tplink-deco/commits/main)
[![Wiki](https://img.shields.io/badge/docs-wiki-blue?style=for-the-badge)](https://github.com/amosyuen/ha-tplink-deco/wiki)
[![License](https://img.shields.io/github/license/amosyuen/ha-tplink-deco?style=for-the-badge)](LICENSE)

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=for-the-badge)](https://github.com/pre-commit/pre-commit)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge)](https://github.com/psf/black)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz)

[![Maintained](https://img.shields.io/badge/maintained-yes-brightgreen?style=for-the-badge)]()
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.12%2B-blue?style=for-the-badge)](https://www.home-assistant.io/)

---

## 🚀 Overview

This integration provides local polling control and diagnostics for TP-Link Deco systems within Home Assistant.

For installation, configuration, troubleshooting, diagnostics, and firmware notes, see the [TP-Link Deco Wiki](https://github.com/amosyuen/ha-tplink-deco/wiki).

See the [syslog setup and troubleshooting guide](https://github.com/amosyuen/ha-tplink-deco/wiki/Syslog) for the optional forwarding feature introduced in v3.15.0. Existing installations do not need to enable forwarding or recreate the integration after upgrading.

---

## ✨ Features

### Diagnostics

- CPU usage (raw + smoothed)
- Memory usage (raw + smoothed)
- Backhaul and network diagnostics
- Monthly mobile data usage on supported 5G Deco firmware
- Coordinator health (last successful update, response time, timeouts, query mode,
  and last error)

### Session recovery

- Keeps the current Deco session during temporary connection drops to avoid
  unnecessary logins and session exhaustion.
- Automatically establishes a new session when the Deco rejects a stale session
  with HTTP 401/403.
- Recovers encrypted legacy sessions when a rebooted Deco returns an empty or
  invalid encrypted response.

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

Each config entry has its own polling switch. Since v3.15.0, the switch's
unique ID is scoped to that entry; the existing entity ID is preserved during
migration. Entity IDs can differ between installations. With multiple entries,
use each entry's switch rather than relying on the pause/resume actions to
select a particular mesh.

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

#### Deco status polling

`device_list` polling can be configured independently from client and
performance polling in the integration options. Enter an interval of at least
10 seconds, or use `0` to run `device_list` only during integration startup.

When automatic Deco status polling is disabled, client tracking and performance
updates continue normally. Deco online state, topology changes, and newly added
Deco nodes are refreshed only after reloading the integration or pressing the
`Refresh Deco status` button.

Some Deco firmware, including reported X20 firmware, may briefly interrupt
wireless-backhaul traffic while processing `device_list`. A longer interval or
startup-only mode can mitigate this firmware behavior.

---

#### Benefits

- Reduces API load
- Prevents session conflicts
- Improves stability
- Better control over performance

---

### WiFi network status

Read-only binary sensors show whether the main, guest and IoT WiFi networks are
enabled. Only networks exposed by the Deco firmware are created. The main WiFi
sensor is disabled by default because most models do not allow that network to
be switched off.

Network names (SSIDs) are not exposed by default. Enable **Show WiFi network
names on the WiFi status sensors** in the integration options to add them as
attributes. A sensor shows a single `ssid` attribute when all bands use the same
name, or one attribute per band (for example `ssid_band2_4` and `ssid_band5_1`)
when the names differ. The attribute is omitted when no name is reported.
Passwords are never read.

Wireless status uses the configured integration polling interval and does not
delay integration setup when the optional endpoint is slow or unavailable.
Changing WiFi settings is not supported because the local write API is not
reliable across Deco models and firmware versions.

### Syslog forwarding

Forwarding sends new Deco system log lines to a syslog server as RFC 5424
messages. It's off by default. To turn it on, enable **Forward the Deco system
log to a syslog server** in the integration options and enter the server's
host. Each config entry forwards its own Deco's log.

The port defaults to 514. UDP sends one datagram per line, and TCP ends each
line with a newline (RFC 6587).

Each run downloads the whole log at the chosen level. A download can take
several seconds, and other polling waits until it finishes. The interval
defaults to 300 seconds, with a minimum of 60.

Which lines are sent:

- Lines already in the log when forwarding is enabled or the level changes
  are not sent.
- After a restart, forwarding resumes from the saved position if it can be
  matched in the Deco's retained log, subject to the per-poll limit.
- A reported send failure keeps the saved position for a later retry. UDP
  does not acknowledge delivery, so a successful send is not proof of receipt.
- The Deco sometimes returns an empty or stale log, so a run that gets an
  empty log or can't find the last lines seen sends nothing.
- If two non-empty downloads in succession cannot find the saved position,
  for example after the Deco reboots, the downloaded log is treated as new,
  subject to the same time budget and checkpointed batch handling.
- Since v3.15.3, new lines are sent oldest first in batches of up to 1000,
  without discarding the beginning of a burst. Each completed batch saves
  progress. A failed, interrupted or paused run can resume from that position
  on a later poll, provided the remaining lines are still in the Deco log.
- A line without a Deco timestamp, such as the rest of a command's output, is
  sent with the timestamp and priority of the last timestamped line before it.

The log can contain client names, MAC/IP addresses and authentication-related
protocol data. It is not automatically redacted. Syslog sends it unencrypted,
so use a server on a trusted local network and review logs before sharing.
TCP retries after a partial send can duplicate lines.

Versions v3.15.0 through v3.15.2 discarded older excess lines at the 1000-line
poll cap. Update to v3.15.3 or newer to preserve the start of fetched bursts.
Sending/checkpointing has a 30-second budget per run, with the existing
per-batch network timeouts and UDP pacing retained. Unsent lines are retried
from the saved position; there is no separate durable queue of their content.
Router log rotation, failed delivery and partial-send retries can still cause
loss or duplication. This is not a guaranteed lossless archive. Avoid
shortening the polling interval on a slow mesh merely to reduce burst size.

See [Syslog in the wiki](https://github.com/amosyuen/ha-tplink-deco/wiki/Syslog)
for receiver configuration, UDP/TCP tests and cleanup instructions.

Forwarding isn't available on firmware that uses the legacy encrypted web
session, such as the Deco S7 firmware listed under
[Tested Devices](#tested-devices). On that firmware, the integration logs one
warning and stops forwarding until it's reloaded.

---

## 🔧 Services

- `tplink_deco.pause_polling`
- `tplink_deco.resume_polling`
- `tplink_deco.reboot_deco`
- `tplink_deco.download_system_log`

---

## 🔌 Entities

### Polling

- `switch.deco_polling`
- `select.polling_interval`
- `button.refresh_deco_status`

### Diagnostics

- CPU usage (raw + smoothed)
- Memory usage (raw + smoothed)
- Mobile data usage (only created when exposed by the firmware)

### WiFi status

- Main WiFi (disabled by default)
- Guest WiFi
- IoT WiFi

## Device Tracking and Topology

The integration uses the local Deco web API for node and client tracking,
throughput, diagnostics, runtime polling controls and optional firmware-specific
endpoints. Some features are unavailable on particular models or firmware.

### Device Trackers

Device trackers are added for both decos and clients. The device tracker state marks whether the device is connected to the deco. If a device is not present, the previous values for attributes are saved except for `down_kilobytes_per_s` and `up_kilobytes_per_s`.

By default, Home Assistant may link a client tracker to a device from another integration when both report the same MAC address. Disable **Link client trackers to devices by MAC address** in the integration options to prevent this. The tracker keeps its entity ID and exposes the MAC as a state attribute, but no longer participates in MAC-based device matching or DHCP discovery. Existing client devices can then be removed manually; Deco devices remain protected.

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

| Attribute              | Example Values (comma separated) |
| ---------------------- | -------------------------------- |
| hw_version             | 2.0                              |
| sw_version             | 1.5.1 Build 20210204 Rel. 50164  |
| device_model           | x60                              |
| internet_online        | false, true                      |
| master                 | false, true                      |
| bssid_band2_4          | A1:B2:C3:D4:E5:F6                |
| bssid_band5            | A1:B2:C3:D4:E5:F6                |
| backhaul_bssid_band2_4 | A1:B2:C3:D4:E5:F6                |
| backhaul_bssid_band5   | A1:B2:C3:D4:E5:F6                |
| signal_band2_4         | 3                                |
| signal_band5           | 4                                |
| deco_device            | living_room                      |
| deco_mac               | 1A-B2-C3-4D-56-EF                |

Note: `deco_device` and `deco_mac` will only be set for non-master decos.

### Devices

A device is created for each deco. Each device contains the device_tracker entities for itself and any clients connected to it. Non-master deco devices will indicate that they are connected via the master deco device.

## Action Examples

### Reboot Deco

Reboots the specified decos. Example yaml:

```yaml
action: tplink_deco.reboot_deco
data:
  device_id:
    - ef41562be18e5e3057e232ffb26de9bb
    - d7f96b1f312d83f195b35ecdfbb3b02b
```

### Download System Log

Saves the Deco system log to `<config>/tplink_deco_logs/<filename>` and returns
the file path and line count. The file is the one the web UI's Save Log button
produces under Advanced > System > System Log.

```yaml
action: tplink_deco.download_system_log
data:
  config_entry_id: 01JABCDEF0123456789ABCDEFG # required with more than one Deco entry
  filename: deco.log # optional, defaults to deco-<timestamp>.log
  log_level: WARNING # optional, defaults to ALL
response_variable: system_log
```

Use **Developer tools > Actions** to run the action interactively. Select the
Deco entry there when more than one is loaded. `response_variable` is for a
script or automation; omit it in the interactive action editor. The response
contains the saved `path` and `line_count`. An existing file with the same name
is overwritten; omit `filename` to use a timestamped name.

Downloaded router logs are not automatically redacted and can contain
authentication-related data as well as network/client identifiers. This is
different from the integration's redacted Home Assistant diagnostics file.

The action isn't available on firmware that uses the legacy encrypted web
session, such as the Deco S7 firmware listed under
[Tested Devices](#tested-devices).

Since v3.15.2, plain-text, gzip-compressed and tar-packaged log snapshots are
decoded automatically, including compressed responses without a correct
`Content-Encoding` header. This applies to both manual downloads and syslog
forwarding, including the reported BE65 and BE9300 firmware variants. Only
the selected regular log file is read from an archive; nothing is extracted
to disk. No configuration changes are required.

<!-- ha-marketplace:exclude-start -->

{% if not installed %}

## Installation

### Marketplace / HACS

For Home Assistant 2026.11 and later:

1. Open **Settings > Marketplace**.
2. Search for **TP-Link Deco**.
3. Select the integration and choose **Install**.

For Home Assistant 2026.10 and earlier, follow the same steps under **HACS > Integrations**.

The button below opens this repository in Marketplace on Home Assistant 2026.11 and later, and in HACS on older versions:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=amosyuen&repository=ha-tplink-deco&category=integration)

### Manual

1. Using the tool of choice open the directory (folder) for your [HA configuration](https://www.home-assistant.io/docs/configuration/) (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `tplink_deco`.
4. Download _all_ the files from the `custom_components/tplink_deco/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant

When updating manually, back up the existing integration directory, use all
files from the same published release (including new modules and translation
files), and restart Home Assistant fully. Do not delete the configured
integration or its entity registry to update the files. Do not mix files from
different releases or copy an extra nested `tplink_deco` directory.

{% endif %}

<!-- ha-marketplace:exclude-end -->

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

### Timeout Seconds

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
- Deco S7 (1.3.0 Build 20220609 Rel. 64814)
- Deco X20
- Deco X50
- Deco X60
- Deco X68
- Deco X73-DSL(1.0)
- Deco XE75
- Deco X90
- Mercusys Halo H70X
- Mercusys Halo H80X

The Deco S7 firmware listed above uses a legacy encrypted local-web session over
HTTP. The integration detects and handles this authentication and request format,
including numeric values returned as strings by the legacy API.

## Known Issues

### Syslog sends nothing or reports the 1000-line cap

The receiver must listen on the exact host, port and UDP/TCP protocol configured
in the integration. Inbound firewall rules must match that protocol, and a VPN
or network isolation can prevent delivery. The first successful download after
enabling forwarding only records a starting point; allow a later poll to send
new lines. The default interval is five minutes.

A successful UDP send does not confirm receipt. On v3.15.0 through v3.15.2,
cap warnings mean older excess lines were skipped; update to v3.15.3 or newer
for chronological, checkpointed batches. See the
[syslog guide](https://github.com/amosyuen/ha-tplink-deco/wiki/Syslog) for details.

### Deprecated connection-class warning

The `CONN_CLASS_CLOUD_POLL` warning from this integration is resolved in
v3.15.0. Update all integration files and fully restart Home Assistant. An old
log entry can remain visible after the fix; check its timestamp. Warnings
from other integrations require fixes in those integrations.

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

Thank you to all contributors. The v3.15.0 system-log and compatibility work
includes contributions from [@alunduil](https://github.com/alunduil),
[@gappleby](https://github.com/gappleby), [@rjullien](https://github.com/rjullien),
[@SJRepos](https://github.com/SJRepos), [@misa1515](https://github.com/misa1515)
and [@dkwolf1](https://github.com/dkwolf1). See the release notes and commit
history for individual contributions.

[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]
[![Community Forum][forum-shield]][forum]

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
