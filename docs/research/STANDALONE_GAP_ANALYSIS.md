# What is required to remove EADesktop.exe from the launch path

## Later BFN milestone (2026-10-20)

A fresh direct signed anti-cheat launch reaches BFN's public hub using the
standalone LSX host and fresh, independently requested EA game auth codes.
The first proof briefly started real EA Desktop. A later approved test kept
the real installation renamed and used our own inert `EADesktop.exe` process
instead; the user again confirmed reaching the hub, with no genuine EA Desktop
observed. An inert `EABackgroundService.exe` did not suffice. Thus the tested
path no longer needs the actual EA client, but still has a process with its
name. Prototype GUI/CLI integration now supervises that helper and LSX host
until the game exits; normal CLI sign-in and cleanup were verified. The exact
native discovery check and extended play remain open. See
[the updated BFN trace](BFN_ACTIVATION_RE.md#later-2026-10-20-direct-launch-and-independent-online-sign-in)
and [current progress](PROGRESS_REPORT_2026-10-20.md). Earlier observations below
are retained for chronology.

## Result for build 13.809.0.6322

There is no switch or IPC request that moves the full EA launch coordinator
into `EABackgroundService.exe`. A proxy is nevertheless unnecessary for one
confirmed direct-title path: a protected executable with a valid signed cached
license accepts the locally derived `EARtPLaunchCode` and completes its own
ActivationUI flow while every EA client process and service remains stopped.

Authentication and library access are implemented independently: OAuth/PKCE,
QRC redirect validation, token refresh, `pc_sign`, current-user, paginated
entitlements, catalog retrieval, and reconciliation all run without EA
processes. Package lookup, remote ZIP reads, extraction, and DiP touchup are
also implemented and have been exercised on a complete small-game install.
See [STANDALONE_AUTH_RE.md](STANDALONE_AUTH_RE.md).

`EALaunchHelper.exe -noclient` starts the background-service-only mode. That
mode can support content maintenance, but the service does not contain the
desktop client's `LicenseManager` or game `ProcessCoordinator`, so it cannot
replace the client for entitled launches.

## Responsibility matrix

| Operation | EADesktop.exe | EABackgroundService.exe | Consequence when EADesktop is absent |
|---|---:|---:|---|
| Interactive login and token storage | yes | no | Implemented by the standalone WebView2/OAuth flow. |
| Access-token refresh and persona | yes | no | Implemented by the standalone session client. |
| Entitlement and catalog stores | yes | partial copies | Implemented as a lossless protected snapshot and derived model. |
| Download URL and package transfer | requests/controls | yes | JIT lookup, ranged ZIP access, selection, and extraction are implemented. |
| Install/touchup process creation | no | yes | Direct DiP touchup works; broad title coverage remains untested. |
| Cached license use | yes | no | Proven directly through the title's ActivationUI with a valid local license. |
| New/renewed legacy OOA license | yes | no | Independently acquired and launch-tested for MOHPA with the local license absent; BFN's signed license was also acquired with its reconstructed mode-4 binding. |
| Denuvo reactivation/GetGameToken | yes | no | Reactivation chain is missing. |
| Legacy run-to-play launch code | yes | no | Exact local date-code generation is implemented and live-tested. |
| Pre/post-game cloud sync | yes | no | Save synchronization and lock lifecycle are missing. |
| Game/store-proxy process selection | yes | no | Direct DiP launcher selection works; BFN's signed EAAC launcher starts but its game invokes EA Desktop for Origin SDK/LSX. Steam and Epic remain open. |
| Game process monitor and termination | yes | no | Basic process creation works; session lifecycle and post-game work are missing. |

## Why the other local interfaces do not solve it

- Port 3215 receives a browser-origin launch request and broadcasts
  `LocalHostGameLaunchRequest`. With no desktop client subscribed, there is no
  `ClientLauncher` to resolve it and no `ProcessCoordinator` to execute it.
- Ports 3216/3217 are LSX servers implemented by `EADesktop.exe` itself. They
  disappear with that process and authenticate trusted game SDK clients.
- The BGS gRPC `CreateRequest` envelope transports EA cereal messages for the
  operations compiled into BGS. It does not dynamically expose the desktop
  client's license and launch classes.
- Starting a game executable directly remains title-specific. The confirmed
  legacy ActivationUI path needs a valid cached license and the RTP date code.
  Other titles can require a new license, EA AntiCheat, or Steam/Epic handoff.

## Components a true independent implementation would need

1. Its own authorized EA OAuth client and interactive account login.
2. Access-token refresh, persona selection, logout, and secure credential
   storage.
3. Entitlement, subscription, catalog, release/trial, and external-platform
   ownership clients.
4. InstallStore reconstruction and catalog-to-executable resolution.
5. The license-service client for missing, stale, or machine-invalid licenses.
6. Additional title-specific token/auth-code and activation variants.
7. Denuvo/EA AntiCheat and elevation orchestration where required.
8. Steam/Epic linked-account and proxy handoff.
9. Cloud-save locks, manifests, conflict handling, and pre/post-game transfer.
10. Process creation, monitoring, telemetry/session mutation, and recovery.

The installed EA application does not provide a third-party API for these
pieces. The standalone launcher owns its OAuth session. For protected titles it
lets the unmodified signed game runtime validate the license EA already placed
in the standard machine license store; it does not parse or modify that license.

## Transitional baseline and current standalone work

The former transitional path remains an oracle only:

```text
custom launcher
  -> EALauncher.exe -silent
  -> wait for EADesktop.exe broker
  -> submit origin2 game request
  -> game starts while EA Desktop remains in the tray
```

This path is retained as an oracle for request ordering and launch behavior. It
does not satisfy the final requirement.

The standalone implementation now provides:

```text
standalone_launcher/auth.py
  -> PKCE and nonce
  -> /connect/auth URL
  -> QRC redirect validation
  -> authorization-code and refresh forms

standalone_launcher/pcsign.py
  -> recovered payload schema
  -> compact ordered JSON
  -> HMAC-SHA256 payload.signature envelope
  -> MAC normalization and FNV-1a mid primitive

standalone_launcher/download.py + remote_zip.py + install.py + finalize.py
  -> authenticated JIT package lookup
  -> manifest-driven range reads, extraction, and touchup

standalone_launcher/launch.py
  -> installed DiP launcher resolution
  -> exact UTC run-to-play date code
  -> direct process creation with no EA client IPC
```

On 2026-10-19 the CLI launched MOHPA launcher UID `2-2` with only the generated
`EARtPLaunchCode`. The wrapper and ActivationUI accepted the cached signed
license; `EADesktop.exe`, `EALaunchHelper.exe`, `EALauncher.exe`, and
`EABackgroundService.exe` remained absent/stopped. The normal invocation reached
the title's setup UI. Adding its shipped `nolauncher` argument reached the game
window directly with the EA components still stopped. The old full-screen
process did not report a responsive window during the 30-second observation,
so manual gameplay input and a second direct title are the next launch checks.
On 2026-10-19 the standalone OAuth client also fetched a fresh EA-signed OOA
license for MOHPA, verified its DSA signature, and installed it atomically.
The first mode-4 machine binding was signed by EA but rejected by the title;
the exact binding from its valid prior license produced a new license that
survived direct launch. The game's own ActivationUI fingerprint algorithm was
then reconstructed, and the standalone result matched that binding. With the
local `.dlf` temporarily absent, the standalone CLI acquired a fresh signed
license and the game launched directly. Other titles still need per-title
binding analysis. See [LICENSE_ACTIVATION_RE.md](LICENSE_ACTIVATION_RE.md).

On 2026-10-19 the standalone extractor also installed the complete 166-file
Battle for Neighborville selection to `E:\Games` and ran its signed touchup
update successfully. A fresh EA-signed license for content ID `194814` passed
local signature verification. The signed anti-cheat launcher and game executable
were tested with the manifest content ID and local run-to-play code. The game
spawned EA Desktop and exited; its Origin SDK then exchanged LSX challenge,
configuration, profile, and setting messages with the desktop client. The
desktop session returned `Invalid user` for the profile. This title therefore
still requires a standalone Origin SDK/LSX host and a validated game-session
handoff before EA-free gameplay can be claimed. See [BFN_ACTIVATION_RE.md](BFN_ACTIVATION_RE.md).

A loopback diagnostic host sent a fresh LSX challenge and received BFN's
`ChallengeResponse`. The game opened a responsive window and remained running
after EA Desktop and its background service were stopped, but EA Desktop had
already started during initialization. The diagnostic host did not answer the
subsequent SDK requests, and gameplay was not validated.
