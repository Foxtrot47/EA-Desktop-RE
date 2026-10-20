# EA custom launcher: implementation specification for build 13.809.0.6322

## Objective and compatibility boundary

The target architecture is a **standalone launcher**. Our process will own
login, token refresh, library/catalog retrieval, install/update/repair,
licensing, activation, cloud saves, and final game process creation without an
EA Desktop process. The current brokered launcher is retained as a runnable
baseline and protocol oracle while those subsystems are replaced.

This boundary is selected from static evidence, not convenience. The other two
local interfaces are private authenticated protocols:

- `EABackgroundService.exe` exposes a TLS gRPC transport whose protobuf body is
  an opaque EA cereal message. The inner types and URLs are version-coupled.
- The LSX game SDK endpoint authenticates a game client with an `EALS`
  challenge/response and then checks SDK/product metadata. It is a game trust
  boundary, not a general launcher API.

The standalone design recreates requests rather than copying the installed
client's cookies or token cache. Build credentials and signing keys are supplied
through a private, protected bootstrap boundary and are never logged.

### Current standalone boundary

This build cannot complete an entitled launch with only
`EABackgroundService.exe` running. IDALib establishes that the game
`ProcessCoordinator`, `LicenseManager`, access-token/auth-code retrieval,
Denuvo reactivation, pre/post-game cloud sync, and final monitored process
creation are compiled into `EADesktop.exe`. The background service's process
creation code belongs to content installation and touchup. Its IPC surface does
not contain an equivalent license-and-launch service.

The runnable legacy prototype still cold-starts the EA broker with
`EALauncher.exe -silent`. That path is transitional. Authentication request
construction, PKCE, redirect parsing, token forms, and `pc_sign` serialization
and signing are now implemented independently under `standalone_launcher/`.
See [STANDALONE_AUTH_RE.md](STANDALONE_AUTH_RE.md) for the recovered login
protocol and `STANDALONE_GAP_ANALYSIS.md` for the full replacement roadmap.

## Process architecture

```mermaid
sequenceDiagram
    participant CL as Custom launcher
    participant EL as EALauncher.exe
    participant ED as EADesktop.exe
    participant ID as Identity services
    participant CS as Content stores
    participant BG as EABackgroundService
    participant LM as LicenseManager
    participant G as Game/proxy

    CL->>EL: origin2://game/launch?contextType=OFFER&id=...
    EL->>ED: start/update-aware handoff
    ED->>ID: restore or display login; obtain/refresh access token
    ED->>CS: join entitlement + catalog + install records
    ED->>LM: launch check and cached/new license request
    LM-->>ED: license status or launch error
    ED->>BG: resolve current installed state when needed
    ED->>G: cloud sync, elevation/anti-cheat/store proxy, process start
    G-->>ED: termination and exit status
    ED->>CS: post-game cloud sync and state update
```

The signed binary inventory and hashes are in `artifacts/manifest.json`. The
addresses below are image virtual addresses from those exact files and are not
portable to another EA Desktop build. `analysis/EVIDENCE_INDEX.md` maps each
major claim to its decompilation artifact.

## Supported public launch grammar

Windows registers `origin:` and `origin2:` to `EALauncher.exe "%1"`. The exact
`origin2` parser is `EALaunchHelper.exe:0x1400DD910`.

### Commands

| Command | Parser result | Intended use |
|---|---:|---|
| `game/launch` | 1 | Resolve and launch a title. |
| `library/open` | 2 | Open the library; also a safe way to request visible login. |
| `store/open` | 3 | Navigate to a store target. |
| `store/checkout` | 4 | Navigate to checkout. |

Unknown commands log `Unsupported origin2 protocol command` and do not create a
valid action.

### Query fields

| Field | Accepted value / behavior |
|---|---|
| `contextType` | `OFFER`, `MASTERTITLE`, `PAGE`, or `SLUG`. |
| `id` | One value or a comma-separated value list. Interpretation depends on `contextType`. |
| `offerIds` | Additional comma-separated offer IDs. |
| `rtpfile` | Run-to-play file associated with `game/launch`. |
| `cmdParams` | Additional game command line. It must be URL encoded as one query value. |
| `trackingId` | Optional launch/store telemetry correlation value. |
| `clientPage` | Optional client navigation context. |

Examples:

```text
origin2://library/open
origin2://game/launch?contextType=OFFER&id=Origin.OFR.50.0004343
origin2://game/launch?contextType=SLUG&id=game-slug&cmdParams=-language+en_US
```

The launcher prototype intentionally emits one ID per request. It does not use
`rtpfile`, `offerIds`, or store checkout because those paths add no value for an
installed-game UI.

Partner stores use separate registered shims. `steam2ea:` targets
`EASteamLauncher.exe`; `link2ea:` targets `Link2EA.exe`. Their parser accepts
fields including `cmdParamsBase64`, `source`, `AUTH_PASSWORD`, `platformToken`,
`entitlement_source`, and `locale`. Those values belong to store-to-EA handoff
and should not be fabricated by this launcher. EA Desktop can redirect an
entitled Steam/Epic title to its correct proxy after resolving ownership.

## Login and session state

The full reverse-engineered request and state-machine detail is in
[AUTH_LIBRARY_RE.md](AUTH_LIBRARY_RE.md).

EA Desktop has three relevant entry states:

1. A remember-me cookie may be restored by
   `CookieJar::restoreRememberMeCookiesFromFile`.
2. EA Desktop sends an authorization-code request to
   `https://accounts.ea.com/connect/auth`. A valid restored cookie permits a
   direct, no-input redirect; otherwise CEF displays the credential UI.
3. EA Desktop exchanges the code at `/connect/token` using S256 PKCE. The
   identity layer can also use the refresh-token grant. The response parser at
   `EADesktop.exe:0x1406FB8E0` requires `access_token` and `expires_in`, with
   optional `refresh_token` and `id_token`.

Authentication is not complete until persona loading succeeds. Account-scoped
content synchronization begins after the state becomes authenticated. Normal
service traffic then carries `Authorization: Bearer ...`; refresh logic retries
when the short-lived access token expires.

Controlled logout removes the remember-me cookie and the protected `AI`/`PI`
identity caches, clears EADesktop's entitlement view, and causes BGS to unload
its authenticated session. It does not erase BGS's account-keyed persistent
Nucleus/catalog cache. On the next successful login, BGS can publish that cached
library immediately while the fresh entitlement and catalog queries run.

The embedded `getCurrentUser` operation requests account country, underage and
ban state, personas, highest/recent subscription, and active Steam/Epic
subscriptions. This explains why persona and subscription state are populated
between identity authentication and the final library view.

For the standalone launcher, login is an owned protocol state. It generates
PKCE and `pc_sign`, hosts the official account page, intercepts the QRC redirect,
exchanges the code, protects the refresh token, and then loads user/persona
state. The complete recovered request and implementation boundary are in
[STANDALONE_AUTH_RE.md](STANDALONE_AUTH_RE.md).

## Library reconstruction

EA's library is not one response. The client joins three stores:

| Store | Key data |
|---|---|
| Entitlement | Account ownership/status, product ID, entitlement type/source, grant and termination dates, use count. |
| Catalog | Offer/content/software/master-title IDs, title/slug, executable, arguments, locale, download metadata, release rules, external-store association. |
| Install | Software ID, base install path, executable path/check, installed version/locale, dependencies, install status and detailed state. |

The normal desktop owned-library feed is the paginated
`getLegacyEntitlements` GraphQL operation in `EABackgroundService.exe` at
`0x14038D210`. It requests `ACTIVE` and `DISABLED` entries for `EA`, `EPIC`, and
`STEAM`, follows the `next` cursor, and then hydrates product/offer IDs with
`getLegacyCatalogDefs`. The `/me/sdkEntitlements/entitlements` handler at
`EADesktop.exe:0x14054DFA0` serves the game SDK/LSX path and must not be used as
the model for the main library. `getLegacyCatalogDefs` returns launch/install metadata,
including `offerId`, `contentId`, `primaryMasterTitleId`, `gameLauncherURL`,
`executePathOverride`, `executeParameters`, `installationDirectory`,
`dipManifestRelativePath`, download type/version, and partner IDs.

### Implemented local library strategy

The current launcher builds a useful installed-game view without account
credentials:

1. Enumerate Windows uninstall registrations in native and WOW64 views.
2. Keep EA-published entries and entries whose path appears in an EA launch log.
3. Correlate `workingDirectory[...] offer[...] content[...]` records with the
   registered install root.
4. Overlay user-maintained offer/slug/master-title mappings from
   `%LOCALAPPDATA%\EA Custom Launcher\library.json`.
5. Launch only when a mapping is known. Unknown identifiers remain visibly
   unmapped rather than guessed.

This discovers installed titles. It cannot enumerate every owned but uninstalled
title because that requires the authenticated Entitlement and Catalog stores.
A future full-account view needs an authorized EA OAuth/API client or access to
the already-reconciled content-store IPC messages. Reading the protected EA
caches or borrowing the client's bearer token would make the implementation
brittle and unsafe.

## Background-service IPC

`EABackgroundService.exe` uses TLS certificates embedded as Qt resources:

```text
:/certs/ipcclient.crt
:/certs/ipcserver.pem
:/certs/ipcserver.key
```

The service port is dynamic and is recorded with the service PID in
`backgroundservice.ini`. The exact outer protobuf descriptor was recovered from
file offset `0xEBC280` in the captured service binary and is preserved as
`analysis/protocol/Server.proto`:

```proto
message BinaryMessage { bytes messageData = 1; }
service GrpcServer {
  rpc CreateRequest(BinaryMessage) returns (google.protobuf.Empty);
  rpc GetSubscriptions(google.protobuf.Empty) returns (BinaryMessage);
  rpc SubscribeEvent(BinaryMessage) returns (stream BinaryMessage);
}
```

The descriptor is 365 bytes and parses as proto3. The RPC paths are:

```text
/eax.services.ipc.GrpcServer/CreateRequest
/eax.services.ipc.GrpcServer/GetSubscriptions
/eax.services.ipc.GrpcServer/SubscribeEvent
```

The protobuf is only an envelope. `messageData` contains EA's
`eax::foundation::messaging::AnyMessage` / `PackedAnyMessage`, serialized with
`cereal::BinaryInputArchive`. `EABackgroundService.exe:0x1405E4DA0` rejects an
invalid serialized request, `0x1405E5FF0` parses subscription type URLs and
rejects an empty subscription list, and `0x1405E56B0` serializes the available
subscription response. A named-pipe implementation uses a related
`PipeEnvelope` containing `messageData`, `requestId`, and subscription URLs.

A complete direct client would need to reproduce all of the following for each
EA release:

- the TLS trust and client identity behavior;
- cereal's binary ABI and EA's `AnyMessage` envelope;
- every request/event C++ type URL and field order;
- request IDs, acknowledgement lifetime, and subscription semantics;
- service/client version checks and privilege expectations.

That is a costly compatibility layer with no advantage for basic launching.
The prototype records the protocol for analysis but delegates mutations to EA
Desktop.

## LSX game SDK boundary

EA Desktop listens on the fixed game SDK port 3216, with 3217 as an alternate.
The available LSX surface includes `QueryEntitlements`, `QueryOffers`,
`QueryContent`, `GetAllGameInfo`, `GetGameInfo`, `GetAuthToken`,
`GetAccessToken`, `GetAuthCode`, `StartDownload`, `DownloadContent`,
`RepairGame`, `RemoveContent`, `RequestLicense`, and `InvalidateLicense`.

Those method names do not make it a public launcher API. Authentication is
performed before dispatch:

- `EADesktop.exe:0x141116390` creates a 16-byte digest seeded with
  `GetTickCount`, sends its hex form as an `EALS` challenge, and labels the
  connection release channel.
- `0x141115D90` uses `RijndaelEncryptor` helpers to decrypt/compare the response,
  then calls `0x141116A00` to extract and validate game/product/version data.
- `0x141117650` performs the additional required-code check when that mode is
  enabled.
- `0x141114430` rejects failed authentication and unsupported SDK versions,
  then registers the authenticated socket and request callbacks.

The LSX endpoint grants games narrowly scoped access to account and content
operations. A generic launcher impersonating this handshake would depend on
private game SDK material and could change the authorization semantics. It is
therefore excluded from the implementation.

## Localhost HTTP bridge

`EALocalHostSvc.exe` listens on `127.0.0.1:3215`. The launch handler at
`0x140055570` parses `offerIds`, constructs a `LocalHostGameLaunchRequest`, and
initially returns `GAME_LAUNCH_PENDING`. The IPC response handler at
`0x140054B00` maps an accepted request to `/game/launch/status`; malformed or
rejected input maps to `ERROR_INVALID_PARAMS`.

The HTTP service authenticates the caller's Origin:

1. Parse/normalize the Origin host.
2. Accept a configured local/allowed origin or begin remote validation.
3. For a remote origin, `0x1401C8810` issues
   `GET https://<origin>/origin/validate` and waits for the encrypted response.
4. Reject invalid callers with HTTP 403 and
   `{"error":"NOT_AUTHORIZED"}`.

Responses identify `Server: OriginClient-LocalHost`, set the allowed origin,
disable caching, and use `text/plain`. Directly calling port 3215 from a desktop
process is not a stable shortcut because the browser-origin trust check is part
of the design.

## Download, install, update, and repair

EA Desktop requests content work through the background service. The service
does not accept an offer ID blindly:

1. `ContentInstallComponent::Impl::verifyInstallRequest` at
   `EABackgroundService.exe:0x1402B18F0` joins the request to an internally
   installable entitlement, validates base-game/DLC parent relationships, and
   rejects missing ownership.
2. `prepareJob` at `0x140299D60` waits for/refetches entitlement state and
   resolves software/catalog metadata.
3. A GraphQL `downloadUrl` request supplies offer, build/CDN, locale, and
   patch-from-version inputs. Returned signed URLs describe full packages,
   sync packages, or known-version patch streams.
4. The state machine obtains the content and DiP manifests. DiP uses
   `__Installer\installerdata.xml` and catalog `dipManifestRelativePath` /
   `installerPath` fields.
5. It chooses a full transfer or KVP/KPP/KPS differential plan, validates patch
   metadata, checks disk space, preallocates output, schedules local-copy and
   remote chunks, and journals progress for resume.
6. It validates CRC/checksum data, sanitizes target paths and permissions, runs
   the touchup/installer, maps its exit status, installs dependencies, and
   persists the final InstallStore record.

The InstallStore serializer at `EABackgroundService.exe:0x14044CF60` writes
fields such as `baseSlug`, `supportedLocales`, `dependencies`, `installInfos`,
and `installStatus`. The V1 deserializer at `0x140445290` reads
`baseInstallPath`, `executablePath`, `installedVersion`, `installedLocale`,
`detailedState`, `previousInstallStatus`, `localInstallProperties`, elevation,
and uninstall metadata.

The outer `CATS2`, `IS`, and `CONF-production` files begin with a 64-character
hex prefix followed by high-entropy protected data. Their storage wrapper and
versioning make them unsuitable as the launcher's primary database.

The standalone launcher implements the package path without the BGS message
ABI. `standalone_launcher/download.py` retrieves an authenticated JIT package
descriptor, `remote_zip.py` reads the remote central directory and selected
members, `manifest.py` builds a locale/chunk install selection, `install.py`
performs resumable verified extraction, and `finalize.py` runs the signed DiP
touchup. The first range probe fetched about 2.3 MB of metadata from a 97.97 GB
Battlefield V archive. The complete validation used the roughly 3.46 GB MOHPA
package and finished extraction and touchup with exit code zero. See
[DOWNLOAD_INSTALL_RE.md](DOWNLOAD_INSTALL_RE.md).

The GUI currently discovers completed installs, while package lookup, planning,
extraction, and touchup are exposed as command-line stages. Update, repair,
uninstall, dependency policy, and crash-safe UI job control still need to be
joined into one install controller.

## Activation and launch state machine

Once the URI reaches EA Desktop, `ClientLauncher::requestLicenseAndLaunch` at
`EADesktop.exe:0x1407897C0` drives the secure part of launch:

```text
Resolve identifier
  -> join entitlement, catalog, and install records
  -> check release/trial/playability/install/executable state
  -> obtain or refresh account access token
  -> read cached license
     -> if invalid/missing: request new license
     -> if protected title needs it: Denuvo reactivation/GetGameToken helper
  -> construct executable, working directory, arguments and locale
  -> choose direct executable, anti-cheat launcher, Steam proxy, or Epic proxy
  -> pre-launch cloud synchronization
  -> create/elevate process and monitor it
  -> record exit and duration
  -> post-launch cloud synchronization
```

`LicenseManager::requestLicense` at `0x140797AF0` distinguishes cached and new
license results and allows a specific elevated-executable continuation case.
`0x14079FC70` handles Denuvo reactivation. `GetGameToken.exe` supplies the game
token through local synchronization primitives; it has no independent network
client. The account-authorized license request remains in EA Desktop.

The legacy OOA title path has now been resolved further. MOHPA's `mohpa.exe`
imports `Activation.dll` ordinal 100. The wrapper creates an inheritable 4 KB
mapping, writes `WrappedExecutablePath`, process/content fields, and starts
`ActivationUI.exe /SMOID=<decimal handle>`. This `SMOID` block is private
wrapper-to-ActivationUI state; it is separate from run-to-play authorization.

`ActivationUI.exe:0x405E10` reads `EARtPLaunchCode` as an unsigned decimal and
accepts a checksum for UTC yesterday through three days ahead. For calendar
date `(year, month, day)`, both ActivationUI and
`EADesktop.exe:0x1404DACA0` compute:

```text
x = uint32(104729*year XOR 350377*day XOR 224737*month)
code = uint32(x XOR (x << 16) XOR (x >> 16))
```

When the code validates, ActivationUI continues locally. Otherwise it invokes
the `origin2://game/launch/...` fallback that starts EA Desktop. A live minimal
environment test established that this one generated variable is sufficient
for MOHPA when its valid signed `.dlf` is already cached. No account token,
license value, EA IPC endpoint, or proxy process was supplied.

`GetGameToken.exe` is for the separate new-license/reactivation path. It opens
an inherited 4 KB mapping whose decimal handle is its command line, loads
`dbdata.dll`, calls `getTableData`, and writes `GameToken` back to the mapping.
EA Desktop waits up to 30 seconds and then performs the network license flow.
The persistent installation does not contain `dbdata.dll`, so its provisioning
and the license-service request remain open.

Expected launcher-visible errors include unmapped ID, login required,
entitlement unavailable/expired, game not installed, update required,
executable absent, missing/stale license, reactivation failure, external store
missing, and a game process that exits immediately. The standalone modules now
resolve installed DiP launchers and report local manifest/executable errors.
License renewal and external-store errors remain unimplemented.

## Prototype file and state model

`custom_launcher/ea_custom_launcher.py` provides:

- `status`: signed-component path, process presence, and fixed-port probes;
- `discover`: uninstall-registry discovery plus historical offer correlation;
- `configure`: persistent offer/slug/master-title mapping;
- `uri`: exact URI construction, dry-run by default;
- `launch`: launch by direct identifier or configured display name.

`custom_launcher/gui.py` provides a local installed-game table, mapping editor,
EA sign-in/library button, and explicit launch button. The config schema is:

```json
{
  "schema": 1,
  "games": [
    {
      "name": "Example",
      "install_location": "E:\\Games\\Example",
      "context": "OFFER",
      "id": "Origin.OFR.50.example",
      "cmd_params": "-language en_US"
    }
  ]
}
```

The launcher calls `EALauncher.exe` as an argument-vector subprocess, so the URI
is not interpreted by a command shell. URI generation percent-encodes all query
values. Dry-run remains the CLI default; execution requires `--execute` or an
explicit GUI button click.

The independent path is implemented by `standalone_launcher/launch.py` and
`tools/launch_standalone_game.py`. The standalone GUI resolves an installed
title from its DiP manifest and launches the preferred non-configuration entry.
`--launcher-uid` selects another manifest entry explicitly. On 2026-10-19 this
path launched MOHPA UID `2-2` with EA Desktop and the background service
stopped. The default title path opened `mohpa_setup.exe`; its native
`nolauncher` argument then reached the MOHPA game window directly. The resolver
now applies that content-ID/launcher-UID compatibility argument automatically.

## Next implementation increments

1. Manually validate input in the MOHPA gameplay window, then validate the
   cached-license path on a second small direct EA title.
2. Reconstruct new-license acquisition and `dbdata.dll` provisioning without
   retaining or exposing license/token contents.
3. Join download, extraction, touchup, repair, and uninstall stages into the GUI.
4. Extract product art from installed executables or EA's non-secret local web
   cache and display it with a cache provenance record.
5. Add launch-history timestamps and duration from sanitized local logs.
6. Package the Python UI with a manifest and code signing for normal desktop
   use.
7. Re-run the targeted IDALib scripts after every EA update and gate protocol
   assumptions by the artifact SHA-256 in `artifacts/manifest.json`.
