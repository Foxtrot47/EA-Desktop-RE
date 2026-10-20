"""Read a fresh game challenge through EA's unmodified GetGameToken helper.

No challenge or IPC payload is logged or persisted. Layout evidence:
analysis/decomp/GetGameToken-main.json and GetGameToken-mapping-layout.json.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import struct
import subprocess
from ctypes import wintypes
from pathlib import Path

from .license import LicenseError

_HELPER_SHA256 = "81c2b298e20e077a74d58b166bc1ce09d4ddcd11b2690f3ca512eab019c7a163"
# File location of the shipped helper's IPC obfuscation table, not a license key.
_MASK_OFFSET = 34592
_MASK_LENGTH = 21
_MAPPING_SIZE = 4096
_PAYLOAD_SIZE = 4000


def _mapping_string(payload: bytes, offset: int) -> tuple[str, int]:
    if offset + 4 > len(payload):
        raise LicenseError("truncated game-token mapping")
    length = struct.unpack_from(">I", payload, offset)[0]
    start = offset + 4
    end = start + length
    if end > len(payload):
        raise LicenseError("invalid game-token mapping string length")
    try:
        return payload[start:end].decode("utf-8"), end
    except UnicodeDecodeError:
        raise LicenseError("invalid game-token mapping encoding") from None


def decode_game_token_mapping(mapping: bytes, mask: bytes) -> str:
    """Validate the helper's revision, bounded map and GameToken entry."""
    if len(mapping) != _MAPPING_SIZE or len(mask) != _MASK_LENGTH:
        raise LicenseError("invalid game-token mapping size")
    if not struct.unpack_from("<Q", mapping)[0]:
        raise LicenseError("game-token helper did not update its mapping")
    payload = bytes(value ^ mask[index % len(mask)]
                    for index, value in enumerate(mapping[8:8 + _PAYLOAD_SIZE]))
    if struct.unpack_from(">I", payload)[0] != 1:
        raise LicenseError("unexpected game-token mapping entries")
    key, offset = _mapping_string(payload, 4)
    token, _ = _mapping_string(payload, offset)
    if key != "GameToken" or not token or any(ord(char) < 32 for char in token):
        raise LicenseError("game-token helper returned an invalid challenge")
    return token


def _mapping_kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD, wintypes.LPCWSTR]
    kernel.CreateFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel


def _run_helper(helper: Path, root: Path, handle: int, timeout: int) -> None:
    startup = subprocess.STARTUPINFO()
    startup.lpAttributeList = {"handle_list": [handle]}
    try:
        result = subprocess.run(
            [str(helper), str(handle)], cwd=root, startupinfo=startup,
            close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise LicenseError("EA game-token helper timed out") from None
    except OSError:
        raise LicenseError("could not execute EA game-token helper") from None
    if result.returncode:
        raise LicenseError("EA game-token helper failed")


def read_game_token(install_location: Path, helper: Path, *, timeout: int = 30) -> str:
    """Run EA's helper in the game's directory with only its mapping inherited."""
    if os.name != "nt":
        raise LicenseError("EA game-token collection requires Windows")
    root = install_location.resolve()
    helper = helper.resolve()
    binary = helper.read_bytes()
    if hashlib.sha256(binary).hexdigest() != _HELPER_SHA256:
        raise LicenseError("unrecognized EA game-token helper build")
    if not (root / "dbdata.dll").is_file() or (helper.parent / "dbdata.dll").exists():
        raise LicenseError("game-token DLL is missing or its search path is ambiguous")
    mask = binary[_MASK_OFFSET:_MASK_OFFSET + _MASK_LENGTH]

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p),
                    ("inherit", wintypes.BOOL)]

    security = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
    kernel = _mapping_kernel()
    handle = kernel.CreateFileMappingW(wintypes.HANDLE(-1), ctypes.byref(security),
                                       4, 0, _MAPPING_SIZE, None)
    if not handle:
        raise LicenseError("could not create game-token mapping")
    view = None
    try:
        view = kernel.MapViewOfFile(handle, 0xF001F, 0, 0, _MAPPING_SIZE)
        if not view:
            raise LicenseError("could not access game-token mapping")
        ctypes.memset(view, 0, _MAPPING_SIZE)
        _run_helper(helper, root, handle, timeout)
        return decode_game_token_mapping(ctypes.string_at(view, _MAPPING_SIZE), mask)
    finally:
        if view:
            ctypes.memset(view, 0, _MAPPING_SIZE)
            kernel.UnmapViewOfFile(view)
        kernel.CloseHandle(handle)
