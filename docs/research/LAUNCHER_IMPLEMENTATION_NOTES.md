# Standalone EA launcher core

This directory contains the EA-independent authentication and owned-library
core for EA Desktop build `13.809.0.6322`. The code performs no EA Desktop IPC
and does not read EA Desktop cookies or token caches.

Run these commands from the repository root:

```powershell
python .\tools\bootstrap_standalone_secrets.py
dotnet build .\auth_host\EaStandalone.AuthHost.csproj -c Release
python .\tools\standalone_login.py
python .\tools\refresh_standalone_tokens.py
python .\tools\fetch_standalone_library.py
python .\tools\show_standalone_library.py
python .\tools\fetch_package_metadata.py Origin.OFR.50.0004343
python .\tools\plan_package_install.py Origin.OFR.50.0004343 --locale en_US
python .\tools\launch_standalone_game.py "C:\Games\Installed EA Game"
python .\tools\refresh_standalone_license.py Origin.OFR.50.0000357
python .\tools\refresh_standalone_license.py Origin.OFR.50.0004873
python .\tools\standalone_logout.py
python -m standalone_launcher.gui
```

`bootstrap_standalone_secrets.py` accepts only the pinned EADesktop SHA-256 and
writes recovered build credentials directly to a DPAPI-protected file.
`standalone_login.py` opens the account page in the WebView2 host and stores the
OAuth token set with DPAPI. `fetch_standalone_library.py` retrieves the complete
current-user, entitlement, offer, and product documents and saves them as
`private/ea_library.dpapi`.

The default `show_standalone_library.py` view shows active base games. Pass
`--all` to include disabled records, expansions, and add-ons. The view joins
catalog installation metadata with local uninstall registration. The protected
snapshot remains the lossless source and retains every field returned by the
recovered GraphQL operations.

`python -m standalone_launcher.gui` opens a native Windows library view. Its
header shows the number of active titles and the raw entitlement, catalog, and
product totals. The checkbox exposes disabled products and add-ons. The
**Refresh from EA** button updates the encrypted snapshot with the standalone
access token. Select an installed title and use **Launch selected**, or
double-click it, to resolve the preferred executable from the installed DiP
manifest and start it directly.

The **Renew license** button requests a fresh EA-signed OOA license for a
selected owned title when its machine-binding algorithm is supported. For
MOHPA, **Launch selected** also acquires a license automatically if its local
`.dlf` is absent. Both paths were exercised from the GUI with the EA client
stopped.

MOHPA content ID `1019521`, launcher UID `2-2`, has a confirmed native
compatibility argument, `nolauncher`. The resolver applies it automatically so
the library GUI reaches the game window instead of the title's setup launcher.

`launch_standalone_game.py` accepts either an installed game directory or an
explicit executable. For a directory it reads
`__Installer/installerdata.xml`, prefers a normal game launcher over setup or
configuration entries, and accepts `--launcher-uid` when a specific manifest
entry is required. The process receives a locally generated `EARtPLaunchCode`
and the DiP manifest's `ContentId`; the launcher itself does not start or
communicate with EA Desktop. Protected games still require their valid signed
EA license in the normal local license store. A game can independently start
EA Desktop through Origin SDK, as Battle for Neighborville currently does.

`refresh_standalone_license.py` now independently acquires MOHPA's signed OOA
license. It uses the saved OAuth token, a machine binding calculated from the
title's own legacy algorithm, EA's license endpoint, and local DSA signature
verification. It protects any prior license with DPAPI before atomic
replacement. A test with the local `.dlf` absent acquired a new license and
launched the game without EA processes. Battle for Neighborville content ID
`194814` uses the independently reconstructed mode-4 binding; its signed
license was also acquired and verified without EA Desktop. Other titles still
require a separately confirmed binding; the mode-4 hash is not a safe universal
default. Details are in [`../LICENSE_ACTIVATION_RE.md`](LICENSE_ACTIVATION_RE.md)
and [`../BFN_ACTIVATION_RE.md`](BFN_ACTIVATION_RE.md).

Battle for Neighborville's full 166-file selection is installed at
`E:\Games\Plants vs Zombies Battle for Neighborville` and its signed touchup
update completed. On 2026-10-20, the standalone LSX/session host obtained fresh
EA game codes and the user confirmed reaching the public hub. The first proof
still briefly started real EA Desktop. A later comparison kept the real
installation folder renamed: an **inert process named `EADesktop.exe`** plus
our host also reached the hub, with no genuine EA Desktop observed. A probe
named `EABackgroundService.exe` did not suffice. Thus the actual EA client can
be absent, but the tested workaround still has a process with its name.
The **prototype GUI and normal CLI now start the tested host/helper pair
automatically for BFN**. Build the Desktop-named helper once using
[`tools/process_name_probe/README.md`](../../tools/process_name_probe/README.md),
then use **Launch selected** or:

```powershell
python .\tools\launch_standalone_game.py "E:\Games\Plants vs Zombies Battle for Neighborville"
```

Use the installed directory, not an explicit executable, for managed BFN
launching. A saved standalone login, active library entitlement, cached signed
BFN license and the existing diagnostic dependencies (including Frida for
process enumeration only) are required. Use **Renew license** if the signed
license is missing. The normal route does not launch or modify the real EA
client, stop an already-running client, rename folders, or modify the registry.
It refuses occupied LSX ports or an already-running BFN/Desktop process.

The GUI starts support asynchronously. Closing the GUI or allowing the CLI to
exit does **not** stop BFN: an independent supervisor owns the session. Unlike
the diagnostic, there is **no two-minute gameplay timer**. After BFN and its
anti-cheat launcher exit, the supervisor closes only its own host/helper,
allowing a five-second exit grace. `--wait` waits for that full BFN session;
other games retain direct-launch behavior. Existing low-level diagnostic entry
points remain direct. The normal CLI was live-tested through public-hub
sign-in and automatic helper cleanup after the user quit. GUI routing/close
behavior has unit coverage and the window passed a startup smoke test; a live
GUI button-click game launch was not separately repeated.

For a live console conversation trace, use:

```powershell
python .\tools\launch_standalone_game.py "E:\Games\Plants vs Zombies Battle for Neighborville" --trace
```

`--trace` implies `--wait`, keeping the CLI console open until BFN exits. It
prints decoded LSX requests/replies with directions and timestamps, plus the
launcher's OAuth refresh and game-auth HTTP request/response fields, endpoint
paths and status codes. Credentials, auth codes, challenge material, profile
identifiers, redirect/cookie values and unknown fields are redacted before
printing. Logs use the console's stderr channel, separate from the supervisor
readiness pipe; no log file is created. Ctrl+C stops console waiting/tracing,
not the running game. Default launches and the GUI remain quiet. This does
**not** intercept the game's own HTTPS or other game-server payloads.

This deliberately reuses the tested diagnostic host with duration `0` (run
until stopped), exclusive loopback ports, disabled overlay reporting, and
account-backed startup/session replies. Credentials are not passed on command
lines or logged. This is working prototype integration, not a rewritten/final
SDK server. Local presence is not published to EA friends/XMPP. Friends,
block-list/achievement replies, extended play, and the exact native discovery
check remain open. Timed comparison tools remain available separately.

`standalone_logout.py` removes the protected token and library files and clears
the dedicated WebView2 profile. The next login therefore prompts for an EA
account again. It does not modify EA Desktop's own cookies or signed-in state.

Authentication, token refresh, remote library retrieval, JIT package lookup,
range-based ZIP access, DiP parsing, package extraction, touchup finalization,
and fresh-license acquisition and direct launch for MOHPA have all been
exercised without EA Desktop. The live
launch proof used Medal of Honor: Pacific Assault with EA Desktop, its launch
helpers, and `EABackgroundService` stopped. Its first run reached the title's
own configuration executable; the confirmed native `nolauncher` argument then
reached the `Medal of Honor Pacific Assault(tm)` game window directly. The old
full-screen process did not report a responsive window during the observation,
so gameplay input still needs a manual validation.

First activation and new-license coverage for other titles, Denuvo
reactivation, broader EA AntiCheat title coverage, Steam/Epic handoff, cloud
saves, updates/repair policy, and general session monitoring remain open. The older
`custom_launcher` directory is retained only as a behavioral oracle for the
EA-brokered path.
