# Legacy OOA license renewal without EA Desktop

This analysis covers the installed EA Desktop `13.809.0.6322` build and one
owned small title, Medal of Honor: Pacific Assault (content ID `1019521`). The
standalone client now obtains an EA-signed renewal and launches that title with
`EADesktop.exe` and `EABackgroundService.exe` stopped. The game still runs its
unmodified local Activation/ActivationUI license validation. Gameplay input has
not been verified in the old full-screen title.

## Request and response

The license path from `sub_1407A08D0` into `sub_1407B1610` and
`sub_1407B2120` constructs a GET to
`https://gateway.ea.com/proxy/access/licenses` with `contentId`, `machineHash`,
and `userId` query parameters. It sends `Authorization: Bearer <access token>`
and `User-Agent: OOA/5.02.21`. The URL builder is `sub_1407AD780`. A separate
requester-concurrency POST uses `X-Requester-Id`; that header does not belong to
the license GET.

The successful response is binary, with a base64 `X-Signature` header.
`sub_1407B39A0` reads both; `sub_1407B1350` decodes the signature and body for
internal storage. The on-disk `.dlf` format is a 64-byte slot containing the DER
DSA signature, zero padding in that slot, one zero byte, then the signed binary
body. `sub_1407AE100` parses the DER signature and verifies SHA-1 of the body
using the public DSA parameters embedded in EA Desktop. The key is public
verification material, stored in `standalone_launcher/ooa_public_key.json`.
The standalone CLI verifies that signature before installing a response and
DPAPI-protects the previous `.dlf` before an atomic replacement.

The body is AES-128-CBC ciphertext with a zero IV and PKCS#7 padding in this
build. `sub_1407ACB90` decrypts it and parses the XML license. This was used
only for an in-memory comparison during analysis; no plaintext body, embedded
decryption key, account ID, or machine hash is retained in the report. The
parsed fields include `CipherKey`, `MachineHash`, `ContentId`, `UserId`,
`GrantTime`, and `StartTime`. The validator compares the machine hash to a local
recalculation, checks time bounds, and deletes a locally invalid license.

## Machine-binding discrepancy and live test

`sub_14079EAB0` selects a machine-hash algorithm from title metadata and
falls back to algorithm 4 when no selector can be read. `sub_1407C0E70`
produces the hash for the selected mode. Its call site passes a fixed-width
lowercase formatter for mode 4 and a variable-width per-byte formatter for
earlier modes (`sub_1407C09B0`). The exact mode used when the existing MOHPA
license was originally granted is not established.

The first independent request used the mode-4 40-character hash. EA returned
HTTP 200 and a valid signature; the decrypted `ContentId` and `UserId` matched
the existing license, but `MachineHash` did not. The old valid license had a
37-character all-hex binding. The game rejected and removed the new `.dlf` and
opened ActivationUI's sign-in window. The old file was immediately restored
from its encrypted backup.

A second request used the exact binding from the existing valid license. EA
returned HTTP 200 with a signed 512-byte body, and the decrypted account,
content, and machine fields matched. This produced a 577-byte `.dlf` that
remained in place after direct game launch. `mohpa.exe` stayed alive after both
10-second and 8-second observations, with no EA client or background service
process running. The first test restored the old file.

Further IDALib analysis of the title's own `ActivationUI.exe` established its
fingerprint routine at `0x4310D0`, SHA-1 formatter at `0x431700`, and local
machine-hash cache at `0x431AB0`. It concatenates baseboard and BIOS WMI
fields, the system-volume serial, the primary display device ID, and CPUID
vendor/features/brand. Its SHA-1 formatting uses `%x` for each byte without
zero padding. `standalone_launcher/ooa_machine.py` now reproduces that value
from Windows directly; its result exactly matched the existing signed license
without reading any `.dlf` at runtime. A controlled cold-license test removed
the local `.dlf`, used the packaged standalone CLI to obtain a fresh signed
file, and directly launched MOHPA. The file persisted and the game process
remained alive after 10 seconds, with no EA process started. The new file is
left installed. This tests an absent local license on the current installed
title, not a clean-machine first install or gameplay input. Redacted
observations are in
`analysis/runtime/standalone_license_refresh_2026-10-19.json`.

The library GUI now exposes **Renew license** and automatically acquires a
missing MOHPA `.dlf` when **Launch selected** is used. Both GUI paths completed
under Tk's event loop; the missing-license path started the installed game.

The earlier confirmed binding remains DPAPI-protected in
`private/ooa_machine_bindings.dpapi` as a regression reference. MOHPA renewal
derives its binding dynamically and does not need that cache or EA Desktop.
`tools/refresh_standalone_license.py` still requires a separately confirmed
binding for every other content ID; it does not assume mode 4. Mapping the
other titles' hash algorithms and metadata selectors, followed by tests on
additional owned small games, is the next activation step. Denuvo, EA
AntiCheat, linked store handoffs, and cloud-save lifecycles are separate
unresolved paths.
