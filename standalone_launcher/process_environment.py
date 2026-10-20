"""Read a same-user Windows process environment for launch interoperability tests."""

from __future__ import annotations

import ctypes
import struct


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_BASIC_INFORMATION = 0
PROCESS_WOW64_INFORMATION = 26


class _ProcessBasicInformation(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("Reserved3", ctypes.c_void_p),
    ]


def _nt_success(status: int) -> bool:
    return ctypes.c_long(status).value >= 0


def read_process_environment(process_id: int, *, maximum_bytes: int = 8 * 1024 * 1024) -> dict[str, str]:
    """Return the UTF-16 environment of a same-user Windows process.

    Both native 64-bit and WOW64 32-bit targets are supported. The caller is
    responsible for keeping credential-bearing values out of logs.
    """
    if maximum_bytes <= 0 or maximum_bytes % 2:
        raise ValueError("maximum_bytes must be a positive even number")

    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll.dll")
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.ReadProcessMemory.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    ntdll.NtQueryInformationProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long

    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, process_id)
    if not handle:
        raise OSError(ctypes.get_last_error(), f"OpenProcess failed for PID {process_id}")

    def read(address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        received = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(
            handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(received)
        ):
            raise OSError(ctypes.get_last_error(), f"ReadProcessMemory failed at {address:#x}")
        return buffer.raw[: received.value]

    try:
        returned = ctypes.c_ulong()
        wow64_peb = ctypes.c_void_p()
        status = ntdll.NtQueryInformationProcess(
            handle,
            PROCESS_WOW64_INFORMATION,
            ctypes.byref(wow64_peb),
            ctypes.sizeof(wow64_peb),
            ctypes.byref(returned),
        )
        if not _nt_success(status):
            raise OSError(f"NtQueryInformationProcess(ProcessWow64Information) failed: {status:#x}")

        if wow64_peb.value:
            pointer_format = "<I"
            process_parameters_offset = 0x10
            environment_offset = 0x48
            peb_address = wow64_peb.value
        else:
            basic = _ProcessBasicInformation()
            status = ntdll.NtQueryInformationProcess(
                handle,
                PROCESS_BASIC_INFORMATION,
                ctypes.byref(basic),
                ctypes.sizeof(basic),
                ctypes.byref(returned),
            )
            if not _nt_success(status):
                raise OSError(f"NtQueryInformationProcess(ProcessBasicInformation) failed: {status:#x}")
            pointer_format = "<Q"
            process_parameters_offset = 0x20
            environment_offset = 0x80
            peb_address = basic.PebBaseAddress

        pointer_size = struct.calcsize(pointer_format)
        parameters_address = struct.unpack(
            pointer_format, read(peb_address + process_parameters_offset, pointer_size)
        )[0]
        environment_address = struct.unpack(
            pointer_format, read(parameters_address + environment_offset, pointer_size)
        )[0]
        if not environment_address:
            return {}

        payload = bytearray()
        chunk_size = 16 * 1024
        while len(payload) < maximum_bytes:
            chunk = read(environment_address + len(payload), min(chunk_size, maximum_bytes - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            terminator = next(
                (
                    offset
                    for offset in range(0, len(payload) - 3, 2)
                    if payload[offset : offset + 4] == b"\x00\x00\x00\x00"
                ),
                -1,
            )
            if terminator >= 0:
                payload = payload[: terminator + 2]
                break
        else:
            raise ValueError(f"environment block exceeded {maximum_bytes} bytes")

        text = bytes(payload).decode("utf-16-le", errors="strict")
        result: dict[str, str] = {}
        for entry in text.split("\0"):
            if not entry:
                continue
            separator = entry.find("=", 1 if entry.startswith("=") else 0)
            if separator < 0:
                continue
            result[entry[:separator]] = entry[separator + 1 :]
        return result
    finally:
        kernel32.CloseHandle(handle)
