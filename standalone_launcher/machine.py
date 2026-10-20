"""EA Desktop 13.809 mode-4 machine identity reconstruction.

The public helpers are split into collection and serialization so tests and
other front ends can inject captured values without reading the local machine.
No function in this module prints hardware identifiers.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import re
import struct
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .pcsign import PcSignPayload, derive_mid, normalize_pc_sign_mac


@dataclass(frozen=True)
class AdapterAddress:
    if_type: int
    physical_address: bytes


@dataclass(frozen=True)
class Mode4Inputs:
    baseboard_manufacturer: str
    baseboard_serial: str
    bios_manufacturer: str
    bios_serial: str
    system_volume_serial: int
    video_pnp_device_id: str
    cpu_vendor: str
    cpuid_leaf1_edx: int
    cpuid_leaf1_eax: int
    cpu_brand: str


@dataclass(frozen=True)
class PcSignMachineFields:
    fingerprint_source: bytes
    fingerprint_sha1_hex: str
    normalized_mac: str
    mid: str
    disk_serial: str
    gpu_device_id: int


def _bounded_wmi(value: object, capacity: int) -> str:
    """Model EA's fixed WCHAR buffer, including its terminal NUL slot."""
    if value is None:
        return ""
    return str(value)[: capacity - 1]


def _encode_legacy_utf8(value: str) -> bytes:
    """Encode UTF-16 code units the same way as EADesktop's local helper.

    Its converter processes every 16-bit unit independently rather than
    combining surrogate pairs.  Hardware strings are normally ASCII, but the
    distinction is retained for byte-exact compatibility.
    """
    raw = value.encode("utf-16-le", errors="surrogatepass")
    output = bytearray()
    for offset in range(0, len(raw), 2):
        unit = raw[offset] | raw[offset + 1] << 8
        if unit < 0x80:
            output.append(unit)
        elif unit < 0x800:
            output.extend((0xC0 | unit >> 6, 0x80 | unit & 0x3F))
        else:
            output.extend(
                (0xE0 | unit >> 12, 0x80 | (unit >> 6) & 0x3F, 0x80 | unit & 0x3F)
            )
    return bytes(output)


def build_mode4_fingerprint(inputs: Mode4Inputs) -> bytes:
    """Serialize the exact byte string passed to EA's algorithm-1 hasher."""
    wmi_prefix = ";".join(
        (
            _bounded_wmi(inputs.baseboard_manufacturer, 128),
            _bounded_wmi(inputs.baseboard_serial, 128),
            _bounded_wmi(inputs.bios_manufacturer, 128),
            _bounded_wmi(inputs.bios_serial, 64),
        )
    ) + ";"
    prefix = _encode_legacy_utf8(wmi_prefix)
    volume = f"{inputs.system_volume_serial & 0xFFFFFFFF:08X}"
    video = _bounded_wmi(inputs.video_pnp_device_id, 1024)
    cpu = (
        f"{inputs.cpu_vendor};"
        f"{inputs.cpuid_leaf1_edx & 0xFFFFFFFF:08X}"
        f"{inputs.cpuid_leaf1_eax & 0xFFFFFFFF:08X};"
        f"{inputs.cpu_brand.lstrip(' ')};"
    )
    return prefix + volume.encode("ascii") + b";" + video.encode("utf-8") + b";" + cpu.encode("latin-1")


def fingerprint_sha1_hex(fingerprint_source: bytes) -> str:
    """Return the lowercase 40-character digest used before MAC binding."""
    return hashlib.sha1(fingerprint_source).hexdigest()


def select_best_mac(adapters: Iterable[AdapterAddress]) -> bytes:
    """Reproduce EA's three-pass GetAdaptersAddresses MAC selection."""
    candidates = [adapter for adapter in adapters if adapter.physical_address]
    wired_or_wifi = {6, 71}  # IF_TYPE_ETHERNET_CSMACD, IF_TYPE_IEEE80211
    for predicate in (
        lambda item: item.if_type in wired_or_wifi and not (item.physical_address[0] & 0x02),
        lambda item: item.if_type in wired_or_wifi,
        lambda item: True,
    ):
        match = next((item.physical_address for item in candidates if predicate(item)), None)
        if match is not None:
            return match
    return b""


def format_mac_for_pc_sign(address: bytes) -> str:
    if not address:
        return "$"
    return normalize_pc_sign_mac("-".join(f"{byte:02x}" for byte in address))


def gpu_device_id(video_pnp_device_id: str) -> int:
    match = re.search(r"DEV_([0-9A-Fa-f]{4})", video_pnp_device_id)
    return int(match.group(1), 16) if match else 0


def make_machine_fields(
    inputs: Mode4Inputs,
    adapters: Iterable[AdapterAddress],
    disk_serial: str,
) -> PcSignMachineFields:
    source = build_mode4_fingerprint(inputs)
    digest = fingerprint_sha1_hex(source)
    mac = format_mac_for_pc_sign(select_best_mac(adapters))
    return PcSignMachineFields(
        fingerprint_source=source,
        fingerprint_sha1_hex=digest,
        normalized_mac=mac,
        mid=derive_mid(digest, mac),
        disk_serial=_bounded_wmi(disk_serial, 128),
        gpu_device_id=gpu_device_id(inputs.video_pnp_device_id),
    )


def make_pc_sign_payload(
    fields: PcSignMachineFields,
    timestamp: str,
    signing_version: int,
) -> PcSignPayload:
    if not 1 <= signing_version <= 4:
        raise ValueError("signing version must be 1 through 4")
    return PcSignPayload(
        mid=fields.mid,
        bsn=None,
        msn=None,
        hsn=fields.disk_serial,
        mac=fields.normalized_mac,
        gid=fields.gpu_device_id,
        ts=timestamp,
        av="v1",
        sv=f"v{signing_version}",
    )


def _native_cpuid(leaf: int, subleaf: int = 0) -> tuple[int, int, int, int]:
    """Execute CPUID on 64-bit Windows using a short, fixed machine-code stub."""
    if struct.calcsize("P") != 8 or not hasattr(ctypes, "windll"):
        raise OSError("native CPUID collector requires 64-bit Windows")
    # push rbx; eax=ecx; ecx=edx; cpuid; store eax/ebx/ecx/edx via r8; pop; ret
    code = bytes.fromhex("53 8B C1 8B CA 0F A2 41 89 00 41 89 58 04 41 89 48 08 41 89 50 0C 5B C3")
    kernel32 = ctypes.windll.kernel32
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    address = kernel32.VirtualAlloc(None, len(code), 0x3000, 0x40)
    if not address:
        raise ctypes.WinError()
    try:
        ctypes.memmove(address, code, len(code))
        output = (ctypes.c_uint32 * 4)()
        function = ctypes.WINFUNCTYPE(
            None, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
        )(address)
        function(leaf, subleaf, output)
        return tuple(int(value) for value in output)  # type: ignore[return-value]
    finally:
        if not kernel32.VirtualFree(ctypes.c_void_p(address), 0, 0x8000):
            raise ctypes.WinError()


def collect_cpu_identity(
    cpuid: Callable[[int, int], tuple[int, int, int, int]] = _native_cpuid,
) -> tuple[str, int, int, str]:
    _, vendor_ebx, vendor_ecx, vendor_edx = cpuid(0, 0)
    vendor = struct.pack("<III", vendor_ebx, vendor_edx, vendor_ecx).rstrip(b"\0").decode("latin-1")
    signature, _, _, feature_edx = cpuid(1, 0)
    max_extended, _, _, _ = cpuid(0x80000000, 0)
    brand_bytes = b""
    if max_extended >= 0x80000004:
        brand_bytes = b"".join(struct.pack("<IIII", *cpuid(leaf, 0)) for leaf in range(0x80000002, 0x80000005))
    brand = brand_bytes.split(b"\0", 1)[0].decode("latin-1").lstrip(" ")
    return vendor, feature_edx, signature, brand


_CIM_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$baseboard = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
$bios = Get-CimInstance Win32_BIOS | Select-Object -First 1
$video = Get-CimInstance Win32_VideoController | Select-Object -First 1
$disk = Get-CimInstance Win32_DiskDrive | Select-Object -First 1
$adapters = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object {
  [ordered]@{ if_type = [int]$_.NetworkInterfaceType; mac = $_.GetPhysicalAddress().ToString() }
}
[ordered]@{
  baseboard_manufacturer = $baseboard.Manufacturer
  baseboard_serial = $baseboard.SerialNumber
  bios_manufacturer = $bios.Manufacturer
  bios_serial = $bios.SerialNumber
  video_pnp_device_id = $video.PNPDeviceID
  disk_serial = $disk.SerialNumber
  adapters = @($adapters)
} | ConvertTo-Json -Compress -Depth 4
"""


def _collect_cim_snapshot() -> dict[str, object]:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _CIM_SCRIPT],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _system_volume_serial() -> int:
    windows = ctypes.create_unicode_buffer(260)
    if not ctypes.windll.kernel32.GetWindowsDirectoryW(windows, len(windows)):
        raise ctypes.WinError()
    root = windows.value[: windows.value.index("\\") + 1]
    serial = ctypes.c_uint32()
    if not ctypes.windll.kernel32.GetVolumeInformationW(
        root, None, 0, ctypes.byref(serial), None, None, None, 0
    ):
        raise ctypes.WinError()
    return int(serial.value)


def collect_local_machine_fields() -> PcSignMachineFields:
    """Collect all local inputs without writing them to stdout or disk."""
    snapshot = _collect_cim_snapshot()
    vendor, feature_edx, signature, brand = collect_cpu_identity()
    inputs = Mode4Inputs(
        baseboard_manufacturer=_bounded_wmi(snapshot.get("baseboard_manufacturer"), 128),
        baseboard_serial=_bounded_wmi(snapshot.get("baseboard_serial"), 128),
        bios_manufacturer=_bounded_wmi(snapshot.get("bios_manufacturer"), 128),
        bios_serial=_bounded_wmi(snapshot.get("bios_serial"), 64),
        system_volume_serial=_system_volume_serial(),
        video_pnp_device_id=_bounded_wmi(snapshot.get("video_pnp_device_id"), 1024),
        cpu_vendor=vendor,
        cpuid_leaf1_edx=feature_edx,
        cpuid_leaf1_eax=signature,
        cpu_brand=brand,
    )
    adapters = []
    for adapter in snapshot.get("adapters", []):
        if not isinstance(adapter, dict):
            continue
        compact = str(adapter.get("mac") or "")
        if len(compact) % 2 or not re.fullmatch(r"[0-9A-Fa-f]*", compact):
            continue
        adapters.append(AdapterAddress(int(adapter.get("if_type") or 0), bytes.fromhex(compact)))
    return make_machine_fields(inputs, adapters, str(snapshot.get("disk_serial") or ""))
