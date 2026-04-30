# Daikin DTA117D611 for Home Assistant

[English](README.md) | [简体中文](README.zh-CN.md)

Home Assistant custom integration for Daikin New Life Multi gateways using the
DTA117D611 local socket protocol.

This integration is intended for DTA117D611 installations where the Daikin app
can see a local gateway and that gateway exposes indoor air conditioners,
Mini VAM / VAM fresh-air devices, and sensors.

## Features

- UI setup through Home Assistant config flow.
- Daikin cloud login for gateway discovery and socket parameters.
- Local socket polling after setup.
- Indoor air conditioners as `climate` entities.
- VAM / Mini VAM fresh-air devices as `fan` entities.
- Temperature, CO2, PM2.5, humidity, raw status, refresh, and control-result
  sensors.
- Online, power, problem, and optional raw snapshot binary sensors.
- Mode and airflow selects where the device reports supported values.
- Gateway/cloud device names are used when available.
- Options for scan interval, timeout, state priority, cloud snapshots, stable
  IDs, and diagnostic entities.
- Home Assistant diagnostics download with private account, token, MAC, serial,
  and raw frame fields redacted.

## Requirements

- Home Assistant 2026.3 or newer is recommended.
- A Daikin account that can log in to the Daikin New Life Multi app.
- A DTA117D611 gateway reachable from the Home Assistant network.
- Devices already paired to the gateway in the Daikin app.

## HACS Installation

1. Open HACS.
2. Add this repository as a custom repository.
3. Choose category `Integration`.
4. Install `Daikin DTA117D611`.
5. Restart Home Assistant.
6. Go to **Settings -> Devices & services -> Add integration**.
7. Search for `Daikin DTA117D611`.

## Manual Installation

Copy:

```text
custom_components/daikin_d611
```

to:

```text
<home-assistant-config>/custom_components/daikin_d611
```

Restart Home Assistant, then add the integration from the UI.

## Configuration

Recommended initial values:

- Gateway: `DTA117D611`, or the actual gateway key/MAC such as `60180310B941`.
- Host/Port: leave blank first. The integration uses `socketIp/socketPort` from
  the Daikin cloud gateway payload.
- Scan interval: `60` seconds.
- Timeout: `10` seconds.

If the account only has one gateway, the integration will use that gateway even
when the entered gateway label does not exactly match the cloud gateway name.

If cloud lookup works but local socket access fails, fill Host/Port manually
with the gateway address shown by your router or by Daikin app traffic.

## Notes and Limitations

- Cloud login is still required during setup to discover the gateway and obtain
  user context.
- Runtime state is local-first by default. Cloud snapshot polling can be enabled
  in options as a fallback/debug source.
- Local control support depends on gateway firmware and the command set exposed
  by each connected indoor unit or fresh-air unit.
- Some Daikin payload fields are undocumented. Unknown fields are preserved in
  diagnostic attributes where practical.
- New installations use stable physical IDs by default. Existing installations
  can toggle this option to migrate from room-based legacy IDs.
- This project is independent from `ha-dsair`, which targets older
  DTA117B611/DTA117C611 style devices.

## Public Release Hygiene

Do not publish APK files, decompiled source trees, local captures, credentials,
or personal gateway data in this repository.
