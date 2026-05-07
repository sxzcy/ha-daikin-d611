# Release checklist

1. Copy the latest `custom_components/daikin_d611` directory into this release
   repository.
2. Confirm `manifest.json` version matches the GitHub tag.
3. Run:

   ```bash
   python -m compileall custom_components/daikin_d611
   python -m json.tool hacs.json >/dev/null
   python -m json.tool custom_components/daikin_d611/manifest.json >/dev/null
   python -m json.tool custom_components/daikin_d611/strings.json >/dev/null
   python -m json.tool custom_components/daikin_d611/translations/en.json >/dev/null
   python -m json.tool custom_components/daikin_d611/translations/zh-Hans.json >/dev/null
   pytest -q
   ```

4. Commit only clean release files.
5. Push to GitHub.
6. Create a tag matching the manifest version, for example `v0.4.11`.
7. Add the GitHub repository to HACS as a custom integration repository.
