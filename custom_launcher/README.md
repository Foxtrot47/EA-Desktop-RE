# EA custom-launcher transitional compatibility prototype

This brokered program is retained as a behavioral comparison tool while the
standalone modules replace EA Desktop. It is not the final launcher architecture.

This prototype owns game discovery and launch intent while using
EA's signed launcher as the authentication, entitlement, activation, anti-cheat,
elevation, cloud-save, and process broker.

EA Desktop does not need to be running before a launch. The prototype starts
`EALauncher.exe -silent`, waits for the broker process, and then submits the
game request. `EADesktop.exe` remains resident in the tray while the game runs
because this build keeps its license manager and game process coordinator in
that executable.

It never reads EA cookies, bearer tokens, refresh tokens, licenses, or protected
cache contents. Commands print their intended URI by default. Add `--execute`
only when you want to send the request to EA Desktop.

```powershell
python .\custom_launcher\ea_custom_launcher.py status
python .\custom_launcher\ea_custom_launcher.py discover
python .\custom_launcher\ea_custom_launcher.py activity --offer Origin.OFR.50.0004343
python .\custom_launcher\ea_custom_launcher.py configure --name "Battlefield 1" --path "E:\Games\Battlefield 1" --offer Origin.OFR.50.example
python .\custom_launcher\ea_custom_launcher.py launch --name "Battlefield 1" --execute
python .\custom_launcher\ea_custom_launcher.py launch --offer Origin.OFR.50.0000001
python .\custom_launcher\ea_custom_launcher.py launch --slug battlefield-5 --execute
python .\custom_launcher\ea_custom_launcher.py uri library/open --execute
python .\custom_launcher\gui.py
```

On Windows, `run_launcher.cmd` starts the GUI without keeping a console window
open.

`discover` reads Windows uninstall registration and correlates a game with an
offer/content ID only when an EA Desktop launch log already recorded the same
working directory. Unknown IDs remain `null`; supply an offer ID or slug to the
launch command or save it in the UI instead of guessing one. User mappings are
stored by default in `%LOCALAPPDATA%\EA Custom Launcher\library.json`.

The UI's **Open EA library / Sign in** button hands control to EA Desktop. A
game's **Launch** button sends the exact `origin2://game/launch` request used by
the installed client. Install/update/repair still open in the official client
because those operations require its authenticated background-service protocol.

`--no-cold-start` is available for diagnostics when a request should be sent
without first starting EA Desktop silently.
