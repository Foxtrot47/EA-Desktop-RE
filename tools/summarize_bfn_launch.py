#!/usr/bin/env python3
"""Print only redacted process-launch lines from EA Desktop's verbose log."""

from __future__ import annotations

import re
from pathlib import Path


LOG = Path.home() / "AppData/Local/Electronic Arts/EA Desktop/Logs/EADesktopVerbose.log"
COMPONENTS = (
    "environmentHelpers::validateLauncher",
    "environmentHelpers::getPathAndArgsLaunchParams",
    "ProcessWin::createProcess",
    "ProcessCoordinator::FsmHost::launchGameProcess",
    "ProcessCoordinator::handleLaunchGame",
    "ClientLauncher::requestLicenseAndLaunch",
)


def redact(value: str) -> str:
    value = re.sub(r"(?i)(token|secret|auth|password|key|code|userid|personaid)([=:])([^\s,;\]]+)", r"\1\2[redacted]", value)
    value = re.sub(r"\b\d{8,}\b", "[numeric-id]", value)
    value = re.sub(r"\b[A-Za-z0-9_./+=-]{32,}\b", "[long-value]", value)
    return value


def main() -> None:
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[2026-10-19T18:26:" not in line:
            continue
        if not any(component in line for component in COMPONENTS):
            continue
        if "<LSX>" in line:
            continue
        print(redact(line[:1000]))


if __name__ == "__main__":
    main()
