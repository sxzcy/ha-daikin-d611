# Daikin DTA117D611 for Home Assistant

Home Assistant custom integration for Daikin New Life Multi gateways using the
DTA117D611 local socket protocol.

This integration was built for installations where the official Daikin app can
see a local DTA117D611 gateway and the gateway exposes indoor air conditioners,
Mini VAM / VAM fresh-air devices, and sensors.

## Features

- Config flow setup from the Home Assistant UI.
- Daikin cloud login for gateway discovery and local socket parameters.
- Local socket polling for connected devices after setup.
- Indoor air conditioner devices exposed as `climate` entities.
- VAM / Mini VAM fresh-air devices exposed as `fan` entities.
- Sensor entities for reported temperature, CO2, PM2.5, humidity, raw status,
  local/cloud refresh timestamps, and control result diagnostics.
- Binary sensors for online, power, problem, and optional raw snapshots.
- Select entities for supported operating mode and airflow values.
- Device names are taken from the gateway/cloud payload when available, with
  stable fallback identifiers when the payload does not include a friendly name.
- Options flow for scan interval, timeout, state priority, cloud snapshot, stable
  IDs, and diagnostic entities.
- Home Assistant diagnostics download with private account, token, MAC, serial,
  and raw frame fields redacted.

## Requirements

- Home Assistant 2026.3 or newer is recommended.
- A Daikin account that can log in to the Daikin New Life Multi app.
- A DTA117D611 gateway reachable from the Home Assistant network.
- The gateway must already have devices paired in the Daikin app.

## HACS Installation

1. Add this repository to HACS as a custom repository.
2. Choose category `Integration`.
3. Install `Daikin DTA117D611`.
4. Restart Home Assistant.
5. Go to **Settings -> Devices & services -> Add integration**.
6. Search for `Daikin DTA117D611`.

## Manual Installation

Copy this directory:

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

If cloud gateway lookup works but local socket access fails, fill Host/Port
manually from a known local gateway address.

## Notes and Limitations

- The integration still needs Daikin cloud login during setup to discover the
  gateway and obtain user context.
- Runtime state is local-first by default. Cloud snapshot polling can be enabled
  in options as a fallback/debug source.
- Local control support depends on the DTA117D611 firmware and the command set
  exposed by the connected indoor unit or fresh-air unit.
- Some Daikin payload fields are undocumented. Unknown fields are preserved in
  raw diagnostic attributes where practical.
- New installations use stable physical IDs by default. Existing installations
  can toggle this option to migrate from room-based legacy IDs.
- This project is independent from `ha-dsair`. `ha-dsair` targets older
  DTA117B611/DTA117C611 style devices and does not cover the DTA117D611 Mini VAM
  device type observed as type `28`.

## Publishing Notes

For public HACS distribution, publish only the clean repository files. Do not
include APK files, decompiled source trees, local captures, or personal gateway
data.
