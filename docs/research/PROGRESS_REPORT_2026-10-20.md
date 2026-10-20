# EA Desktop replacement: progress and current BFN investigation

## Latest: opt-in redacted live CLI conversation trace

The normal BFN directory CLI now accepts `--trace`, which implies `--wait`.
It displays decoded LSX requests/replies with directions/timestamps and the
launcher's OAuth refresh/game-auth HTTP endpoint, fields and status exchanges.
Credentials, auth codes, challenge material, profile identifiers, unknown
values and redirect/cookie headers are redacted before logging. HTTP query
strings are never printed. The game’s own server HTTPS is not intercepted.

The trace travels on a separate channel from startup readiness; closing the
console does not make the host block or stop the game. Default launches and
GUI behavior remain quiet. No log file is created by this option.
The live console test was confirmed by the user (**Logs visible; game quit**);
after quitting, the console/session helpers ended and both LSX ports were free.
See `bfn_console_trace_validation.json` (`analysis/runtime/bfn_console_trace_validation.json`, local-only).
Validation: **145 passed, 5 subtests passed**, including credential-redaction,
HTTP request/response, readiness-channel separation, console-close draining,
and trace-implies-wait tests. Usage is in the standalone README.

## Working prototype integrated into normal BFN launching

The GUI's **Launch selected** and the normal installed-directory CLI now route
BFN through `standalone_launcher/managed_launch.py` and the independent
`standalone_launcher/bfn_session.py` supervisor. Other games keep their direct
launch path; low-level diagnostics remain direct.

The prototype deliberately reuses the already tested LSX diagnostic host and
Desktop-named compatibility process. No optimization or replacement SDK server
was introduced. The host runs without a duration limit, and only owned helpers
are closed after the game/anti-cheat launcher exit. Closing the GUI or the
non-waiting CLI does not stop the game. Startup waits occur off the GUI thread,
missing licenses/login/helpers and occupied ports are reported, and existing EA
processes are not terminated. The existing Frida dependency is used for process
enumeration, not game/anti-cheat attachment.

**Live normal-CLI verification:** the command returned a ready supervisor;
BFN reached the public hub, and the user confirmed **Reached hub and quit**.
After quitting, the supervisor, compatibility process and both LSX listeners
exited automatically. The real EA folder remained renamed and its original
registered executable path stayed absent. See
`bfn_normal_launcher_integration.json` (`analysis/runtime/bfn_normal_launcher_integration.json`, local-only).
GUI routing and close behavior have unit tests, and the real window passed a
startup smoke test; a live GUI game-button click was not separately repeated.
Validation: **127 passed, 5 subtests passed**, plus compilation of the new
modules. Normal launch instructions are in
[`standalone_launcher/README.md`](../../standalone_launcher/README.md).

This remains prototype code: it still uses an inert process named
`EADesktop.exe`, and friends/block-list/achievement coverage, extended play and
broader packaging remain open. No game/anti-cheat or registry changes were made.

## Earlier 2026-10-20: genuine EA Desktop absent; inert name probe reached the hub

The user proposed a process-name check. Separate, approved comparisons kept the
real EA Desktop folder renamed and its original registered executable path
absent:

| Pre-existing inert probe | Game LSX connection | Result |
|---|---|---|
| None | No | BFN exited before LSX. |
| `EABackgroundService.exe` | No | BFN exited before LSX. |
| `EADesktop.exe` | Yes | Startup replies and fresh EA game-code handoff worked. |
| `EADesktop.exe`, 120-second interactive repeat | Yes | **User confirmed reaching the public hub.** |

The probe is our own .NET executable whose entire program sleeps; it does not
provide EA client IPC, windows/readiness, services or networking. It lives in
`artifacts/diagnostics/process_name_probe`, not the installed EA tree. Its PID,
path and executable/assembly hashes are retained in each process trace. No
**genuine EA Desktop software** was observed in the successful repeat; a
process with the name `EADesktop.exe` was deliberately present. That distinction
must remain explicit. The exact SDK discovery API is not statically confirmed.
The background service is currently stopped and was not observed in the older
successful real-client-assisted run either.

See `bfn_process_name_comparison_summary.json` (`analysis/runtime/bfn_process_name_comparison_summary.json`, local-only),
`bfn_renamed_folder_desktop_probe_interactive.json` (`analysis/runtime/bfn_renamed_folder_desktop_probe_interactive.json`, local-only),
and its `.host.log`. The user confirmation belongs to this run; the earlier
saved screenshot belongs to the earlier real-client-assisted run, not this
repeat. Source/build/reproduction instructions are in
[`tools/process_name_probe/README.md`](../../tools/process_name_probe/README.md).
Both builds completed with zero warnings/errors; validation is now
**105 passed, 5 subtests passed**. The timed test cleaned up its game, host and
probe. The user's renamed folder and the registry were left unchanged.

Remaining: integrate the host/probe lifecycle into normal launching, identify
the precise SDK discovery check, and cover friends/block-list/achievements and
extended play. No game/anti-cheat executable was patched.

## Earlier 2026-10-20 update: standalone game sign-in reached the public hub

The later investigation below supersedes the earlier early-exit diagnosis:

- A fresh direct signed anti-cheat launch, with no captured EA launch tokens,
  reached BFN's **public hub**. The user confirmed sign-in and supplied
  `runtime screenshot` (`analysis/runtime/bfn_standalone_public_hub.png`, local-only).
- Fresh direct launch identifies BFN to LSX as `194814`; the normal EA-created
  launch uses `Origin.OFR.50.0004873`. The diagnostic host now accepts both
  observed identities while preserving AES proof and client-key validation.
- Reporting the unavailable overlay as disabled let direct launches progress
  beyond `IS_IGO_ENABLED`; an overlay-enabled repeat disconnected there.
- The online gate required **`InternetConnectedState connected="1"`**, not the
  previous `"true"`. After that fix the game requested `GetAuthCode`.
- `standalone_launcher/game_auth.py` independently requested fresh, EA-issued
  BFN server codes using the standalone OAuth account. The successful game
  trace records code issuance/forwarding without retaining credential values.
  `standalone_launcher/lsx_session.py` adds local presence state and explicitly
  unsupported downloader-utilization replies. It does not implement XMPP.
- The successful interactive observation lasted **120 seconds**. **EA Desktop
  was not absent for the entire run**: the game auto-started it during SDK
  initialization; the watcher stopped it after a two-second grace period.
  Eliminating that startup remains open. Some zero-grace attempts exited before
  LSX; that timing dependency is not resolved. The user also reports normal
  EA Desktop launches can have initial network timeouts, so a timeout alone
  does not establish a replacement-host failure.

**Renamed-folder negative control:** after the user renamed the installed EA
Desktop folder to `_EA Desktop`, the original executable path was absent.
BFN started but exited at 8.875 seconds without any game LSX connection; no EA
Desktop process was observed. The signed anti-cheat launcher exited 0. The
remaining pre-LSX bootstrap check is unresolved; renaming alone is not a
working solution. See `bfn_renamed_ea_folder_interactive.json` (`analysis/runtime/bfn_renamed_ea_folder_interactive.json`, local-only)
and its `.host.log`. The folder and registry were left unchanged.

Evidence: `bfn_fresh_direct_connectivity_fixed_interactive.json` (`analysis/runtime/bfn_fresh_direct_connectivity_fixed_interactive.json`, local-only)
and its host trace (`analysis/runtime/bfn_fresh_direct_connectivity_fixed_interactive.host.log`, local-only).
The bounded reproducer is `tools/test_bfn_direct_lsx.py`; see the updated
[standalone README](../../standalone_launcher/README.md). Tests after these changes:
**98 passed, 5 subtests passed**. Friends/block-list/achievement requests remain
unsupported; matchmaking and extended play were not independently validated.

## Earlier investigation snapshot (retained for chronology)

Status on **2026-10-20**, before the update above. The objective is a launcher that authenticates, discovers owned games, downloads and installs them, obtains legitimate EA licenses, and starts them **without `EADesktop.exe` running**. That objective is partially met: the standalone account/library/install path works, and one legacy title launched after a fresh independent license renewal. **Plants vs. Zombies: Battle for Neighborville (BFN) is installed and licensed, but an EA-free launch has not been achieved.**

The analyzed desktop build is `13.809.0.6322` under `C:\Program Files\Electronic Arts\EA Desktop\EA Desktop`. The exact staged binary hashes and signatures are in the artifact manifest (`artifacts/manifest.json`, local-only). Static findings come from IDA Pro 9.1/IDALib, with an address-to-evidence map in analysis/EVIDENCE_INDEX.md (`analysis/EVIDENCE_INDEX.md`, local-only). Live tests used the user's owned titles and the unmodified signed game, activation, installer, and anti-cheat binaries. Private credentials, account identifiers, license bodies, and signed download URLs are kept out of the report and runtime traces.

## Current result at a glance

| Area | Implemented and observed | Still open |
|---|---|---|
| Authentication | Independent interactive OAuth/PKCE login, token refresh, logout, local DPAPI storage, EA `pc_sign` construction. | Version changes and broader account/error cases. No public third-party compatibility promise. |
| Library | `getCurrentUser`, paginated entitlements, catalog hydration, reconciliation, install discovery, Windows GUI. Latest protected snapshot: **149 entitlement records, 100 offers, 95 product records, 33 visible active titles**. | Continuous subscription updates and all suppression/subscription edge cases. |
| Downloads | Authenticated just-in-time package lookup, HTTP range ZIP reading, DiP parsing, safe extraction and CRC checks. | General update/repair, patch streams, interruption/resume, broad-title validation. |
| Installation | Full BFN `en_US` selection installed in `E:\Games`; signed Touchup install and update completed. | Broad installer/dependency coverage; BFN's ~19 GB test is not a general installer proof. |
| License/activation | Independent EA-signed OOA license retrieval and local signature verification for MOHPA and BFN; title-specific machine bindings reconstructed. MOHPA cold-license renewal and direct launch worked with EA processes stopped. | Denuvo, additional titles/bindings, BFN's later launch/online handoff. |
| Game launch | Direct DiP launcher selection and `EARtPLaunchCode` generation. BFN signed EA AntiCheat launcher starts the game; independent LSX host completes startup requests in one normal-launch diagnostic. | **No confirmed BFN launch with EA Desktop absent for the whole run.** Main-menu/gameplay validation with the replacement host is pending. |

The older [custom_launcher](../../custom_launcher/README.md) intentionally delegates to `EALauncher.exe`/EA Desktop. It remains an oracle, **not** the final product. The active implementation is [standalone_launcher](../../standalone_launcher/README.md).

## Authentication and owned-library discovery

IDA recovered EA Desktop's `/connect/auth` authorization-code flow, S256 PKCE, redirect handling, `/connect/token` code/refresh forms, and the build-specific `pc_sign` payload, HMAC and machine fingerprint. The standalone WebView2 sign-in host runs this flow without opening or reading EA Desktop's cookie/token cache. OAuth tokens are protected with Windows DPAPI. Refresh and logout are implemented. The full reverse-engineered request map and its static anchors are in [STANDALONE_AUTH_RE.md](STANDALONE_AUTH_RE.md); the current code is in [auth.py](../../standalone_launcher/auth.py), [pcsign.py](../../standalone_launcher/pcsign.py), [machine.py](../../standalone_launcher/machine.py), and [login.py](../../standalone_launcher/login.py).

The main desktop library is **not** the SDK `sdkEntitlements` response. `EABackgroundService.exe` obtains paginated `getLegacyEntitlements` across EA/Epic/Steam storefronts, then batches `getLegacyCatalogDefs` for offer and product data. The standalone [library.py](../../standalone_launcher/library.py) executes the same account-scoped operations with its own token. The latest sanitized library summary (`analysis/runtime/standalone_library_2026-10-17.json`, local-only) records 149 entitlements over two pages, 100 offers, 95 game-product records, and seven catalog batches. The full response is DPAPI-protected in `private/ea_library.dpapi`. The [GUI](../../standalone_launcher/gui.py) showed 33 active titles and their local installation status; it also exposes the raw counts and optional disabled/add-on rows.

The earlier 40-entitlement result in [AUTH_LIBRARY_RE.md](AUTH_LIBRARY_RE.md) was an **earlier account snapshot**. It is not the latest 149-record library. A recent check confirmed the currently saved standalone OAuth token and the protected library snapshot represent the same user/persona. EA Desktop's verbose log masks `UserId` and `PersonaId` as `####`; comparisons against those log strings cannot establish an account mismatch. The separate unmasked socket relay comparison found only an `AvatarId` difference in the generated `GetProfileResponse`, as recorded in bfn_relay_comparison.json (`analysis/runtime/bfn_relay_comparison.json`, local-only).

## Package retrieval and installation

The recovered install flow requests a short-lived `downloadUrl` by offer ID, inspects a remote ZIP/ZIP64 central directory and DiP `installerdata.xml`, chooses locale/progressive content, streams files, verifies CRC and size, and runs the package's signed Touchup. The background service also has differential patch, resume, and repair state machines that are **not yet fully reproduced**. See [DOWNLOAD_INSTALL_RE.md](DOWNLOAD_INSTALL_RE.md), [download.py](../../standalone_launcher/download.py), [remote_zip.py](../../standalone_launcher/remote_zip.py), [manifest.py](../../standalone_launcher/manifest.py), [install.py](../../standalone_launcher/install.py), and [finalize.py](../../standalone_launcher/finalize.py).

The standalone client queried a Battlefield V package of ~98 GB only to inspect its manifest and plan a locale selection; **it did not download/install that game**. BFN was the live installation target. Its archive had 250 entries; the full `en_US` selection contained 166 files and 19,134,479,272 installed bytes. Extraction completed with CRC validation, followed by signed Touchup install and update, both exiting successfully. The registered installation is `E:\Games\Plants vs Zombies Battle for Neighborville`. Details and limitations are in [BFN_ACTIVATION_RE.md](BFN_ACTIVATION_RE.md).

## Licenses, activation, and launch selection

EA's OOA license response contains a signed body, not a license the launcher can invent. The standalone service requests the user's license with its OAuth token and title-specific machine binding, checks the DSA signature locally, and installs the `.dlf` atomically. The title's signed activation library performs the final local validation. The mode-4 machine binding for BFN content ID `194814` was reconstructed from `Activation64.dll`; an EA-signed 577-byte license was obtained and locally verified with EA Desktop stopped. For Medal of Honor: Pacific Assault (MOHPA), the title's older variable-width fingerprint was recovered separately. With its `.dlf` absent, the standalone client obtained a new EA-signed license and direct-launched the game while EA Desktop and its background service were stopped. Game window/process and license persistence were observed; gameplay input was not verified. See [LICENSE_ACTIVATION_RE.md](LICENSE_ACTIVATION_RE.md) and [license_service.py](../../standalone_launcher/license_service.py).

The direct launcher reads the installed DiP manifest, selects its launcher UID, supplies `ContentId` and the date-based `EARtPLaunchCode`, and starts the signed executable. BFN's DiP launcher is `EAAntiCheat.GameServiceLauncher.exe`; using the catalog's game executable override would skip that normal entry path. The activation library accepts the local run-to-play values, but the game has an additional Origin SDK/LSX session dependency. See [launch.py](../../standalone_launcher/launch.py) and [BFN_ACTIVATION_RE.md](BFN_ACTIVATION_RE.md).

## BFN: precise status of the recent live tests

The user previously confirmed BFN reached its main menu from a **normal EA Desktop launch**. The sanitized normal LSX oracle (`analysis/runtime/bfn_normal_launch_oracle.json`, local-only) records its challenge and subsequent SDK requests, including game info, presence, connectivity, social data, and `GetAuthCode`. That confirms the game's normal path, not the standalone result.

Our [diagnostic LSX host](../../tools/probe_lsx_connection.py) binds loopback ports 3216/3217, sends EA's challenge, validates BFN's AES proof, sends `ChallengeAccepted`, derives the version-3 socket key, decrypts requests, and returns account-backed startup replies from [lsx_startup.py](../../standalone_launcher/lsx_startup.py). It does **not** fabricate an online game auth code. An early host bug checked the numeric download content ID (`194814`) against the challenge's `ContentId` element; BFN actually puts its offer ID (`Origin.OFR.50.0004873`) there. That check was fixed. An earlier host log's connection at 0.063 seconds was the test script's own readiness probe, before the game started, and must not be counted as game traffic.

The key controlled results are:

| Test | EA Desktop state | BFN's LSX peer | Observed result |
|---|---|---|---|
| Normal user launch | EA Desktop running normally | EA Desktop | User confirmed main menu; normal request sequence captured. |
| Direct replay of EA-created game environment | Original EA Desktop kept running | EA Desktop | BFN process survived 50 seconds. This does **not** prove EA-free launch or main-menu reach. |
| Direct replay, original desktop stopped | Independent host on 3216/3217; BFN auto-started new EA Desktop children, which the watcher stopped | Independent host | Valid challenge, `GetConfig`, `GetProfile`, first `GetSetting`; then BFN exited. Host trace (`analysis/runtime/bfn_offline_replay_host.log`, local-only) and redacted launch context (`analysis/runtime/bfn_offline_launch_context_replay_v3.json`, local-only). |
| Direct replay with a fresh desktop on redirected ports 13216/13217 | A **new** EA Desktop process was present but could not own 3216/3217 | Independent host | Same early exit after `GetSetting`. Redacted context (`analysis/runtime/bfn_coexist_launch_context_replay.json`, local-only). |
| **Normal EA Desktop launch with its LSX binds redirected to 13216/13217** | Original EA Desktop performed launch coordination and remained running | **Independent host** on 3216/3217 | BFN stayed alive for the full 45-second observation and progressed through game info, install status, repeated profile, presence, and connectivity requests. Host trace (`analysis/runtime/bfn_live_desktop_independent_lsx.log`, local-only). **Main menu was not verified in this diagnostic.** |

These tests separate two dependencies. The LSX replacement now carries substantially more startup traffic **when EA Desktop performs the original launch**. In direct replay, copying the EA-generated environment variables and starting the signed anti-cheat launcher is still insufficient. Having an arbitrary new EA Desktop process running did not rescue that replay. Therefore the remaining early-exit cause is more specific than “BFN merely checks that `EADesktop.exe` exists.” It may involve per-launch state, a one-time token, IPC, process coordination, or anti-cheat/session validation; the exact condition is **not yet established**.

The EA-created process environment contains `EAAccessTokenJWS`, `EAGenericAuthToken`, `EALaunchUserAuthToken`, `EAAuthCode`, `EAConnectionId`, `EALaunchCode`, `EALicenseToken`, `EASecureLaunchTokenTemp`, `OriginSessionKey`, `EALsxPort`, `ContentId`, `EARtPLaunchCode`, and other locale/store/overlay fields. [capture_ea_launch_context.py](../../tools/capture_ea_launch_context.py) captured values **only in memory** for replay; checked-in runtime JSON records names and lengths, never values. Some values may be short-lived or bound to the original desktop's launch state. The copied environment's apparent completeness must not be treated as proof it is valid for an independent launch.

BFN can start `EADesktop.exe` as its child even when the independent LSX port is available. If that new desktop tries to bind port 3216 while our host owns it, EA Desktop may display `EC:10701` (“couldn't connect to port 3216”). That error reflects a test-created listener collision; it does not by itself diagnose the game exit. The live test scripts stop their own processes, and the current post-test check found no BFN/EA Desktop/EAAC process or listener on 3216, 3217, 13216, or 13217.

## Earlier next steps (superseded by the later update above)

1. **Identify the original launch-only state.** Compare the normal EA Desktop `ProcessCoordinator` path with the failed direct replay: environment field producers, lifetime and consumer of launch/auth/license/session codes, process creation flags, and any service IPC. Static anchors are EADesktop-launch.json (`analysis/decomp/EADesktop-launch.json`, local-only), EADesktop-environment-init-disassembly.json (`analysis/decomp/EADesktop-environment-init-disassembly.json`, local-only), and the launch evidence index (`analysis/EVIDENCE_INDEX.md`, local-only). Avoid treating an observed environment variable as sufficient until its server-side or process-side validation is known.
2. **Run controlled one-variable launch comparisons.** Preserve the original desktop's session/launch state while swapping only the LSX peer, then vary launch provenance and token freshness. Capture only process timing, message names, lengths, and outcome. This should locate the first condition that distinguishes the 45-second survivor from the direct replay.
3. **Finish the LSX host for later startup.** The 45-second trace reached `GetPresence` and `SetDownloaderUtilization`, for which the diagnostic host currently sends no answer. Implement supported replies from the signed-in account/session, then cover the normal `GetAuthCode` request through an authorized EA token flow. Do not invent a code or equate local `.dlf` activation with online game authentication.
4. **Establish an EA-free BFN run only with direct evidence.** Keep `EADesktop.exe` absent throughout launch, verify the game reaches its menu, then test actual gameplay/online behavior and cleanup. If signed anti-cheat or EA's online session requires an unavailable proprietary broker, document that boundary precisely instead of claiming success from a process-survival timer.

There has been **no successful BFN menu/gameplay test without EA Desktop**. The last successful 45-second proxy test still had EA Desktop running for the normal launch; it establishes LSX host progress, not elimination of EA Desktop.

## Verification and repository layout

`python -m pytest -q` on 2026-10-20: **70 passed, 5 subtests passed**. The tests cover the standalone implementation; the live BFN diagnostic outcomes above are separate runtime observations. The new diagnostic scripts compile and completed their controlled runs. This folder is not a Git repository, so validation uses file reads, targeted checks, the test suite, and process/port inspection rather than `git status`.

- [REPORT.md](REPORT.md): broad reverse-engineered architecture.
- [AUTH_LIBRARY_RE.md](AUTH_LIBRARY_RE.md), [STANDALONE_AUTH_RE.md](STANDALONE_AUTH_RE.md): login and library details.
- [DOWNLOAD_INSTALL_RE.md](DOWNLOAD_INSTALL_RE.md): package/installer details.
- [LICENSE_ACTIVATION_RE.md](LICENSE_ACTIVATION_RE.md), [BFN_ACTIVATION_RE.md](BFN_ACTIVATION_RE.md): title activation evidence.
- analysis/EVIDENCE_INDEX.md (`analysis/EVIDENCE_INDEX.md`, local-only): addresses and retained analysis artifacts.
- [standalone_launcher](../../standalone_launcher/README.md): current implementation and usage.
- analysis/runtime (`analysis/runtime`, local-only): sanitized live evidence; `private/` contains DPAPI-protected sensitive state and is excluded from the report.
