# EA Desktop 13.809.0.6322 reverse-engineering plan

Target installation: `C:\Program Files\Electronic Arts\EA Desktop\EA Desktop`

IDA installation: `E:\Software\IDA Professional 9.1`

This investigation uses static analysis first. Findings must distinguish observed
binary/resource evidence from inferred behavior. Runtime behavior is only claimed
after a separate trace captures it.

## Questions and evidence

| Stage | Question | Primary artifacts | Evidence sought | Status |
|---|---|---|---|---|
| 0 | What exact build and components are installed? | whole installation | version, signatures, hashes, imports, resources | complete |
| 1 | How does sign-in work? | `EADesktop.exe`, `EALocalHostSvc.exe` | auth URLs, OAuth/OIDC parameters, browser callbacks, token storage and refresh paths | complete; configuration URLs and at-rest cache format remain open |
| 2 | How are owned games and game metadata retrieved? | `EADesktop.exe`, `EABackgroundService.exe` | entitlement/catalog endpoints, request builders, response models, cache/database paths | complete |
| 3 | How are downloads and installs performed? | `EABackgroundService.exe`, legacy package manager resources | manifest acquisition, chunk/protocol code, staging, verification, elevation, install state | complete statically and validated with a full MOHPA extraction/touchup |
| 4 | How are games activated? | `EADesktop.exe`, `GetGameToken.exe`, title `Activation.dll`/`ActivationUI.exe` | cached/new license paths, RTP validation, Denuvo reactivation, local handoff | cached-license direct path complete; new-license service and Denuvo remain open |
| 5 | How are installed games started? | title manifest/runtime, `EALauncher.exe`, `EALaunchHelper.exe`, store proxies | executable selection, RTP environment, process creation, external-store routing | direct legacy path implemented and live-tested; EAAC/Steam/Epic standalone paths open |
| 6 | What remains unknown without runtime evidence? | logs, caches, optional passive capture | concrete request sequences and data values | documented in `REPORT.md` |

## Outputs

- `artifacts/manifest.json`: exact copied inputs and hashes.
- `analysis/index/*.json`: idalib inventories and keyword/xref indexes.
- `analysis/decomp/*.json`: focused function pseudocode and call relationships.
- `REPORT.md`: evidence-backed architecture and end-to-end flows.

