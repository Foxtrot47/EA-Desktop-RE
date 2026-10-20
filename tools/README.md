# Tools

Run from the repository root after [setup](../docs/setup.md).

## Everyday utilities

| Script | Purpose |
| --- | --- |
| `standalone_login.py` / `standalone_logout.py` | Sign in or clear this launcher's local session |
| `fetch_standalone_library.py` / `show_standalone_library.py` | Refresh or inspect your owned library |
| `fetch_package_metadata.py` / `plan_package_install.py` | Inspect an owned game's package |
| `extract_package.py` | Plan an install; `--execute` downloads/extracts selected files |
| `run_touchup.py` | Plan installer finalization; `--execute` runs EA's installer |
| `refresh_standalone_license.py` | Acquire a signed license for supported bindings |
| `launch_standalone_game.py` | Launch an installed directory or explicit executable |

Use `--help` for arguments. Planning tools do not execute installation by default.

## SDK diagnostics

`probe_lsx_connection.py` hosts a diagnostic loopback SDK connection. BFN is the
default title; `--offer-id` selects an active owned entitlement. Other titles
cannot use BFN's game-auth-code session.

Unravel Two's observed startup/license exchange used:

```powershell
python tools/probe_lsx_connection.py --seconds 0 --exclusive --offer-id Origin.OFR.50.0002520 --send-challenge --ack-challenge --answer-startup --disable-overlay --answer-license
```

That host command alone does **not** launch the game or inert helper. The confirmed
session also ran the built [Desktop-name helper](process_name_probe/README.md) and
launched the installed game with its manifest identity. Keep support processes
running until the game exits. This remains a diagnostic, not normal Unravel integration.

## Research scripts

`idalib_*.py` requires a separately installed, licensed IDA/IDALib environment.
Capture, relay, Frida, and live-game scripts are investigation tools, not routine
launcher setup. Read their descriptions before use; some execute targets or
control test-owned processes. Do not share their raw output or local inputs.

No proprietary analysis inputs or generated results are distributed here.
