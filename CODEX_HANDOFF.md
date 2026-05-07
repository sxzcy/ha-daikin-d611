# Codex Handoff: Daikin DTA117D611 Home Assistant Integration

This file is a public, non-secret handoff for future Codex sessions. It captures
the current project state, important design decisions, and the next practical
optimization targets.

## Repository

- GitHub: https://github.com/sxzcy/ha-daikin-d611
- HACS category: Integration
- Current release: `v0.4.10`
- Home Assistant domain: `daikin_d611`
- Integration name: `Daikin DTA117D611`

## Current State

- HACS-compatible repository structure is in place.
- GitHub Actions has two successful jobs:
  - HACS official validation through `hacs/action@main`
  - Local validation for Python compile, JSON files, and parser fixtures
- GitHub Release `v0.4.10` exists.
- The integration is intended for Daikin New Life Multi accounts with a
  DTA117D611 gateway.
- Runtime behavior is local-first after cloud-assisted setup.

## Public Features

- Config flow setup from Home Assistant UI.
- Daikin cloud login for gateway discovery and user context.
- DTA117D611 local socket device discovery and polling.
- Indoor air conditioners exposed as `climate`.
- VAM / Mini VAM fresh-air units exposed as `fan`.
- Air sensor values exposed as sensors and binary sensors.
- Mode and airflow selects for supported device types.
- Diagnostics download with account, token, MAC, serial, and raw frame fields
  redacted.
- Daikin brand assets under `custom_components/daikin_d611/brand/`.

## Important Implementation Notes

- `api.py` is only a compatibility export module.
- Cloud client implementation is in `cloud.py`.
- Socket protocol and parsers are in `socket.py`.
- Shared helpers and exceptions are in `codec.py`.
- Entity naming and stable physical IDs are in `models.py` and `entity.py`.
- Parser fixtures are under `tests/fixtures/`.
- Minimal parser tests are in `tests/test_parsers.py`.

## Current Real-World Gateway Shape

Observed cloud gateway payload shape:

- Gateway display name may be generic, for example `智能网关`.
- Gateway key / MAC may be the useful stable identifier, for example a
  12-character hex-like string.
- Users may naturally type `DTA117D611` in the gateway field.
- If the cloud account has exactly one gateway, the integration automatically
  uses that gateway even when the entered gateway label does not exactly match
  the cloud gateway name.

Do not hardcode any real account, password, token, SSH key, IP address, or local
gateway secret into this repository.

## Validation Commands

From the repository root:

```bash
python -m compileall custom_components/daikin_d611
python -m json.tool hacs.json >/dev/null
python -m json.tool custom_components/daikin_d611/manifest.json >/dev/null
python -m json.tool custom_components/daikin_d611/strings.json >/dev/null
python -m json.tool custom_components/daikin_d611/translations/en.json >/dev/null
python -m json.tool custom_components/daikin_d611/translations/zh-Hans.json >/dev/null
pytest -q
```

If `pytest` is not installed locally, the parser tests can still be executed by
loading `tests/test_parsers.py` manually, but GitHub Actions should remain the
authoritative public check.

## Release Checklist

1. Update `custom_components/daikin_d611/manifest.json` version.
2. Update release notes.
3. Run local validation.
4. Commit to `main`.
5. Create annotated tag matching the manifest version, for example `v0.4.11`.
6. Push `main` and tags.
7. Create a GitHub Release for the tag.
8. Confirm GitHub Actions HACS validation passes.

## Next Optimization Targets

Prioritize issues that improve real user installation and diagnostics:

1. Improve config flow errors so cloud login, gateway discovery, and local socket
   connection failures show distinct messages instead of generic labels.
2. Add a gateway selection step when the account has multiple gateways.
3. Add a local host/port validation helper that reports socket connection errors
   without requiring users to inspect Home Assistant logs.
4. Expand parser fixtures with more real but redacted device payloads from other
   DTA117D611 firmware versions.
5. Add screenshots to README after HACS installation is visually confirmed.
6. Add a troubleshooting section covering:
   - login failure
   - gateway not found
   - local socket timeout
   - unknown states
   - fresh-air unit control ACK timeout
7. Consider reducing large raw diagnostic attributes by default and keeping raw
   frame details primarily in diagnostics downloads.

## Suggested Prompt For Future Codex Sessions

```text
Use $karpathy-guidelines. Continue optimizing this repo:
https://github.com/sxzcy/ha-daikin-d611
Read CODEX_HANDOFF.md first, then inspect the current code before changing it.
Focus on the next optimization target: <describe target>.
```
