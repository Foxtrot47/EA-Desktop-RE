# BFN process-name diagnostic

These are inert .NET 8 console executables built from `Program.cs`. They only
sleep. They do not implement EA IPC, client windows/readiness, service
registration, network access, or game/anti-cheat hooks. They are **not EA
Desktop or EA Background Service**, even though their filenames match.

Build from the repository root using the installed .NET SDK:

```powershell
dotnet build tools/process_name_probe/ProcessNameProbe.csproj -c Release -p:AssemblyName=EADesktop -o artifacts/diagnostics/process_name_probe/desktop
dotnet build tools/process_name_probe/ProcessNameProbe.csproj -c Release -p:AssemblyName=EABackgroundService -o artifacts/diagnostics/process_name_probe/background-service
```

The approved comparison kept the real EA Desktop folder renamed and its
original registered executable path absent. It did not alter the registry or
installed game/anti-cheat files. Do not restore or rename anything automatically.

With all real EA/BFN processes closed, run comparisons **sequentially**, using
new output filenames:

```powershell
python tools/test_bfn_direct_lsx.py --seconds 30 --disable-overlay --answer-session --name-probe desktop --output analysis/runtime/bfn_desktop_probe_test.json
python tools/test_bfn_direct_lsx.py --seconds 30 --disable-overlay --answer-session --name-probe background-service --output analysis/runtime/bfn_background_probe_test.json
```

For an interactive sign-in test, increase `--seconds` to `120`, press Enter in
BFN, and allow for its normal initial network timeouts. All test-owned
processes, including the probe, are closed at the end. This is a bounded
diagnostic. Normal prototype launching is now integrated through
`tools/launch_standalone_game.py` (installed directory) and the library GUI;
those paths keep the helpers alive until the game exits instead of using this
diagnostic's fixed time budget.

The JSON's `name_probe` records the inert process's PID, path, executable and
assembly hashes, and exit code. The deliberately preserved probe PID is not
counted in `desktop_observed`, which records additional Desktop-named
processes; **do not interpret that field alone as absence of the probe**.
The helper refuses unexpected probe process names. Name-only comparisons also
refuse pre-existing real EA/BFN processes, including the background service.

## Observed 2026-10-20

- No probe + missing real EA Desktop path: BFN exited before LSX.
- Desktop-named probe: LSX handshake and fresh EA game-code handoff worked.
  A 120-second repeat reached the public hub, confirmed by the user.
- Background-service-named probe: BFN exited before LSX.

An inert Desktop-named process was sufficient for this tested startup path;
the exact native discovery API/check is not statically established. A process
named `EADesktop.exe` still exists during these tests, but the genuine EA
Desktop software is not running. Friends, block-list and achievements replies,
matchmaking, extended play, and normal GUI integration remain outside this
proof.
