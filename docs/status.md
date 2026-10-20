# Compatibility

Results below describe observed runs, not guarantees for every build or machine.

| Title / feature | Confirmed | Remaining limits |
| --- | --- | --- |
| EA account and library | Independent sign-in, token refresh, owned-library retrieval | Requires locally supplied, version-pinned EA application files |
| Download and installation | Package planning, extraction with CRC checks, signed installer finalization | Not a complete update/repair client |
| Battle for Neighborville | EA-signed license, fresh game-auth codes, online public hub | Inert Desktop-named helper; broader social features and extended play unverified |
| Unravel Two | Fresh game-ticket exchange, signed license, rendered opening cinematic after restart | Diagnostic only; normal launcher integration and gameplay input unverified |
| Medal of Honor: Pacific Assault | Fresh signed license and direct game launch | Gameplay input unverified |
| Battlefield 3 / 4 / Hardline | No standalone Battlelog launch verification | Browser authentication, local handoff, and join tickets need investigation |
| Other games | No general compatibility claim | Per-title licensing, SDK calls, and anti-cheat requirements vary |

## Important distinctions

- EA account authentication, local signed licenses, SDK game tokens, and
  game-server authentication are separate layers.
- Unravel's successful SDK ticket exchange is not an independent identification
  of every protection layer in that build.
- A shared anti-cheat product does not imply identical launch/auth behavior.
- The inert `EADesktop.exe` helper is our own sleeping process, not the genuine EA app.
- This project does not patch games, disable anti-cheat, or invent entitlement data.

## Known gaps

- Unravel diagnostic achievement and presence requests remain unanswered. They
  were not established as the cause of its earlier black screen.
- Friends, cloud saves, linked-store handoffs, and broad matchmaking support
  are not complete.
- Research notes contain historical intermediate failures. Prefer this page for
  the current compatibility summary.

Detailed reports are indexed in [research notes](README.md). Raw local evidence,
account state, and proprietary analysis inputs are intentionally not in Git.
