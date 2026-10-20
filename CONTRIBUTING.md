# Contributing

Keep changes small and tied to an observed behavior or a reproducible issue.
This is a Windows prototype; avoid claiming support for untested titles.

## Development

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest _tests
```

Run the checks relevant to your change. Live game tests require your own account,
entitlement, installation, and consent to any process lifecycle changes.

## Pull requests

- Describe the change, relevant title/build, and what was actually verified.
- Preserve signature, ownership, account, and protocol-proof validation.
- Do not fabricate success replies for authorization or licensing operations.
- Do not include EA/game binaries, credentials, account snapshots, license files,
  captures, or unredacted logs. `.gitignore` is a safeguard, not a security audit.
- Keep raw research output local. Share minimal sanitized findings instead.
- Preserve third-party notices and identify any new dependencies.

Contributions are under the repository's GPL-3.0-only license. For sensitive
findings, follow [SECURITY.md](SECURITY.md) rather than a public issue.
