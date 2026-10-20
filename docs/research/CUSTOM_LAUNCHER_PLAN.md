# Custom launcher reconstruction plan

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Exact external protocol commands, identifiers, URI parameters, and registry handlers | complete |
| 2 | Localhost, BGS IPC, and LSX trust-boundary reconstruction | complete for integration decision |
| 3 | Installed-game discovery and offer-ID correlation | prototype complete |
| 4 | Brokered login and launch implementation | transitional prototype complete |
| 5 | Library/catalog acquisition design | installed-library strategy complete; full account library requires supported account API |
| 6 | Install/update/repair controls | direct BGS protocol recovery in progress |
| 7 | Desktop UI, state monitoring, and packaging | UI and passive monitoring complete; double-click runner provided |
| 8 | Launch from a stopped EA session | silent baseline complete; standalone replacement is the target |

The implementation target is a launcher that presents the user's games and
initiates official EA operations. This remains the comparison baseline while
the standalone implementation replaces account login, ownership, licenses,
DRM, anti-cheat, elevated launch, and signed download URL handling.
