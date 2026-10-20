# Standalone EA Launcher

Experimental Windows launcher and protocol research for EA games you own.
Uses your EA account and EA-issued licenses; no game binaries, credentials,
or local account data are included.

## Status

| Title | Verified result |
| --- | --- |
| Battle for Neighborville | Standalone launch and online public-hub sign-in; normal launcher integration |
| Unravel Two | Fresh SDK license exchange and rendered opening cinematic; diagnostic launch only |
| Medal of Honor: Pacific Assault | Signed-license acquisition and direct launch; gameplay not verified |
| Other titles | Not verified; Battlelog integration remains open |

This is a working prototype, not a universal EA app replacement. Some launches
use an inert process named `EADesktop.exe`, not the genuine EA client.

## Getting started

Requires **Windows**, **Python 3.12**, **.NET 8 SDK**, WebView2 Runtime, and
locally supplied files from the supported EA app build.

1. Follow [setup](docs/setup.md).
2. Sign in with your own EA account.
3. Run `python -m standalone_launcher.gui`.

See [compatibility and limitations](docs/status.md) before trying a title.

## Project layout

- `standalone_launcher/` — authentication, library, installation, licensing, and launch code.
- `auth_host/` — WebView2 sign-in window.
- `tools/` — command-line utilities and research scripts.
- `custom_launcher/` — installed-game discovery and legacy EA-brokered launcher.
- `_tests/` — automated checks.
- [`docs/`](docs/README.md) — setup, status, and detailed research notes.

## Contributing and safety

Only use accounts and games you are authorized to access. This project does
not remove ownership checks, modify anti-cheat, or fabricate licenses.
Never upload account data, license files, binaries, captures, or unredacted logs.
See [contributing](CONTRIBUTING.md) and [security](SECURITY.md).

Independent project; not affiliated with or endorsed by Electronic Arts.
EA and game trademarks belong to their respective owners.

## License

[GNU GPL version 3](LICENSE) (`GPL-3.0-only`). The license covers this project's
source, not EA software, game assets, or other third-party components.
