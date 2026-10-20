# EA package resolution and install metadata

## Scope and evidence boundary

This note covers `EABackgroundService.exe` from EA Desktop
13.809.0.6322. Its SHA-256 is recorded in `artifacts/manifest.json`. Addresses
are build-specific image virtual addresses.

The standalone implementation now resolves an entitled offer into its
short-lived content URL, reads the remote ZIP central directory, and retrieves
the two small install manifests with bounded HTTP range requests. It has not
downloaded or installed a game payload.

## JIT package URL request

The query literal is initialized at `0x140018E70`. The request builder at
`0x140357B80` constructs an EA GraphQL `Query`, adds
`Authorization: Bearer <access token>`, and supplies these variables:

| Variable | Native behavior |
|---|---|
| `offerId` | Required owned offer ID. |
| `cdnOverride` | Optional CDN selector. Omitted unless its optional value is present. |
| `buildId` | Optional staged/specific build ID. |
| `preferredLanguage` | Empty by default; used for known-version language streams. |
| `patchFromVersion` | Empty by default; installed version for differential planning. |
| `fetchSyncPackage` | Controls `syncUrl` and `syncArchiveSize`. |
| `enableVersionUpdate` | Controls the known-version update plan and streams. |

The exact operation is:

```graphql
query JitUrlRequest(
  $offerId: String!
  $cdnOverride: String
  $buildId: String
  $preferredLanguage: String = ""
  $patchFromVersion: String = ""
  $fetchSyncPackage: Boolean!
  $enableVersionUpdate: Boolean!
) {
  jitUrl: downloadUrl(offerId: $offerId, cdnOverride: $cdnOverride, buildId: $buildId) {
    url
    archiveSize
    syncUrl @include(if: $fetchSyncPackage)
    syncArchiveSize @include(if: $fetchSyncPackage)
    knownVersionUpdateInfo(
      preferredLanguage: $preferredLanguage
      patchFromVersion: $patchFromVersion
    ) @include(if: $enableVersionUpdate) {
      planUrl
      planArchiveSize
      baseStreamUrl
      baseStreamArchiveSize
      languageStreamUrl
      languageStreamArchiveSize
    }
  }
}
```

The response parser at `0x1403584A0` reads `/data/jitUrl/url`,
`archiveSize`, optional sync fields, and `knownVersionUpdateInfo`. It treats a
zero-byte archive as an error and maps GraphQL error codes including
`unauthenticated`, `forbidden`, and `bad_user_input` into install-flow errors.

`standalone_launcher/download.py` reproduces this request and keeps every URL
field out of dataclass representations and sanitized summaries. Signed URLs are
short-lived bearer material and are not written to disk.

## Remote archive format

`GetArchiveInfo::Run` at `0x140327610` calls EA archive range helpers and then
parses a ZIP central directory. Its explicit failure string is
`Failed to parse zip central directory`. `GetContentManifest::Run` at
`0x14032B670` searches the resulting entry list for `installerdata.xml`, then
reads only that entry by its stored file offsets.

`standalone_launcher/remote_zip.py` implements the same boundary with a
seekable block-cached HTTP range reader and Python's ZIP/ZIP64 parser. It:

- requires HTTP 206 and validates `Content-Range`;
- caps total fetched bytes and manifest size;
- parses the central directory from the archive tail;
- reads a selected member through its local header;
- checks the member CRC through `zipfile`;
- never logs or persists the signed archive URL.

## Live Battlefield V verification

The independently refreshed OAuth session resolved owned offer
`Origin.OFR.50.0004343` without an EA Desktop request. The result described an
Akamai archive of 97,971,816,426 bytes.

The first manifest probe used two range requests totaling 1,263,594 bytes:

| Property | Value |
|---|---:|
| ZIP entries | 277 |
| DiP member | `__Installer/installerdata.xml` |
| DiP size | 35,313 bytes |
| DiP SHA-256 | `2D053C55C6C69974E2E7F96673D2128C3FF6297B983E65DBA05F074CC797127F` |
| DiP root | `DiPManifest` |

The archive's central directory reports:

| Property | Value |
|---|---:|
| Total uncompressed bytes | 98,013,809,814 |
| Total compressed bytes | 97,971,737,270 |
| Stored entries | 196 |
| Deflated entries | 81 |
| Encrypted entries | 0 |

The stored entries include the large Frostbite CAS files. This means a direct
installer can stream most payload bytes to their final files without a second
full-size temporary archive. Deflated entries still require sequential inflate
and CRC verification.

The DiP document points to `/Support/mnfst.txt`. That member is 14,096 bytes,
contains 278 quoted paths, and has SHA-256
`D41A8AAF9B96E249C9BF36ECE23B08CDE6CF67B8F93863EE695A67108536D346`.
The extra path includes generated installer state such as
`__Installer/InstallLog.txt`; the list is the authoritative removal/repair file
set rather than a simple copy of central-directory entries.

Both manifests are stored DPAPI-protected under
`private/package_metadata/Origin.OFR.50.0004343/`. The adjacent
`metadata.json` contains hashes, sizes, and request counts but no access token
or signed URL.

## DiP install and launch metadata

The live DiP manifest declares:

- game version `1.0.78.11385`;
- Windows 6.1 minimum and a 64-bit OS requirement;
- 14 supported locales and locale-specific file filters/EULAs;
- 44 progressive chunks, split between required and recommended content;
- differential updates, mandatory updates, dynamic content, language changes,
  and Origin/EA in-game API support;
- touchup executable `/__Installer/touchup.exe`;
- install, update, and repair argument templates using `{locale}` and
  `{installLocation}`;
- two runtime launcher variants: trial and full game;
- the full-game launcher path resolves from the Battlefield V registry install
  root to `EAAntiCheat.GameServiceLauncher.exe`.

## Native archive filtering and dry-run planner

`FilterArchiveFiles::Run` at `0x14030CCC0` receives the ZIP entry vector and
the parsed DiP model. Its recovered behavior establishes these rules:

- `app.downloadAllLanguages` bypasses locale filtering;
- otherwise `0x140312A50` chooses an exact locale, treats `zh_TW` and `zh_HK`
  as a fallback group, tries a two-character language match, and finally tries
  English;
- `0x140314170` compiles the selected and non-selected locale patterns and
  marks archive entries for inclusion/exclusion;
- entries matching `.*\.eaPatch.*` are always marked out of the package file
  selection;
- the progressive `required`/`recommended` labels are not used by this native
  filter to remove recommended files from a normal full install.

`standalone_launcher/manifest.py` parses this DiP data and reproduces the
locale and `.eaPatch` selection. It also exposes an explicitly labelled
required-set estimate for studying progressive readiness. Files not assigned
to a progressive chunk are retained because BFV leaves activation and install
metadata outside those chunks.

`tools/plan_package_install.py` resolves a fresh JIT URL, parses only the live
central directory, loads the protected DiP metadata, and prints a URL-free
plan. The 2026-10-18 live BFV results for `en_US` were:

| Selection | Files | Compressed payload | Installed bytes |
|---|---:|---:|---:|
| Native-style full install | 251 | 97,971,281,538 (91.243 GiB) | 98,011,495,921 (91.280 GiB) |
| Progressive required-set estimate | 80 | 18,664,024,056 (17.382 GiB) | 18,673,609,978 (17.391 GiB) |

The full plan excludes 26 non-English locale files totaling 455,732 compressed
bytes. It has 79,156 bytes of ZIP framing outside selected and locale-filtered
payloads. The required-set estimate omits 171 recommended files totaling
79,307,257,482 compressed bytes. Five retained files are outside every
progressive chunk: two English support documents, `Core/Activation.dll`,
`Core/Activation64.dll`, and `Support/mnfst.txt`.

The next implementation layer is the extraction engine. It must validate every
target path, stream each selected ZIP entry with resumable journaling, verify
size and CRC, and only then invoke touchup with the recovered argument
template. Actual installation remains an explicit title-and-destination
operation because it writes tens of gigabytes, runs an installer, and changes
machine state.
