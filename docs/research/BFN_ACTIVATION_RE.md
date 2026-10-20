# Battle for Neighborville: install and activation trace

This trace concerns the owned EA offer `Origin.OFR.50.0004873`, content ID
`194814`, build `1.0.55.50002` on 2026-10-19. The installed game is under
`E:\Games\Plants vs Zombies Battle for Neighborville`. Tests used the unmodified,
EA-signed game, activation library, anti-cheat launcher, and installer.

## Package and installation

The 19,101,214,972-byte DiP archive contains 250 entries. The `en_US` full
selection has 166 files and 19,134,479,272 installed bytes. Its progressive
manifest marks 124 files (6,265,403,830 installed bytes) as the initial required
set and 42 files (12,868,418,280 compressed bytes) as recommended full-game
content. The standalone extractor CRC-verified the required set, and signed
`__Installer/Touchup.exe` completed with exit code 0. Its log records the EA
AntiCheat custom component installation (`-title pvzgw3 -eactitleId 473`), the
game's uninstall registration, and its `Install Dir` registry value. Existing
newer VC++ runtimes caused the bundled older redistributables to return 1638;
touchup still completed successfully. The extractor then completed the entire
166-file selection: 19,134,479,272 installed bytes, no missing or partial
files, and CRC validation for each extracted entry. The signed touchup update
ran after full extraction and exited 0. Its update invocation started
`EADesktop.exe` and `EABackgroundService.exe`; both were stopped before the
standalone launch test. The game is registered at the requested `E:\Games`
location.

The DiP launcher UID `1-1` names `EAAntiCheat.GameServiceLauncher.exe` and has
no manifest arguments. The catalog's `executePathOverride` instead names
`PVZBattleforNeighborville.exe`; the launch coordinator must honor the DiP
anti-cheat launcher. The package also carries Easy Anti-Cheat files and a game
setting named `UseDenuvoProtection`. The presence of that setting alone does not
establish its runtime value.

## Signed license and local activation

The game imports `Core/Activation64.dll` ordinals 100 and 101. IDALib found the
license request builder in that DLL at `0x180022510`, its caller at
`0x180027C50`, and the machine-hash selector at `0x180037380`. A new-license
path calls the selector with mode 4 (`0x180025910`). At the SHA-1 formatter
call (`0x180037482`), mode 4 selects fixed-width lowercase hex. This matches
the already reconstructed mode-4 Windows hardware fingerprint used by the
standalone identity client. The activation DLL also contains its own OOA OAuth
and license HTTP routines; these are distinct from the game's later Origin SDK
connection.

With EA Desktop stopped, the standalone account session requested a license
for content ID `194814` and the calculated mode-4 binding. EA returned a signed
577-byte `.dlf`. Local signature verification passed before the file was placed
at the normal EA Services license path. Neither the signed bytes, account ID,
machine hash, nor OAuth credentials are in this report. The standalone license
service now derives this binding automatically for this content ID; it does not
depend on a previously cached hash.

`Activation64.dll:0x18000CB30` reads `EARtPLaunchCode` from the environment,
validates the UTC date checksum against a window from yesterday through three
days ahead, then reads `ContentId` and checks it against the wrapped game's
embedded content-ID list. `0x18000CE80` takes the `origin2` fallback when this
check fails. The first direct anti-cheat launch supplied only the RTP code and
caused an `origin2://game/launch` request that started EA Desktop. The
standalone launch environment now supplies the manifest's `ContentId=194814` as
well. Focused tests cover the environment and license-selection branches.

## Remaining EA Desktop dependency

With both environment values present and EA Desktop/background service stopped,
the signed anti-cheat launcher started the game executable. The game then
started a plain `EADesktop.exe` process as its child, without an `origin2`
launch argument. A diagnostic direct game-executable start with the same
environment produced the same plain EA Desktop child. The signed license
remained in place. EA Desktop's log then recorded an Origin SDK/LSX connection
for product `194814` and requests including `ChallengeResponse`, `GetConfig`,
`GetProfile`, and `GetSetting`. Those observations support local activation
advancing to game code; they do not prove that offline or online gameplay works
without the LSX host. The next required component is an authorized LSX host
backed by the standalone account session, with enough of the game's request
sequence implemented to prevent its Origin SDK from starting EA Desktop.

An oracle connection to EA Desktop's port 3216 received a NUL-terminated XML
`Event/Challenge` first. The packet is 132 bytes including its NUL terminator;
its `key` is 32 hex characters, `version` is `13,809,0,6322`, and `build` is
`release` for the tested EA Desktop build. The game answers with
`ChallengeResponse` carrying
`response`, `key`, and `version` attributes plus `ContentId`, `Title`,
`MultiplayerId`, `Language`, and `Version` elements. It then requests
`GetConfig` (SDK version 3), `GetProfile` (index 0), and `GetSetting` for
`IS_IGO_ENABLED`. `GetConfigResponse` advertises 28 `EbisuSDK` facilities.
The auto-started EA Desktop returned `Invalid user` to this game's
`GetProfile`, consistent with its session not being authenticated; this does
not invalidate the independently issued signed license. A loopback listener on
3216 received the game's TCP connection, but did not prevent the Origin SDK
from spawning EA Desktop before connecting. A production replacement needs to
validate LSX clients and source profile/auth responses from the standalone
session, rather than replaying an unrelated account's cached responses.

A second diagnostic listener sent a fresh, NUL-terminated LSX `Challenge` on
port 3216. BFN connected and sent a 431/432-byte `ChallengeResponse` with the
expected five identity child elements. Unlike a listener that only accepted
TCP, this left the game process running with a responsive `PVZ Battle for
Neighborville` window beyond 20 seconds. EA Desktop still started as a child
of the game, so this is evidence of an independent LSX transport connection,
not an EA-free startup. After stopping EA Desktop and its background service,
the game window remained responsive for at least another 12 seconds. Gameplay
and the validity of the diagnostic challenge response have not been confirmed.

After the complete install and touchup update, the signed anti-cheat launcher
exited 0 following a roughly 17-second attempt. A direct diagnostic run of the
game executable with the same launch environment exited 0 after roughly five
seconds; it spawned `EADesktop.exe` as its child. The new EA Desktop log again
contained the BFN product ID, LSX `ChallengeResponse`, `GetConfig`,
`GetProfile`, `GetSetting`, and `Invalid user`. There was no observed sustained
game process or gameplay. This full-install retest confirms the remaining
Origin SDK dependency rather than proving an EA-free launch. The client and
background service were stopped again afterward.

Static evidence: `analysis/index/BFN-game.json`,
`analysis/index/BFN-Activation64.json`,
`analysis/decomp/BFN-Activation64-utf16-refs.json`, and
`analysis/decomp/BFN-Activation64-mode-callsite.json`. Full pseudocode for the
activation library is kept under the gitignored `private/idalib_decomp` tree
because it includes embedded credential material.

## Successful normal-launch reference and LSX replacement probe (2026-10-20)

The user launched BFN from an authenticated EA Desktop session and confirmed
that it reached the main menu. A redacted capture of that successful run is in
`analysis/runtime/bfn_normal_launch_oracle.json`. It records message names
and field names without account identifiers, auth codes, license bytes, or raw
message bodies. The early request/reply sequence was `ChallengeResponse`,
`GetConfig`, `GetProfile`, `GetSetting(IS_IGO_ENABLED)`, two `GetGameInfo`
requests (`FREETRIAL`, `LANGUAGES`), two more settings (`ENVIRONMENT`,
`IS_IGO_AVAILABLE`), `GetAllGameInfo`, and
`IsProgressiveInstallationAvailable`. Later requests included profile,
presence, connectivity, `GetAuthCode`, friends, and the block list. That
successful trace establishes what the game requests, but not which individual
response fields are mandatory.

IDALib analysis of the EA Desktop LSX server recovered the authenticated
challenge exchange and version-3 encrypted socket framing. The local host in
`tools/probe_lsx_connection.py` validates the game's challenge proof, sends
`ChallengeAccepted`, and decrypts subsequent LSX requests. The SDK startup
reply builder in `standalone_launcher/lsx_startup.py` sources profile IDs from
the standalone, DPAPI-protected library snapshot and game metadata from the
catalog. Its first 11 generated response schemas match the normal EA Desktop
trace; the nonpersonal profile field values also match. The builder does not
fabricate an EA online auth code.

In two direct-launch probes, BFN accepted the independent host's handshake
and consumed its `GetConfigResponse`, `GetProfileResponse`, and first
`GetSettingResponse`. It then disconnected about 2.3-2.5 seconds later and
the game process exited. The signed anti-cheat launcher itself exited 0.
EA Desktop auto-started during both tests despite the working LSX connection;
because our host occupied port 3216, EA Desktop failed to bind it and displayed
`EC:10701`. This port collision was caused by the diagnostic setup. Its
relationship to the game exit is unproven. The diagnostic listener was stopped,
its surviving Python child was explicitly terminated, and ports 3216/3217
were verified free afterward. Further independent-launch testing must avoid
making EA Desktop contend for the same listener port, or first prevent its
automatic start.

IDA's `UtilityHandlers::getAuthCode` path calls the identity service's
`AuthCodeRequestor` for a game-specific online code. The normal trace shows
BFN issuing this request after reaching its online startup phase. This is a
separate remaining requirement from the locally verified signed `.dlf` and
the LSX handshake; at that stage the standalone host could not answer it.

## Later 2026-10-20: direct launch and independent online sign-in

The new `tools/test_bfn_direct_lsx.py` runs bounded, fresh direct anti-cheat
launches. It does not capture/replay EA Desktop environment credentials or
attach to the game/anti-cheat. It records startup/exit events, stops its own
new EA Desktop children, preserves pre-existing background-service PIDs, and
cleans up its game and LSX host. EAAC sometimes creates a transient game
process before the real launch; the monitor now observes the entire budget
rather than treating that transient exit as final failure.

Three protocol findings changed the result:

1. **Two legitimate BFN identities.** A fresh direct run's challenge carried
   numeric content ID `194814`, whereas the normal EA launch carried offer ID
   `Origin.OFR.50.0004873`. The identity diagnostic showed valid AES proof and
   client-key shape, with only the offer-only check failing. The host now
   accepts exactly one of either known BFN identity; invalid proofs, unrelated
   titles and duplicate identities remain rejected.
2. **Unavailable overlay must not be advertised enabled.** With the identity
   fix, `--disable-overlay` yielded 45- and 60-second direct-launch survivors.
   An overlay-enabled repeat authenticated LSX but exited after
   `GetSetting(IS_IGO_ENABLED)`. One other enabled attempt exited before LSX,
   so it cannot inform the overlay comparison. The diagnostic override affects
   both IGO enabled/available settings, not installed overlay/game binaries.
3. **Connectivity is a numeric wire field.** The native normal-launch reply
   is `InternetConnectedState connected="1"`. The old host returned `"true"`:
   its schema matched, but its value did not. After changing it to `"1"`,
   BFN followed connectivity with `GetProfile`, `SetPresence` and `GetAuthCode`.

The normal-launch oracle requested `ClientId=PVZGW3-PC-SERVER-BLAZE` with empty
scope. The matching EA HTTP request contained exactly `access_token`,
`client_id`, `release_type=prod`, and `response_type=code`, with no
`redirect_uri`, PKCE or `pc_sign`. Static anchors are
`EADesktop.exe:0x1405BB9B0` (SDK request construction), `0x1406F6000`
(query construction), `0x1406F4450` (EA access-token input), `0x1406FDEF0`
(HTTP setup), and `0x1406FE620` (original 302 response/Location parsing).
The latter is retained in `analysis/decomp/EADesktop-authcode-vtables.json`;
focused entry and input artifacts have matching `EADesktop-sdk-authcode-entry`
and `EADesktop-authcode-auth-input` names.

`standalone_launcher/game_auth.py` executes that account-authorized request,
refuses redirects rather than fetching a code-bearing destination, and keeps
the issued code in memory. HTTP/transport failures produce credential-free
errors. The opt-in session handler allows only this BFN client, empty scope,
and the current snapshot user (or SDK current-user ID 0). Every game request
gets a fresh EA code, not a cached/fabricated code. Local presence comes from
the account/catalog and subsequent game updates; it is not a claim of remote
XMPP presence. Downloader utilization remains explicitly unsupported with
the normal oracle's error code.

The successful interactive run is retained as
`analysis/runtime/bfn_fresh_direct_connectivity_fixed_interactive.json` and
its `.host.log`. The host refreshed the standalone OAuth token, authenticated
BFN, returned fresh EA-issued game codes, and subsequently observed friends,
block-list and achievement requests. BFN remained alive for the full
120-second budget. The user confirmed successful sign-in and supplied
`analysis/runtime/bfn_standalone_public_hub.png`, showing the public hub.
The user also reports initial network timeouts on normal EA Desktop launches;
startup delays alone should not be attributed to our host.

**Boundary:** this is a direct-launch/online-sign-in success, not proof of
an EA Desktop-free lifecycle. One auto-started EA Desktop process was observed
at 8.765 seconds and exited at 10.906 seconds after the watcher's two-second
grace. Exact timing is retained in the process JSON. Immediate termination
was unreliable in other attempts, some of which exited before LSX. Preventing
that initial SDK auto-start remains unresolved. The host does not yet answer
friends/block-list/achievement requests. Matchmaking and extended play are
not established by this screenshot or the process timer. The regular launcher
GUI has not yet integrated the diagnostic host. Regression validation after
these changes: **98 passed, 5 subtests passed**.

### User-renamed EA Desktop folder: negative control

The user renamed `C:\Program Files\Electronic Arts\EA Desktop` to
`_EA Desktop`. The original registered executable path no longer existed;
there were no EA/BFN processes or occupied LSX ports at preflight. No registry
or installation-path changes were made by the diagnostic.

The same fresh direct diagnostic with the independent session host ran for
120 seconds. BFN appeared at 6.219 seconds and exited at 8.875 seconds; the
signed anti-cheat launcher exited 0 at 9.891 seconds. No `EADesktop.exe` was
observed, but **the game never connected to LSX**. The only host connection
was the diagnostic's own readiness probe. Evidence:
`analysis/runtime/bfn_renamed_ea_folder_interactive.json` and its `.host.log`.

This is not a working EA-free launch. It supports a remaining pre-LSX SDK
bootstrap/installation-path dependency; the exact failing check is unknown.
Renaming the folder prevents the earlier brief Desktop startup but also
prevents reaching the successfully implemented game-auth handoff in this run.
The renamed folder was left unchanged.

### Process-name comparison: inert Desktop probe reaches the public hub

The user proposed that the game might check for a running EA process and
approved separate comparisons for the two names. The real installation stayed
renamed; its original registered `EADesktop.exe` path remained absent. All
real EA/BFN processes were closed before each comparison. The actual
`EABackgroundService` Windows service was stopped; it was not reconfigured.

`tools/process_name_probe/Program.cs` only executes
`Thread.Sleep(Timeout.Infinite)`. Two console apphosts were built from it with
assembly names `EADesktop` and `EABackgroundService`, under separate diagnostic
artifact directories. Neither is EA software or implements client IPC,
EA-specific windows/readiness, service registration, or networking. The runner
starts the chosen probe without a console window, verifies its PID/name,
records both executable and managed-assembly hashes, and stops only its owned
probe afterward. Installed binaries and registry values are unchanged.

| Comparison | Evidence | Observed result |
|---|---|---|
| No probe, real path missing | `bfn_renamed_ea_folder_interactive.json` and `.host.log` | Game exited before any game LSX connection. |
| Inert `EABackgroundService.exe` | `bfn_renamed_folder_background_name_probe.json` and `.host.log` | Real game exited at 9.890 seconds; no game LSX connection. |
| Inert `EADesktop.exe` | `bfn_renamed_folder_desktop_name_probe.json` and `.host.log` | Valid LSX handshake, startup/session replies and fresh EA code handoff; game alive at 30-second cleanup. |
| Inert `EADesktop.exe`, interactive repeat | `bfn_renamed_folder_desktop_probe_interactive.json` and `.host.log` | Game alive for 120.016-second budget; **user confirmed reaching the public hub**. No additional Desktop-named process was observed. |

All paths in the table are under `analysis/runtime`. The summary is
`analysis/runtime/bfn_process_name_comparison_summary.json`. The raw automatic
trace retains `menu_verified=false`; the separate user confirmation supplies
visual outcome evidence, rather than changing what the monitor itself saw.
No new screenshot was supplied for this specific run; the older screenshot
belongs to the earlier real-client-assisted run.

**Conclusion:** an inert Desktop-named process plus our account-backed LSX host
is sufficient for this tested launch/sign-in path while the genuine EA Desktop
installation is unavailable. The background-service-named probe is not
sufficient. This strongly supports a Desktop process-identity discovery check,
but does not establish the exact native API or every predicate. It does not
prove that no process named `EADesktop.exe` is needed: that name deliberately
belongs to our inert probe. No original EA Desktop software was observed
running in this repeat. Matchmaking and extended play remain unverified.

Build and bounded reproduction commands are in
`tools/process_name_probe/README.md`. Both .NET builds succeeded with zero
warnings/errors. Python validation after the added ownership/preflight/probe
tests: **105 passed, 5 subtests passed**.

### Normal GUI/CLI prototype integration

At the user's request, the working components were connected to normal
launching without a broader optimization/rewrite. `managed_launch.launch_game`
resolves the existing DiP launcher, routes only BFN to a detached supervisor,
and leaves other titles' direct commands/environment inputs unchanged. The
older `launch_installed_game` API remains direct for diagnostic/oracle scripts.
The crypto/handshake helpers were moved unchanged into `lsx_protocol.py` and
re-exported by the diagnostic tool so its existing tests/callers remain valid.

`bfn_session.py` checks the installation, cached signed license, active library
entitlement, existing Desktop/game processes and LSX ports before starting the
already tested host and inert compatibility process. The host uses duration
`0` (run until stopped) and exclusive port binding. A readiness/authorization
pipe prevents a caller that cancels startup from inadvertently launching BFN.
After authorization, the supervisor runs independently of the GUI/CLI and
tracks the game beyond the immediate anti-cheat launcher's lifetime. There is
no fixed gameplay timer. A five-second final exit grace accommodates process
handoff. Cleanup stops only owned support processes; it does not kill a running
game on launcher-window close or helper failure.

The normal command `python tools/launch_standalone_game.py` with the installed
BFN directory was exercised live. It returned supervisor PID 23108; the
compatibility/game processes were observed, and the user confirmed **Reached
hub and quit**. After quitting, the supervisor and compatibility process were
gone and ports 3216/3217 were free. The real EA folder remained renamed. This
is retained as `analysis/runtime/bfn_normal_launcher_integration.json`.

The GUI's existing button uses the same managed route on a background thread.
Its route, status, failure, and window-close behaviors are unit-tested; the
real library window loaded and passed a launch-button/close-handler smoke
test. A live GUI button-click game launch was not separately repeated. New
routing/lifetime/cancellation tests plus the existing suite passed:
**127 passed, 5 subtests passed**. The prototype still reuses the diagnostic
host/Frida process-enumeration dependency; final packaging, long-session edge
cases and unsupported SDK/social operations remain open.

### Earlier diagnostic complexity check

Manual AST-based decision counts (including comprehensions and boolean
operators) kept each newly added function at CC 8 or below. During development,
`observe` was split into `record_changes` and `stop_new_desktops`; adding the
name probe then prompted extraction of `preflight` from `run`:

| Function | Before extraction | Final |
|---|---:|---:|
| `observe` | 14 | 6 |
| `run`, after adding name-probe ownership | 11 | 5 |

Behavior verified by transient-game-process, baseline-process preservation,
handshake validation, connectivity wire-value, local-session and credential-safe
HTTP failure tests, plus the live sign-in observation above.

## Denuvo cold-reactivation reconnaissance

Read-only inspection confirmed that the installed executable and activation DLL
match the earlier indexed artifacts (game SHA-256
`3FE7A944F891C497FE0FD8E526D3AEC744940B45DC6475655D6E64D055E6421D`,
activation DLL SHA-256
`A073118DD286FFA10E527E2A37E41D2482C74A12A537188736BEE0A72E85EE30`).
The game exports `GetDenuvoTicketLocation` at `0x140960990` and
`GetDenuvoTimeTicketRequest` at `0x1409609B0`. Their on-disk decompilation
produces implausible instructions, not a usable cache path; it must not be
interpreted as the runtime implementation. See
`analysis/decomp/BFN-denuvo-ticket-exports.json`. These export names are static
integration evidence, not proof of a fresh Denuvo activation.

No file named `dbdata.dll` was present in the installed tree. Nevertheless,
`Activation64.dll:0x1800292E0` contains a dynamic DLL loader and
`getTableData` lookup; its caller is `0x180008D30`. The DLL pathname is an
argument, so the missing conventional filename does not prove Denuvo absence.
The focused string cross-reference is retained in
`analysis/decomp/BFN-Activation64-denuvo-refs.json`; full caller pseudocode is
kept in the private decompilation directory, not published with activation
material.

The existing EA Services `194814.dlf` is 577 bytes. The game profile contains
`settings/PROFSAVE` and `settings/PROFSAVE_profile`; neither was modified or
assumed to be a Denuvo cache. An existing UTF-16 online-activation log was
located, but bounded keyword checks found no Denuvo/ticket marker. Its contents
were not copied to evidence. No activation state has been removed, renamed, or
renewed during the read-only pass; that pass did not launch the game.

The ticket/cache location remains unresolved. A short passive file-access trace
during a normal launch is the next runtime option; Windows tracing tools are
installed, but this session is not elevated. Unravel Two and the saved Need for
Speed entries have no discovered installation registrations, so fallback testing
would first require locating or installing one of those games. Cold-reactivation
success remains unproven; removing only the EA `.dlf` would not establish it.

The user subsequently approved a bounded elevated Windows file-access trace.
A 90-second `Microsoft-Windows-Kernel-File` session with keywords `0x90`
(filename/create events, no file contents) started successfully. A normal
standalone launch observed only the compatibility Desktop process and the
anti-cheat launcher; no game process was observed during the sampling window.
The user then reported that driver-signature enforcement and other security
settings had been disabled for unrelated work, preventing BFN launch. This is
user-reported context, not a diagnosis from the trace. Testing was paused;
the trace stopped successfully with exit code 0, and process enumeration found
no remaining game, compatibility Desktop, or anti-cheat launcher processes.
Raw trace metadata remains under `private/diagnostics/bfn_files_20261020_225506`.
No security settings or activation caches were changed. This attempt supplies
no evidence of a fresh Denuvo activation.
