# Unravel Two installation and activation investigation

## Confirmed installation

- Owned offer: `Origin.OFR.50.0002520`; content ID: `1035049`.
- Build: `1.0.0.1`; destination: `E:\Games\Unravel Two`.
- Extraction completed with exit code 0: 96 CRC-verified files,
  7,560,297,760 game-file bytes; no partial files remained.
- Windows WinVerifyTrust returned 0 for `__Installer/Touchup.exe`,
  `UnravelTwo.exe`, and `dbdata.dll` before setup.
- Manifest-derived signed Touchup installation completed with exit code 0.
- Installation discovery finds the game at the requested destination.
- Both native and WOW6432Node `SOFTWARE\Coldwood\UnravelTwo` keys contain
  the correct `DisplayName` and `Install Dir`. No manual registry edits occurred.

## First independent launch

The standard manifest launcher started `UnravelTwo.exe`, followed by the
installed game's `Core\ActivationUI.exe`. The EA Services `1035049.dlf` file
was absent before and after the observation window. User screenshots show
an empty legacy EA email/password activation form, with the placeholder
"DisplayName field missing from registry". This placeholder does not establish
that the game's installation registry values are absent: the two known game
keys were checked and contain them. The activation UI's exact lookup remains
unresolved. Subsequent enumeration found neither launch process running.

This is an activation prompt, not proof of a Denuvo rejection or successful
fresh activation. No user credentials were entered by the assistant, no
activation cache was removed, and no Windows security settings were changed.
Existing standalone license acquisition has title-specific machine-binding
support for other games, not a confirmed Unravel Two binding. That binding
and any game-token requirement must be established before using that service
for this title; BFN's parameters must not simply be assumed to apply.

Evidence: `analysis/runtime/unravel_two_first_launch.json`,
`analysis/decomp/UnravelTwo-Activation64-license-refs.json`, and
`analysis/decomp/UnravelTwo-ActivationUI-license-refs.json`.
Staged copies of the installed activation binaries are under
`artifacts/staged/UnravelTwo`. Full launch output stays private.

## Authorized license request and token-helper test

Static tracing found mode-4 hashing in the new-license path at
`ActivationUI.exe:0x4395D0`, through `0x4370E0` and `0x433F00`.
The formatter at `0x433CB0` uses fixed-width SHA-1 hex for modes >= 4.
Full activation-library pseudocode remains in `private/idalib_decomp` to avoid
publishing embedded activation material.

Using the existing standalone account session and local mode-4 collector,
EA issued a signed 593-byte `.dlf` for content ID `1035049`. Local signature
verification passed. There was no previous file to replace. The next game
launch exited with code `0xFFFFFFFF`; ActivationUI was observed briefly. The
license remained unchanged. The title's own activation log includes the
message "License signature is good". This confirms its signature check, not
all machine/time checks, successful gameplay, or Denuvo activation. The same
public DSA verification parameters were also found in this build's ActivationUI.
See `analysis/runtime/unravel_two_signed_license.json` and
`analysis/runtime/unravel_two_signed_license_launch.json`.

EA Desktop's game-token request parameter was traced from `0x1407A05B0`
through `0x1407A08D0`, `0x1407B1610`, `0x1407B2120`, `0x1407B39A0`, and
`0x1407AD780`: an available game token becomes the `requestToken` query
parameter. `standalone_launcher/license.py` now supports that optional parameter
without changing ordinary requests. `standalone_launcher/game_token.py`
implements the shipped helper's inherited 4 KB mapping, bounded map decoding,
exact helper-build validation, and in-memory-only challenge handling. No GUI
routing or automatic Unravel license refresh was enabled.

The first live challenge attempt failed before any token-bearing HTTP request.
`GetGameToken.exe` expects a named `dbdata.dll!getTableData` export. This
Unravel DLL has three ordinal-only exports and no named exports on disk.
An isolated absolute-path load succeeded, but `GetProcAddress("getTableData")`
returned no address and Windows error 127. Thus this helper path is not
compatible with the installed DLL's exposed API; this does not establish the
cause of the earlier game exit. No ordinal function was guessed or invoked,
no binary was patched, and no challenge or response value was persisted.
See `analysis/runtime/unravel_two_challenge_license.json` and
`analysis/runtime/unravel_two_token_helper_compatibility.json`.

Validation: 158 tests passed, 5 subtests passed; changed modules compiled.
The mapping decoder and optional request parameter are unit-tested. A successful
live mapping round trip is unverified because helper collection failed first.

## Live SDK license exchange succeeded

Further static inspection corrected the interpretation of `dbdata.dll`:
its version resource identifies Electronic Arts' **Origin Platform Interface**,
and ordinal 1 constructs `PlatformInterfaceImpl`. The filename and missing
`getTableData` export were not evidence that this DLL was a Denuvo token
provider. Ordinal 3 reaches a formatting helper. No unknown ordinal was invoked.

A challenge-only LSX listener plus the previously built inert Desktop-name
probe received Unravel's `ChallengeResponse`. An explicit owned-title context
was then added to the diagnostic host: it validates the active entitlement,
accepts only that title's numeric/offer identities and valid AES proof, and
uses its own catalog metadata. BFN remains the default; its server-auth-code
session is prohibited for other selected titles.

The live game completed `GetConfig`, `GetProfile` and overlay-setting exchange,
then repeatedly requested `RequestLicense`. Its request schema was recovered
from this DLL's serializer at `0x18004A760`: `UserId`, `RequestTicket`, and
`TicketEngine`. EA Desktop's response serializer at `0x1410D2120` writes
`RequestLicenseResponse` with a `License` field. Native license parsing at
`0x1407A3360` obtains that value from the server-issued `GameToken` XML text.

`standalone_launcher/lsx_license.py` now exchanges the fresh game-supplied
ticket with the authorized EA account. It checks the EA signature, decodes the
signed body in memory using the native-derived decoder, verifies account,
content and machine bindings, and returns the unmodified server-issued token.
The decoder reads its implementation data from the exact hash-pinned EA binary;
no decoder key, challenge, account identifier or token is embedded in evidence.
The previous license is DPAPI-backed up through the existing installer.

In the live run, a 408-character ticket with engine 0 and a matching account
produced one successful fresh exchange. The installed signed license became
3,121 bytes. After the SDK response, a second authenticated SDK connection
completed startup and issued `QueryAchievements` and `SetPresence`. The game
was still running beyond 39 seconds. This advances beyond the earlier activation
blocker. Evidence: `analysis/runtime/unravel_two_lsx_license_exchange.json`.

The live session uses `private/diagnostics/run_unravel_lsx.py`, keeping the
independent host and inert helper alive until the game exits, without a fixed
playtime timer. No genuine EA Desktop was started. The latest code compiled and
was validated with the real ticket exchange, not fabricated success replies.

## User-confirmed rendered intro after restart

The first ticket-enabled run produced music but a black screen. Inspection
found the window minimized with a zero-size client area; restoring it yielded
2560x1440, but the user still reported black video. At the user's explicit
request, the stalled test process was restarted. Normal close did not complete,
so only that path-verified, test-owned game PID was terminated. Its supervisor
cleaned up the owned host and inert name helper before the replacement launch.

The replacement launch again completed one fresh, authorized SDK license
exchange and proceeded into the game's second SDK connection. The user then
confirmed success and supplied a screenshot showing the opening boat/storm
cinematic rendered in the Unravel Two window. The screenshot is retained as
`analysis/runtime/unravel_two_intro_success.png`, with this run's metadata and
safe protocol events in `analysis/runtime/unravel_two_restart_success.json`.
No graphics configuration, driver setting, binary, or protection was changed
between these two runs. The black-screen root cause is not established.

The unanswered achievement/presence requests were not shown to cause the black
screen: video succeeded after restart with those same handlers still absent.
The current diagnostic remains running until the game exits.

## Remaining work

Normal GUI/directory-CLI routing for Unravel is not integrated yet.
Achievement/presence replies remain unsupported in this diagnostic. Intro
rendering and a fresh SDK license exchange are confirmed; gameplay input and
extended play are not yet verified. A Denuvo-specific classification of this
exact build is not independently established. No activation cache was deleted
or Windows security setting changed.
