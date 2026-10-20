"""Render and run DiP touchup commands without a command shell."""

from __future__ import annotations

import ctypes
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .install import InstallError, safe_relative_path
from .manifest import DipManifest, resolve_manifest_locale


@dataclass(frozen=True)
class TouchupInvocation:
    executable: Path
    arguments: tuple[str, ...]
    working_directory: Path


def windows_command_line_to_argv(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    pointer = shell32.CommandLineToArgvW(value, ctypes.byref(count))
    if not pointer:
        raise ctypes.WinError()
    try:
        return tuple(pointer[index] for index in range(count.value))
    finally:
        ctypes.windll.kernel32.LocalFree(pointer)


def build_touchup_invocation(
    manifest: DipManifest,
    install_location: Path,
    *,
    locale: str,
    operation: str = "install",
) -> TouchupInvocation:
    templates = {
        "install": manifest.touchup.install_parameters,
        "update": manifest.touchup.update_parameters,
        "repair": manifest.touchup.repair_parameters,
    }
    if operation not in templates:
        raise ValueError(f"unsupported touchup operation {operation!r}")
    selected_locale = resolve_manifest_locale(manifest, locale)
    root = install_location.resolve()
    manifest_path = manifest.touchup.file_path.lstrip("/\\")
    executable = (root / safe_relative_path(manifest_path)).resolve()
    try:
        executable.relative_to(root)
    except ValueError:
        raise InstallError("touchup executable escapes install root") from None
    if not executable.is_file():
        raise InstallError(f"touchup executable is missing: {executable}")
    rendered = templates[operation].format(
        locale=selected_locale,
        installLocation=str(root),
    )
    return TouchupInvocation(
        executable=executable,
        arguments=windows_command_line_to_argv(rendered),
        working_directory=root,
    )


def run_touchup(invocation: TouchupInvocation, *, timeout: int = 1800) -> int:
    try:
        completed = subprocess.run(
            [str(invocation.executable), *invocation.arguments],
            cwd=invocation.working_directory,
            shell=False,
            timeout=timeout,
            check=False,
        )
        return completed.returncode
    except OSError as exc:
        if getattr(exc, "winerror", None) != 740:
            raise
        return run_touchup_elevated(invocation, timeout=timeout)


def run_touchup_elevated(invocation: TouchupInvocation, *, timeout: int = 1800) -> int:
    """Run the signed EA touchup through Windows UAC and return its exit code."""
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(invocation.executable)
    info.lpParameters = subprocess.list2cmdline(list(invocation.arguments))
    info.lpDirectory = str(invocation.working_directory)
    info.nShow = 1
    shell32 = ctypes.windll.shell32
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError()
    try:
        wait = ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, timeout * 1000)
        if wait == 0x00000102:
            raise TimeoutError("EA touchup timed out")
        if wait != 0:
            raise ctypes.WinError()
        exit_code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise ctypes.WinError()
        return int(exit_code.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
