# Setup

Run commands from the repository root. This prototype is Windows-only.

## Requirements

- Python 3.12, including Tkinter.
- .NET 8 SDK and Microsoft Edge WebView2 Runtime.
- An EA account with an active entitlement to the game being launched.
- Your own locally installed EA app files from the supported build:
  **13.809.0.6322**. Other builds are rejected rather than guessed.

No EA executables, game files, credentials, or prepared account state are supplied.

## Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
dotnet build auth_host/EaStandalone.AuthHost.csproj -c Release
```

If PowerShell activation is restricted, use `.venv\Scripts\python.exe` directly;
do not weaken your execution policy just to activate the environment.

## Configure your account

Replace the placeholder with the path to your own supported EA executable.

```powershell
python -m tools.bootstrap_standalone_secrets "<path-to-your-EADesktop.exe>" private/ea_bootstrap.dpapi
python tools/standalone_login.py
python tools/fetch_standalone_library.py
python -m standalone_launcher.gui
```

Sign in yourself in the WebView2 window. Authentication material and the library
snapshot stay in `private/`, protected using Windows DPAPI. Do not share that
folder, even between your own accounts or machines.

## Battle for Neighborville

Build the inert process-name helper once:

```powershell
dotnet build tools/process_name_probe/ProcessNameProbe.csproj -c Release -p:AssemblyName=EADesktop -o artifacts/diagnostics/process_name_probe/desktop
```

The game must be installed with its DiP manifest and a valid EA-signed license.
Use **Renew license** if needed, then **Launch selected**. The directory CLI is:

```powershell
python tools/launch_standalone_game.py "<installed-game-directory>"
```

Do not use the executable path for BFN's managed launch. Close existing game/EA
client processes yourself first; the launcher refuses conflicts. Its supervisor
keeps support processes alive until the game exits. `--trace` enables redacted
launcher/LSX diagnostics; it is not a game-traffic interceptor.

## Unravel Two diagnostics

Unravel's fresh SDK license exchange and opening cinematic were confirmed through
a diagnostic session, **not** the normal GUI/CLI launch route. Its diagnostic host
supports an explicit owned offer and `--answer-license`; see
[`tools/`](../tools/README.md). The license decoder also requires your own matching
`EADesktop.exe` at `artifacts/EADesktop.exe`. This local file must never be committed.

## Troubleshooting

- Check [title-specific limitations](status.md); support is not universal.
- Keep anti-cheat's required Windows security settings enabled. No bypass is supplied.
- A black window is not proof of an activation failure. Check whether it is minimized;
  a normal restart resolved the observed Unravel video issue, but its cause is unknown.
- Never post credentials, license contents, request tickets, or raw captures in issues.
