# Standalone EA authentication, build 13.809.0.6322

## Verdict

Interactive EA account login can be recreated without an EA Desktop process.
The recovered flow is OAuth authorization code with S256 PKCE, plus EA's local
`pc_sign` request signature. The browser/UI and redirect interception do not
depend on EADesktop.exe. Token exchange requires the desktop client's
build-specific client secret.

This is now live-validated. On 2026-10-17 the standalone WebView completed the
authorization-code exchange, saved the resulting token set with Windows DPAPI,
refreshed that token set through the refresh grant, and used the refreshed
access token to execute `getCurrentUser`, `getLegacyEntitlements`, and
`getLegacyCatalogDefs`. No EA Desktop API, process, cookie file, token cache, or
private IPC endpoint participated in those operations.

The protocol implementation is now split into independently testable pieces:

- `standalone_launcher/auth.py` implements PKCE, the authorization URL,
  redirect validation, authorization-code and refresh-token forms, and safe
  redaction;
- `standalone_launcher/pcsign.py` implements the recovered JSON schema,
  canonical compact serialization, HMAC-SHA256 signature, base64url envelope,
  MAC normalization, and the final FNV-1a `mid` calculation;
- `standalone_launcher/machine.py` implements the exact mode-4 machine input;
- `standalone_launcher/bootstrap.py` extracts the version-pinned signing keys
  and OAuth client secret directly into DPAPI-protected storage;
- `standalone_launcher/login.py` performs login, token exchange, protected
  persistence, and refresh; and
- `standalone_launcher/library.py` retrieves identity, entitlements, and
  catalog definitions and protects the complete snapshot with DPAPI.

No running EA process is part of the intended architecture:

```mermaid
sequenceDiagram
    participant L as Custom launcher
    participant W as Embedded WebView
    participant A as accounts.ea.com
    participant S as Secure local credential store

    L->>L: collect machine fields; build pc_sign
    L->>L: generate PKCE verifier/challenge and nonce
    L->>W: open /connect/auth URL
    W->>A: interactive login / remembered web session
    A-->>W: qrc:///html/login_successful.html?code=...
    W-->>L: intercept redirect; return code
    L->>A: POST /connect/token with code, verifier, client credentials
    A-->>L: access, refresh, and optional ID tokens
    L->>S: protect refresh token
    L->>A: later refresh_token grant
```

## Authorization request

The normal UI path builds:

```text
GET https://accounts.ea.com/connect/auth
  ?client_id=JUNO_PC_CLIENT
  &sbiod_enabled=true
  &code_challenge=<base64url(SHA256(verifier))>
  &code_challenge_method=S256
  &redirect_uri=qrc%3A%2F%2F%2Fhtml%2Flogin_successful.html
  &display=junoClient%2Flogin
  &locale=en_US
  &pc_sign=<payload>.<signature>
  &nonce=<decimal value>
  &response_type=code
```

`scope` is optional. The builder can emit `signin` or
`signin dp.client.default` in the branches that request it. Steam Deck adds
`is_sd=true`. Linking uses `/connect/linking/ondevice`; ordinary login uses
`/connect/auth`.

The server-side probes establish two independent validation gates:

- omitting `pc_sign` returns `invalid_request` with the missing-field result;
- a syntactically split but invalid signature returns `invalid_request` with
  the invalid-signature result; and
- token exchange rejects a missing or incorrect client secret as
  `invalid_client`.

Those probes used only fabricated values. No account credential was persisted.

### Redirect handling

EA registers the UI redirect as `qrc:///html/login_successful.html`. The
replacement launcher can register a WebView navigation callback, cancel that
navigation, and parse `code` from its query. The decompiled direct requestor
also changes a returned fragment marker (`#`) to a query marker (`?`), so the
implementation accepts either form. Error results may contain `error`,
`error_code`, and `error_number`.

This QRC URI is only a navigation sentinel. Qt resource handling and an EA
Desktop process are not required for interception.

## Token exchange and refresh

EA sends `application/x-www-form-urlencoded` to:

```text
POST https://accounts.ea.com/connect/token
```

Authorization-code form:

| Field | Value |
|---|---|
| `client_id` | `JUNO_PC_CLIENT` |
| `client_secret` | recovered build credential, supplied privately |
| `code` | code returned by the QRC redirect |
| `grant_type` | `authorization_code` |
| `code_verifier` | original PKCE verifier |
| `redirect_uri` | `qrc:///html/login_successful.html` |

Refresh form:

| Field | Value |
|---|---|
| `client_id` | `JUNO_PC_CLIENT` |
| `client_secret` | recovered build credential, supplied privately |
| `refresh_token` | previously issued refresh token |
| `grant_type` | `refresh_token` |
| `refresh_tos` | optional string `true` |

The response parser requires `access_token` and `expires_in`. It also accepts
`refresh_token` and `id_token`. A standalone launcher should place the refresh
token in Windows Credential Manager or a DPAPI-protected file, retain the PKCE
verifier only until the code exchange finishes, and redact every credential
field before structured logging.

## `pc_sign` wire format

The value is:

```text
base64url_no_padding(compact_json) .
base64url_no_padding(HMAC-SHA256(base64url_no_padding(compact_json), signing_key))
```

The HMAC input is the ASCII payload segment after base64url encoding, without
padding. It is not the raw JSON byte sequence.

EADesktop uses the default `nlohmann::json` object, whose keys serialize in
lexical order. The exact payload schema in this build is:

| Field | JSON type | Recovered source |
|---|---|---|
| `av` | string | Literal `v1`. |
| `bsn` | null | Explicit JSON null in this build. |
| `gid` | unsigned number | First GPU `PNPDeviceID` `DEV_` value, parsed as four hex digits. |
| `hsn` | string | First nonempty `Win32_DiskDrive.SerialNumber`; empty string if none. |
| `mac` | string | Selected adapter MAC as `$` plus lowercase hex with hyphens removed. |
| `mid` | decimal string | FNV-1a 64 of `fingerprint_digest_hex + mac`. |
| `msn` | null | Explicit JSON null in this build. |
| `sv` | string | Signing-key version `v1` through `v4`, selected by environment/key branch. |
| `ts` | string | Application clock formatted `{year}-{month}-{day} {hour}:{min}:{sec}:{ms}`. |

### Adapter selection

`eax::foundation::getBestMacAddress` calls `GetAdaptersAddresses` and tries
three predicates in order:

1. Ethernet (`IfType=6`) or IEEE 802.11 (`IfType=71`) with a globally
   administered address;
2. Ethernet or IEEE 802.11, including a locally administered address; then
3. any adapter with a nonempty physical address.

The selected bytes are formatted as lowercase two-digit hex separated by
hyphens. `pc_sign` then removes the hyphens and prepends `$`.

### Machine fingerprint and `mid`

The `mid` producer is not a Windows MachineGuid read. EADesktop calls its
legacy mode-4 fingerprint routine, digests the resulting byte string with
SHA-1 (its internal algorithm ID `1` maps to the 20-byte DirtySDK hash type),
converts every digest byte to lowercase hex, appends the normalized `mac`, and
runs 64-bit FNV-1a:

```text
fingerprint = legacy_machine_fingerprint(mode=4)
fingerprint_digest_hex = lowercase_hex(SHA1(fingerprint))
mid = decimal(FNV1a64(fingerprint_digest_hex + mac))
```

The exact mode-4 source string is:

```text
BaseBoard.Manufacturer;
BaseBoard.SerialNumber;
BIOS.Manufacturer;
BIOS.SerialNumber;
SYSTEM_VOLUME_SERIAL_AS_8_UPPERCASE_HEX;
VideoController.PNPDeviceId;
CPUID_VENDOR;CPUID_LEAF1_EDX_AS_8_HEXCPUID_LEAF1_EAX_AS_8_HEX;
CPUID_BRAND_WITH_LEADING_SPACES_REMOVED;
```

The line breaks above are only for readability; the actual value is one byte
string. Every displayed line ends in `;`. The four initial WMI values are
first concatenated as UTF-16 and passed through EA's local UTF-8 converter.
The video-controller value is `Win32_VideoController.PNPDeviceId`. The volume
serial is from the volume containing the Windows directory. EA's CPU block
uses CPUID vendor order EBX, EDX, ECX, followed by leaf-1 EDX and EAX. It does
not include leaf-1 ECX in mode 4.

`standalone_launcher/machine.py` implements the collector and serialization.
Its locally produced 40-character SHA-1 value was compared to the initialized
EA process value on 2026-10-17 and matched; the values themselves were not
printed or persisted.

### Signing key selection

The 32-byte HMAC key is recovered locally from an environment/version-specific
encrypted blob. EADesktop selects four nonproduction variants or two production
variants, unwraps the selected value with an embedded AES-256 key and 16-byte
IV, and uses the resulting 32 bytes as the HMAC-SHA256 key. `sv` records the
selected key version.

The extraction is mechanically possible from this exact signed binary. The
implementation keeps the key outside source control and accepts it as a
runtime/build-adapter input. Updating EA Desktop may change the blobs, key
selection, client secret, endpoints, or payload construction; the staged SHA-256
in `artifacts/manifest.json` is therefore the compatibility boundary.

## Live standalone result

The first complete run returned a valid current-user object, 40 legacy
entitlement records, 34 unique product IDs/catalog offers, and 33 game-product
records. The entitlement request fit in one page and the catalog request used
three 16-ID batches. The full account-bearing response is stored only in
`private/ea_library.dpapi`; the non-identifying result is
`analysis/runtime/standalone_library_2026-10-17.json`.

The service's current Akamai edge has a transport-specific problem with the
default TLS 1.3 path on this machine: the connection accepts the request and
then repeatedly renegotiates without returning an HTTP response. TLS 1.2
returns immediately and is pinned for this GraphQL client. This was isolated
with otherwise identical requests and is independent of authentication.

Authentication and the primary remote library feed are no longer blockers.
The next launcher work is store reconciliation, local install discovery,
download manifests and chunk delivery, installation state, license/activation,
cloud saves, and final process launch.

## Static evidence map

| Finding | Address / artifact |
|---|---|
| Authorization URL and UI fields | `EADesktop.exe:0x1406F3EC0`, `0x1406F6000`; `analysis/decomp/EADesktop-auth-url-builder.json` |
| Auth-code redirect parser | `EADesktop.exe:0x1406FE620`; `analysis/decomp/EADesktop-auth-code-requestor.json` |
| Token form and client credentials | `EADesktop.exe:0x1406FA9A0`; `analysis/decomp/EADesktop-token-request-builder.json` |
| `pc_sign` assembly | `EADesktop.exe:0x140388A10`; `analysis/decomp/EADesktop-pcsign-pkce.json` |
| HMAC-SHA256 primitive | `EADesktop.exe:0x14045E250`, `0x140237A00`, `0x140237A50`; `analysis/decomp/EADesktop-pcsign-crypto-core.json` |
| Machine field collector | `EADesktop.exe:0x1403B6250`, `0x1403B2D90`; `analysis/decomp/EADesktop-hardware-collector.json`, `EADesktop-systeminfo-wmi-handlers.json` |
| Best MAC selection and formatting | `EADesktop.exe:0x1404CEAF0`, `0x1404D0AD0`, `0x140456770`; `analysis/decomp/EADesktop-best-mac-callbacks.json`, `EADesktop-best-mac-format.json` |
| Machine fingerprint and FNV derivation | `EADesktop.exe:0x140385870`, `0x140386610`, `0x1401650D0`; `analysis/decomp/EADesktop-mid-salt.json`, `EADesktop-pcsign-field-producers.json` |
| Mode-4 WMI obfuscation and CPU block | `EADesktop.exe:0x140385F20`, `0x140386610`, `0x1407CE000`, `0x1407CE330`; `analysis/decomp/EADesktop-machine-fingerprint-helpers.json`, `EADesktop-machine-fingerprint-obfuscated-strings.json` |
| Algorithm-ID-to-SHA-1 mapping | `EADesktop.exe:0x14045CF90`, `0x14045CAA0`, `0x140232950`; `analysis/decomp/EADesktop-hash-registry-initializers.json`, `EADesktop-dirty-hash-core.json` |
| GPU `DEV_` parsing | `EADesktop.exe:0x1403B36E0`, `0x1403B5B80`; `analysis/decomp/EADesktop-pcsign-gid.json` |
| Field constants | `analysis/decomp/EADesktop-pcsign-constants.json` |

