# Launcher core

Windows-only authentication, owned-library access, package installation,
EA-signed license handling, and title-specific launch support.

```powershell
python -m standalone_launcher.gui
```

Complete [setup](../docs/setup.md) first. The normal managed launch route is
currently implemented for BFN; Unravel Two's confirmed run used diagnostics.
See [compatibility](../docs/status.md) for exact claims and limitations.

Credentials and account snapshots belong in the ignored `private/` directory.
EA/game executables and generated helpers belong in ignored local directories,
not in the repository.

Detailed history: [implementation notes](../docs/research/LAUNCHER_IMPLEMENTATION_NOTES.md).
