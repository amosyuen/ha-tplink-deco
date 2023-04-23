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

{% if not installed %}

## Installation

### HACS

1. Install [HACS](https://hacs.xyz/)
2. Go to HACS "Integrations >" section
3. In the lower right click "+ Explore & Download repositories"
4. Search for "TP-Link Deco" and add it
   - HA Restart is not needed since it is configured in UI config flow
5. In the Home Assistant (HA) UI go to "Configuration"
6. Click "Integrations"
7. Click "+ Add Integration"
8. Search for "TP-Link Deco"

### Manual

1. Using the tool of choice open the directory (folder) for your [HA configuration](https://www.home-assistant.io/docs/configuration/) (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `tplink_deco`.
4. Download _all_ the files from the `custom_components/tplink_deco/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant
7. In the Home Assistant (HA) UI go to "Configuration"
8. Click "Integrations"
9. Click "+ Add Integration"
10. Search for "TP-Link Deco"

{% endif %}

## Configuration (Important! Please Read)

Config is done in the HA integrations UI.

### Host

The IP address of the main deco which you visit in the browser to see the web admin page. Example: `192.168.0.1`

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
- Deco S4
- Deco X20
- Deco X50
- Deco X60
- Deco X68
- Deco X73-DSL(1.0)
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
