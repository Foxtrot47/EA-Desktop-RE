"""Owned inert processes for isolating BFN's client-name startup hypothesis."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
PROBE_NAMES = {
    "desktop": "EADesktop.exe",
    "background-service": "EABackgroundService.exe",
}


def probe_path(kind: str) -> Path:
    return ROOT / "artifacts" / "diagnostics" / "process_name_probe" / kind / PROBE_NAMES[kind]


def stop_owned_probe(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def record_probe(process: subprocess.Popen, target: Path, kind: str, result: dict) -> None:
    result["name_probe"] = {
        "kind": kind, "name": target.name, "pid": process.pid,
        "executable": str(target),
        "exe_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "assembly_sha256": hashlib.sha256(target.with_suffix(".dll").read_bytes()).hexdigest(),
        "implements_ea_ipc_or_readiness": False,
    }


@contextmanager
def running_name_probe(kind: str | None, device, result: dict):
    """Yield an explicitly labelled probe PID, then stop only that owned child."""
    if kind is None:
        yield None
        return
    target = probe_path(kind)
    if not target.is_file():
        raise RuntimeError("Build the process-name diagnostic first; probe executable is missing")
    process = subprocess.Popen(
        [str(target)], cwd=target.parent,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        names = {item.pid: item.name for item in device.enumerate_processes()}
        if process.poll() is not None or names.get(process.pid) != target.name:
            raise RuntimeError("The inert name probe did not remain running with the expected process name")
        record_probe(process, target, kind, result)
        yield process.pid
    finally:
        stop_owned_probe(process)
        if "name_probe" in result:
            result["name_probe"]["exit_code"] = process.returncode
